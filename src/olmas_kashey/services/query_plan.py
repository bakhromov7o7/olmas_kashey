import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Optional
from loguru import logger
from sqlalchemy import select, update

from olmas_kashey.core.settings import settings
from olmas_kashey.db.models import KeywordUsage
from olmas_kashey.db.session import get_db
from olmas_kashey.services.keyword_generator import KeywordGenerator


class QueryPlanner:
    def __init__(self, seed: int = 42) -> None:
        self.generator = KeywordGenerator(seed=seed)
        self.cooldown = timedelta(days=1)  # Per-keyword cooldown
        # For demonstration simplicity, standard generator is infinite but logic needs state.
        # We'll regenerate the list each time but skip used ones.
        # In a real rigorous system, we might want a persistent queue.
        # Here we rely on the deterministic shuffle + DB persistence to "resume".
        self._keyword_cache: Optional[List[str]] = None

    def _get_keywords(self) -> List[str]:
        # Always generate fresh to respect settings.discovery.allowed_topics changes
        return list(self.generator.generate())

    async def get_next_query(self) -> Optional[str]:
        """
        Returns the next available keyword that satisfies cooldowns and global rate limits.
        Returns None if no keyword is available or global limit reached.
        """
        keywords = self._get_keywords()
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        
        # Global Rate Limit Check
        # We can configure this in settings, for now hardcoded or passed in __init__
        # "global max searches per hour" -> Example: 20
        MAX_SEARCHES_PER_HOUR = 20 
        
        async for session in get_db():
            # Check global usage in last hour
            stmt = select(KeywordUsage).where(KeywordUsage.last_used_at > one_hour_ago)
            result = await session.execute(stmt)
            recent_usage_count = len(result.scalars().all()) # Simple count
            
            if recent_usage_count >= MAX_SEARCHES_PER_HOUR:
                logger.warning("Global search rate limit reached.")
                return None

            for kw in keywords:
                # Check DB for last usage
                stmt = select(KeywordUsage).where(KeywordUsage.keyword == kw)
                result = await session.execute(stmt)
                usage = result.scalar_one_or_none()

                if usage:
                    last_used = usage.last_used_at
                    if last_used.tzinfo is None:
                        last_used = last_used.replace(tzinfo=timezone.utc)
                        
                    if now - last_used < self.cooldown:
                        continue # Cooling down
                    
                    # Ready to use again
                    usage.last_used_at = now
                    usage.use_count += 1
                    await session.commit()
                    return kw
                else:
                    # Never used
                    new_usage = KeywordUsage(keyword=kw, last_used_at=now, use_count=1)
                    session.add(new_usage)
                    await session.commit()
                    return kw
        
        return None

    async def preview(self, limit: int = 10) -> List[str]:
        """
        Preview the next N queries that would be generated, checking cooldowns but not marking usage.
        """
        keywords = self._get_keywords()
        now = datetime.now(timezone.utc)
        available = []
        
        async for session in get_db():
            for kw in keywords:
                if len(available) >= limit:
                    break
                
                stmt = select(KeywordUsage).where(KeywordUsage.keyword == kw)
                result = await session.execute(stmt)
                usage = result.scalar_one_or_none()

                if usage:
                    if now - usage.last_used_at >= self.cooldown:
                        available.append(f"{kw} (Ready)")
                    else:
                        # Skip or show as cooldowned? The prompt says "prints next N planned queries". 
                        # Usually implies the ones that WOULD run.
                        # So skip cooldowns.
                        pass
                else:
                    available.append(f"{kw} (New)")
        
        return available
