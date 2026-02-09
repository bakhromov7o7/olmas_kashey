import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from olmas_kashey.core.settings import settings

from loguru import logger
from sqlalchemy import select
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
from olmas_kashey.telegram.entity_classifier import EntityClassifier
from olmas_kashey.services.query_plan import QueryPlanner

class GroupDiscoveryService:
    def __init__(self, client: OlmasClient, planner: QueryPlanner):
        self.client = client
        self.planner = planner

    async def run(self, iterations: int = 1) -> None:
        """
        Execute discovery pipeline for N iterations (keywords).
        """
        for _ in range(iterations):
            keyword = await self.planner.get_next_query()
            if not keyword:
                logger.info("No query available (rate limit or cooldown). Stopping discovery run.")
                break
            
            await self._process_keyword(keyword)

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
            raw_entities = await self.client.search_public_channels(keyword, limit=50)
            
            # 2. Process Results
            processed_count = 0
            async for session in get_db():
                # Add run record to DB first to get ID? Or add later?
                # Best to add later or add now and update. 
                # Let's add at end for atomic-ish "run completed" or keep session open?
                # We'll stick to single session for the batch if possible, or per-item.
                # Per-item upsert is safer for long runs, but batch is faster.
                # Let's do batch upsert logic.
                
                for raw in raw_entities:
                    # Filter scam/fake
                    if getattr(raw, "scam", False) or getattr(raw, "fake", False):
                        continue

                    classified = EntityClassifier.classify(raw)
                    
                    if classified.kind != EntityKind.GROUP:
                        continue

                    # Upsert Entity
                    stmt = select(Entity).where(Entity.tg_id == int(classified.tg_id))
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
                    
                    # Auto-join if enabled (only for new groups)
                    if not existing and settings.service.enable_auto_join:
                        try:
                            await asyncio.sleep(2)  # Rate limit delay
                            await self.client.join_channel(classified.username or classified.tg_id)
                            
                            # Update membership state
                            mem.state = MembershipState.JOINED
                            mem.joined_at = datetime.now(timezone.utc)
                            
                            logger.info(f"Auto-joined group: {classified.title or classified.username}")
                            
                            # Emit join event
                            join_event = Event(
                                entity_id=entity_id,
                                type="auto_joined",
                                payload={"source_keyword": keyword}
                            )
                            session.add(join_event)
                        except Exception as join_err:
                            logger.warning(f"Failed to auto-join {classified.title}: {join_err}")
                
                # 3. Finalize Run Record
                run_record.finished_at = datetime.now(timezone.utc)
                run_record.results_count = processed_count
                run_record.success = True
                session.add(run_record)
                await session.commit()
                
            logger.info(f"Finished keyword '{keyword}': {processed_count} groups found.")

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
