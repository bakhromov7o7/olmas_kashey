"""
Robust discovery pipeline for Telegram groups.
Handles noisy AI output, uses fuzzy matching, and implements efficient caching.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union
from loguru import logger
from rapidfuzz import fuzz, process
from sqlalchemy import select

from olmas_kashey.core.settings import settings
from olmas_kashey.db.models import Entity, Membership, MembershipState, Event
from olmas_kashey.db.session import get_db
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.telegram.entity_classifier import EntityClassifier
from olmas_kashey.utils.normalize import normalize_title, normalize_username, normalize_link


class DiscoveryPipeline:
    """
    Implements a robust tiered search strategy:
    1. Cache Lookup (DB)
    2. Resolve by Username (High precision)
    3. Global Search (Multi-query)
    4. Fuzzy Ranking & Selection
    """

    def __init__(self, client: OlmasClient):
        self.client = client
        self.confidence_threshold = 0.6
        self.high_confidence_threshold = 0.85

    async def discover(self, raw_input: str) -> Dict[str, Any]:
        """
        Execute the full discovery pipeline for a single raw input.
        """
        logger.info(f"Starting discovery pipeline for: '{raw_input}'")
        
        # 1. Normalization
        norm_title = normalize_title(raw_input)
        norm_username = normalize_username(raw_input)
        
        attempts = []
        
        # 2. Cache Lookup
        cached_result = await self._lookup_cache(norm_title, norm_username)
        if cached_result:
            logger.info(f"Cache hit for '{raw_input}': {cached_result.title} (@{cached_result.username})")
            return {
                "status": "found",
                "best": self._entity_to_dict(cached_result, score=1.0, confidence="cache"),
                "alternatives": [],
                "debug": {"source": "cache"}
            }

        # 3. Generate Search Variants
        queries = self._generate_search_queries(raw_input, norm_title)
        handles = self._generate_handle_candidates(raw_input, norm_username)
        
        # 4. Tiered Search
        candidates = []
        
        # Step 4.1: Resolve by Username (High Precision)
        for handle in handles:
            try:
                entity = await self.client.get_entity(handle)
                if entity:
                    classified = EntityClassifier.classify(entity)
                    if classified.kind == "group" or classified.kind == "channel": # EntityKind.GROUP
                        candidates.append(classified)
            except Exception as e:
                attempts.append({"type": "resolve", "target": handle, "status": "failed", "error": str(e)})

        # Step 4.2: Global Search (Multi-query)
        for query in queries:
            try:
                results = await self.client.search_public_channels(query, limit=20)
                for raw in results:
                    classified = EntityClassifier.classify(raw)
                    if classified.kind == "group" or classified.kind == "channel":
                        candidates.append(classified)
                attempts.append({"type": "search", "query": query, "status": "success", "results": len(results)})
            except Exception as e:
                attempts.append({"type": "search", "query": query, "status": "failed", "error": str(e)})

        # 5. Fuzzy Ranking
        ranked = self._rank_candidates(norm_title, norm_username, candidates)
        
        if not ranked:
            return {
                "status": "not_found",
                "best": None,
                "alternatives": [],
                "debug": {"attempts": attempts}
            }

        best = ranked[0]
        status = "found" if best["score"] >= self.high_confidence_threshold else "ambiguous"
        
        if status == "found":
            # Cache the result
            await self._cache_entity(best["entity"])

        return {
            "status": status,
            "best": best,
            "alternatives": ranked[1:5],
            "debug": {
                "queries": queries,
                "handles": handles,
                "attempts": attempts
            }
        }

    async def _lookup_cache(self, title: str, username: Optional[str]) -> Optional[Entity]:
        async for session in get_db():
            if username:
                stmt = select(Entity).where(Entity.username == username)
                res = await session.execute(stmt)
                entity = res.scalar_one_or_none()
                if entity: return entity
            
            # Fuzzy title lookup in DB could be complex, for now exact normalized title
            stmt = select(Entity).where(Entity.title == title)
            res = await session.execute(stmt)
            entity = res.scalar_one_or_none()
            if entity: return entity
        return None

    def _generate_search_queries(self, raw: str, norm: str) -> List[str]:
        # Rules: original, normalized, first 2 words
        queries = {raw, norm}
        words = norm.split()
        if len(words) > 1:
            queries.add(" ".join(words[:2]))
        return [q for q in queries if q]

    def _generate_handle_candidates(self, raw: str, norm_user: Optional[str]) -> List[str]:
        candidates = set()
        if norm_user:
            candidates.add(norm_user)
            candidates.add(f"{norm_user}_group")
            candidates.add(f"{norm_user}_chat")
        
        # Try to extract handle from t.me links
        if "t.me/" in raw:
            link_user = normalize_link(raw)
            if link_user: candidates.add(link_user)
            
        return [c for c in candidates if c]

    def _rank_candidates(self, target_title: str, target_user: Optional[str], candidates: List[Any]) -> List[Dict[str, Any]]:
        # Deduplicate candidates by tg_id
        unique_candidates = {}
        for c in candidates:
            unique_candidates[c.tg_id] = c
            
        ranked = []
        for c in unique_candidates.values():
            # Scoring
            title_score = fuzz.token_sort_ratio(target_title, normalize_title(c.title or "")) / 100.0
            
            user_score = 0.0
            if target_user and c.username:
                user_score = fuzz.ratio(target_user, normalize_username(c.username)) / 100.0
            
            # Weighted average
            total_score = (title_score * 0.5) + (user_score * 0.5)
            
            # Boost if username matches exactly (after normalization)
            if target_user and c.username and normalize_username(c.username) == target_user:
                total_score = max(total_score, 0.95)

            if total_score >= self.confidence_threshold:
                ranked.append({
                    "chat_id": c.tg_id,
                    "title": c.title,
                    "username": c.username,
                    "score": round(total_score, 2),
                    "confidence": "high" if total_score > self.high_confidence_threshold else "medium",
                    "entity": c
                })
        
        return sorted(ranked, key=lambda x: x["score"], reverse=True)

    async def _cache_entity(self, classified_entity: Any):
        async for session in get_db():
            stmt = select(Entity).where(Entity.tg_id == int(classified_entity.tg_id))
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            
            now = datetime.now(timezone.utc)
            if not existing:
                entity = Entity(
                    tg_id=int(classified_entity.tg_id),
                    username=classified_entity.username,
                    title=classified_entity.title,
                    kind=classified_entity.kind,
                    discovered_at=now,
                    last_seen_at=now
                )
                session.add(entity)
                await session.flush()
                
                # Default membership
                mem = Membership(
                    entity_id=entity.id,
                    state=MembershipState.NOT_JOINED,
                    last_checked_at=now
                )
                session.add(mem)
                await session.commit()

    def _entity_to_dict(self, entity: Entity, score: float, confidence: str) -> Dict[str, Any]:
        return {
            "chat_id": entity.tg_id,
            "title": entity.title,
            "username": entity.username,
            "score": score,
            "confidence": confidence
        }

