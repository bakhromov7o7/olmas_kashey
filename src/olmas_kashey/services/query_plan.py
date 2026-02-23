import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Optional, Set
from loguru import logger
from sqlalchemy import select, update, desc

from olmas_kashey.core.settings import settings
from olmas_kashey.db.models import KeywordUsage, SearchRun
from olmas_kashey.db.session import get_db
from olmas_kashey.services.keyword_generator import KeywordGenerator
from olmas_kashey.services.evolution import keyword_evolution_service


class QueryPlanner:
    def __init__(self, seed: int = 42) -> None:
        self.generator = KeywordGenerator(seed=seed)
        self._keyword_cache: Optional[List[str]] = None
        self._current_index: int = 0  # Fallback round-robin index

    def _get_base_keywords(self) -> List[str]:
        # Always generate fresh to respect settings.discovery.allowed_topics changes
        return list(self.generator.generate())

    async def get_next_query(self) -> Optional[str]:
        """
        Returns the next keyword using adaptive planning.
        Prioritizes evolved keywords and implements backoff for failed ones.
        """
        base_keywords = self._get_base_keywords()
        evolved_keywords = await keyword_evolution_service.get_evolved_keywords()
        
        all_candidates = list(set(base_keywords + evolved_keywords))
        if not all_candidates:
            return None

        now = datetime.now(timezone.utc)
        
        async for session in get_db():
            # 1. Check recent performance and usage
            # We want keywords that:
            # - Haven't been used recently OR
            # - Have high success rate OR
            # - Are newly evolved
            
            # To keep it efficient, let's pick a subset of candidates that aren't on high backoff
            final_keywords = []
            
            # Optimization: Shuffle candidates to avoid processing same ones if many are backed off
            random.shuffle(all_candidates)
            
            for kw in all_candidates[:50]: # Check top 50 shuffled candidates
                # Check SearchRun for this keyword
                stmt = select(SearchRun).where(SearchRun.keyword == kw).order_by(desc(SearchRun.started_at)).limit(1)
                res = await session.execute(stmt)
                last_run = res.scalar_one_or_none()
                
                if last_run:
                    # Adaptive Backoff Logic
                    if not last_run.success or last_run.results_count == 0:
                        # If it failed or found nothing, check if enough time has passed
                        # The more it fails, the longer we should wait? 
                        # For now: if last run found 0, wait at least 4 hours
                        elapsed = (now - last_run.started_at.replace(tzinfo=timezone.utc)).total_seconds()
                        wait_time = 3600 * 4 # 4 hours default backoff
                        
                        if elapsed < wait_time:
                            continue # Skip this keyword for now
                
                # Check KeywordUsage for cooldown (don't spam same keyword too often)
                stmt_usage = select(KeywordUsage).where(KeywordUsage.keyword == kw)
                res_usage = await session.execute(stmt_usage)
                usage = res_usage.scalar_one_or_none()
                
                if usage:
                    elapsed_usage = (now - usage.last_used_at.replace(tzinfo=timezone.utc)).total_seconds()
                    # 1 hour cooldown between same keyword searches
                    if elapsed_usage < 3600:
                        continue
                
                # If it passed all checks, it's a candidate
                # Give weight to evolved keywords
                weight = 1.0
                if kw in evolved_keywords:
                    weight = 2.0 # More likely to be picked
                
                final_keywords.append((kw, weight))

            if not final_keywords:
                logger.debug("All candidate keywords are in backoff/cooldown. Falling back to base round-robin.")
                # Fallback to simple round-robin if everything is filtered out
                if self._current_index >= len(base_keywords):
                    self._current_index = 0
                kw = base_keywords[self._current_index]
                self._current_index += 1
            else:
                # Weighted random choice
                kw = random.choices(
                    [k[0] for k in final_keywords],
                    weights=[k[1] for k in final_keywords],
                    k=1
                )[0]

            # Track usage in DB
            stmt = select(KeywordUsage).where(KeywordUsage.keyword == kw)
            result = await session.execute(stmt)
            usage = result.scalar_one_or_none()

            if usage:
                usage.last_used_at = now
                usage.use_count += 1
            else:
                session.add(KeywordUsage(keyword=kw, last_used_at=now, use_count=1))
            await session.commit()
            
            return kw

    async def preview(self, limit: int = 10) -> List[str]:
        """
        Preview the next N queries that would be generated.
        """
        base = self._get_base_keywords()
        evolved = await keyword_evolution_service.get_evolved_keywords()
        return (evolved[:5] + ["..."] + base[:limit])[:limit]
