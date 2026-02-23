import asyncio
import random
from datetime import datetime, timezone
from typing import List, Optional, Any, Union

from olmas_kashey.core.settings import settings

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert 
# Note: sqlite doesn't support pg_insert properly for upsert in same syntax usually, 
# but generic sqlalchemy 2.0 has support or we check existence.
# For compatibility with SQLite (which we use for dev) and Postgres, 
# we should use a merge or check-then-update approach if not using specialized dialect.
# Or use `sqlalchemy.dialects.sqlite.insert` for sqlite.
# To be safe and portable-ish without complex switching: 
# Select by tg_id -> if exists update, else insert.

from olmas_kashey.core.types import EntityKind
from olmas_kashey.db.models import Entity, SearchRun, Event, Membership, MembershipState
from olmas_kashey.db.session import get_db
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline
from olmas_kashey.services.query_plan import QueryPlanner
from olmas_kashey.services.control_bot import TopicsChangedInterruption
from olmas_kashey.services.smart_advisor import smart_advisor
from olmas_kashey.services.link_crawler import LinkCrawlerService
from olmas_kashey.services.evolution import keyword_evolution_service

class GroupDiscoveryService:
    def __init__(self, client: OlmasClient, planner: QueryPlanner, bot: Optional[Any] = None):
        self.client = client
        self.planner = planner
        self.pipeline = DiscoveryPipeline(client, bot=bot)
        self.crawler = LinkCrawlerService(client)
        self.bot = bot

    async def run(self, iterations: int = 1, sig_handler: Optional[Any] = None) -> None:
        """
        Execute discovery pipeline for N iterations (keywords).
        """
        for i in range(iterations):
            if sig_handler and sig_handler.check_shutdown:
                break
            
            if self.bot:
                await self.bot.wait_if_paused()

            keyword = await self.planner.get_next_query()
            if not keyword:
                logger.debug("No query available (rate limit or cooldown). Stopping discovery run.")
                break
            
            try:
                await self._process_keyword(keyword)
            except TopicsChangedInterruption:
                logger.info("Topic change detected during discovery. Re-planning...")
                if self.bot:
                    self.bot.topics_updated = False
                continue
            
            # Add batch delay between iterations to be more human-like
            if i < iterations - 1:
                delay = settings.discovery.batch_interval_seconds
                if self.bot and getattr(self.bot, 'eco_mode', False):
                    delay = max(120, delay)
                
                logger.debug(f"Iteration {i+1} complete. Waiting {delay}s before next batch...")
                
                if sig_handler or self.bot:
                    end_time = asyncio.get_running_loop().time() + delay
                    while not (sig_handler and sig_handler.check_shutdown):
                        if self.bot:
                            await self.bot.wait_if_paused()
                            if self.bot.manual_resume_event.is_set():
                                self.bot.manual_resume_event.clear()
                                await self.bot.bot_client.send_message(
                                    settings.telegram.authorized_user_id,
                                    "⚙️ Discovery qayta ishga tushdi..."
                                )
                                break
                        
                        now = asyncio.get_running_loop().time()
                        remaining = end_time - now
                        if remaining <= 0:
                            break
                            
                        sleep_duration = min(5, remaining)
                        if sig_handler:
                            if await sig_handler.sleep(sleep_duration):
                                break
                        else:
                            await asyncio.sleep(sleep_duration)
                else:
                    await asyncio.sleep(delay)

    async def _process_keyword(self, keyword: str) -> None:
        logger.info(f"Processing keyword: '{keyword}'")
        run_record = SearchRun(
            keyword=keyword,
            started_at=datetime.now(timezone.utc),
            results_count=0,
            success=False
        )

        try:
            # 1. Search
            # We assume client.search_public_channels returns a list of Telethon entities (Channel/Chat)
            # The client wrapper we wrote earlier has this method.
            candidates = await self.pipeline.search_candidates(keyword)
            
            # 2. Process Results
            processed_count = 0
            new_results_count = 0
            new_entities = []
            
            async for session in get_db():
                # Add run record to DB first to get ID? Or add later?
                # Best to add later or add now and update. 
                # Let's add at end for atomic-ish "run completed" or keep session open?
                # We'll stick to single session for the batch if possible, or per-item.
                # Per-item upsert is safer for long runs, but batch is faster.
                # Let's do batch upsert logic.
                
                for candidate in candidates:
                    if self.bot:
                        await self.bot.wait_if_paused()

                    # Filter scam/fake
                    classified = candidate.entity
                    
                    if classified.kind != EntityKind.GROUP:
                        continue

                    # Upsert Entity
                    stmt = select(Entity).where(Entity.tg_id == int(classified.tg_id)).options(selectinload(Entity.memberships))
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    
                    now = datetime.now(timezone.utc)

                    if existing:
                        existing.last_seen_at = now
                        if classified.title: existing.title = classified.title
                        if classified.username: existing.username = classified.username
                        # existing.kind is likely already GROUP, but could update?
                        entity_id = existing.id
                    else:
                        new_entity = Entity(
                            tg_id=int(classified.tg_id),
                            username=classified.username,
                            title=classified.title,
                            kind=EntityKind.GROUP,
                            discovered_at=now,
                            last_seen_at=now
                        )
                        session.add(new_entity)
                        await session.flush() # get ID
                        entity_id = new_entity.id
                        new_entities.append(new_entity)
                        new_results_count += 1
                        
                        # Emit Discovery Event
                        event = Event(
                            entity_id=entity_id,
                            type="entity_discovered",
                            payload={"source_keyword": keyword}
                        )
                        session.add(event)
                        
                        # Initialize Membership state
                        # Check if membership already exists (unlikely for new entity but safety)
                        # Actually if new entity, no membership.
                        mem = Membership(
                            entity_id=entity_id,
                            state=MembershipState.NOT_JOINED,
                            last_checked_at=now
                        )
                        session.add(mem)

                    processed_count += 1
                    
                    # Auto-join if enabled (new groups OR existing but NOT_JOINED)
                    mem_to_join = None
                    if not existing:
                        mem_to_join = mem # The new one we just created
                    else:
                        if not existing.memberships:
                            # Auto-heal: create missing membership record for old legacy database entities
                            new_mem = Membership(
                                entity_id=existing.id,
                                state=MembershipState.NOT_JOINED,
                                last_checked_at=now
                            )
                            session.add(new_mem)
                            existing.memberships = new_mem
                            mem_to_join = new_mem
                        elif existing.memberships.state == MembershipState.NOT_JOINED:
                            mem_to_join = existing.memberships

                    if mem_to_join and settings.service.enable_auto_join:
                        try:
                            # Dynamic AI delay vs Static delay
                            if self.bot and getattr(self.bot, 'smart_mode', False):
                                delay = await smart_advisor.get_join_delay()
                                logger.info(f"Smart Mode active: Waiting {delay:.1f}s before joining {classified.username or classified.tg_id}")
                                await asyncio.sleep(delay)
                            else:
                                await asyncio.sleep(2)  # Normal Rate limit delay
                                
                            await self.client.join_channel(classified.username or classified.tg_id)
                            
                            # Update membership state
                            mem_to_join.state = MembershipState.JOINED
                            mem_to_join.joined_at = datetime.now(timezone.utc)
                            
                            logger.info(f"Auto-joined group: {classified.title or classified.username}")
                        
                            # Instant Telegram notification
                            if self.bot:
                                await self.bot.notify_join(classified.title or classified.username, classified.username)
                            
                            # Emit join event
                            session.add(join_event)

                            # 🚀 Recursive Discovery: Crawl newly joined group for more links
                            asyncio.create_task(self._crawl_and_save_links(classified.username or classified.tg_id, keyword))
                        except Exception as join_err:
                            logger.warning(f"Failed to auto-join {classified.title}: {join_err}")
                
                # 3. Finalize Run Record
                run_record.finished_at = datetime.now(timezone.utc)
                run_record.results_count = processed_count
                run_record.new_results_count = new_results_count
                run_record.success = True
                session.add(run_record)
                await session.commit()
                
            # 4. Trigger Evolution if we found enough new groups
            if new_results_count >= settings.discovery.evolution_threshold:
                logger.info(f"Triggering keyword evolution: found {new_results_count} new groups.")
                # We do this after commit/session close
                asyncio.create_task(keyword_evolution_service.evolve_from_entities(new_entities))
                
            logger.info(f"Finished keyword '{keyword}': {processed_count} groups found ({new_results_count} new).")

        except TopicsChangedInterruption:
            # Re-raise to be caught by run() loop
            raise
        except Exception as e:
            logger.error(f"Error processing keyword '{keyword}': {e}")
            run_record.finished_at = datetime.now(timezone.utc)
            run_record.success = False
            run_record.error = str(e)
            
            async for session in get_db():
                session.add(run_record)
                await session.commit()
            
            # Re-raise or suppress? 
            # If FloodWait, client handles it (retries or raises). 
            # If raised, we catch here.
            # If it's a critical error, maybe stop pipeline?
            # For now, log and continue to next keyword?
            # FloodWait usually implies we should stop for a while globally, 
            # but client wrapper sleeps. 
            pass

    async def _crawl_and_save_links(self, target: Union[int, str], source_keyword: str):
        """Background task to crawl a group and save found links as potential candidates."""
        try:
            logger.info(f"Background crawling started for {target}")
            # Wait a bit to not be too aggressive immediately after join
            await asyncio.sleep(random.uniform(5, 15))
            
            raw_links = await self.crawler.crawl_group(target)
            if not raw_links:
                return
                
            classified_entities = await self.crawler.filter_and_classify(raw_links)
            
            async for session in get_db():
                new_count = 0
                for entity in classified_entities:
                    # Check if exists
                    stmt = select(Entity).where(Entity.tg_id == int(entity.tg_id))
                    res = await session.execute(stmt)
                    if res.scalar_one_or_none():
                        continue
                        
                    # Save new candidate
                    now = datetime.now(timezone.utc)
                    new_ent = Entity(
                        tg_id=int(entity.tg_id),
                        username=entity.username,
                        title=entity.title,
                        kind=entity.kind,
                        discovered_at=now,
                        last_seen_at=now
                    )
                    session.add(new_ent)
                    await session.flush()
                    
                    # Init membership
                    mem = Membership(
                        entity_id=new_ent.id,
                        state=MembershipState.NOT_JOINED,
                        last_checked_at=now
                    )
                    session.add(mem)
                    
                    # Log event
                    event = Event(
                        entity_id=new_ent.id,
                        type="entity_crawled",
                        payload={"source_group": str(target), "original_keyword": source_keyword}
                    )
                    session.add(event)
                    new_count += 1
                    
                await session.commit()
                if new_count > 0:
                    logger.info(f"Crawler saved {new_count} new candidates from {target}")
                    
        except Exception as e:
            logger.error(f"Background crawl failed for {target}: {e}")
