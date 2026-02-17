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
        self._keyword_cache: Optional[List[str]] = None
        self._current_index: int = 0  # Round-robin index

    def _get_keywords(self) -> List[str]:
        # Always generate fresh to respect settings.discovery.allowed_topics changes
        return list(self.generator.generate())

    async def get_next_query(self) -> Optional[str]:
        """
        Returns the next keyword using round-robin rotation.
        Each call advances to the next keyword in the list.
        """
        keywords = self._get_keywords()
        if not keywords:
            return None

        now = datetime.now(timezone.utc)
        
        # Wrap around if index exceeds list length
        if self._current_index >= len(keywords):
            self._current_index = 0
        
        kw = keywords[self._current_index]
        self._current_index += 1
        
        # Track usage in DB (for stats, not for limiting)
        async for session in get_db():
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
        keywords = self._get_keywords()
        available = []
        
        idx = self._current_index
        for _ in range(min(limit, len(keywords))):
            if idx >= len(keywords):
                idx = 0
            available.append(f"{keywords[idx]} (Next)")
            idx += 1
        
        return available
