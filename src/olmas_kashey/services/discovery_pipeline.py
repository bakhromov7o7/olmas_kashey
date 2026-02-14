"""
Robust discovery pipeline for Telegram groups.
Handles noisy AI output, uses fuzzy matching, and implements efficient caching.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from rapidfuzz import fuzz
from sqlalchemy import select

from olmas_kashey.core.cache import TTLCache
from olmas_kashey.core.settings import settings
from olmas_kashey.core.types import EntityKind
from olmas_kashey.db.models import Entity, Membership, MembershipState
from olmas_kashey.db.session import get_db
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.telegram.entity_classifier import EntityClassifier, ClassifiedEntity
from olmas_kashey.utils.normalize import normalize_title, normalize_username, normalize_link
from olmas_kashey.services.ai_keyword_generator import ai_keyword_generator
from olmas_kashey.services.control_bot import TopicsChangedInterruption


@dataclass(frozen=True)
class Candidate:
    entity: ClassifiedEntity
    about: Optional[str] = None


class DiscoveryPipeline:
    def __init__(self, client: OlmasClient, bot: Optional[Any] = None):
        self.client = client
        self.bot = bot
        self.min_confidence = settings.discovery.min_confidence
        self.high_confidence_threshold = settings.discovery.high_confidence
        self.max_query_variants = settings.discovery.max_query_variants
        self.max_results_per_query = settings.discovery.max_results_per_query
        self.max_ranked_candidates = settings.discovery.max_ranked_candidates
        self.allow_channels = settings.discovery.allow_channels
        self._entity_cache = TTLCache[ClassifiedEntity](settings.discovery.entity_cache_ttl_seconds)
        self._stopwords = {
            "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on", "at",
            "from", "group", "chat", "channel", "community", "telegram", "tg", "guruh", "kanal"
        }
        self._query_suffixes = [
            "group", "chat", "community", "club", "students", "study", "prep", "academy", "course"
        ]
        self._username_suffixes = [
            "uz", "study", "prep", "group", "chat", "students", "club", "community", "academy", "course"
        ]
        self._synonym_map = {
            "ielts": [
                "ielts preparation", "ielts prep", "band score", "mock test", "speaking club",
                "writing task 2", "listening practice", "reading practice"
            ],
            "toefl": ["toefl prep", "toefl ibt", "toefl speaking", "toefl writing"],
            "english": ["english speaking", "english practice", "ingliz tili", "inglizcha"],
            "cefr": ["cefr prep", "cefr speaking", "cefr writing"],
        }

    async def search_candidates(self, raw_input: str, language: Optional[str] = None, region: Optional[str] = None) -> List[Candidate]:
        queries, _ = await self.build_query_plan_ai(raw_input)
        attempts: List[Dict[str, Any]] = []
        return await self._search_candidates(queries, attempts)

    async def discover(self, raw_input: str, language: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
        logger.info(f"Starting discovery pipeline for: '{raw_input}'")

        norm_title = normalize_title(raw_input)
        norm_username = normalize_username(raw_input)

        cached_result = await self._lookup_cache(norm_title, norm_username)
        if cached_result:
            logger.info(f"Cache hit for '{raw_input}': {cached_result.title} (@{cached_result.username})")
            return {
                "status": "found",
                "best": self._entity_to_dict(cached_result, score=1.0, confidence="cache"),
                "alternatives": [],
                "debug": {"source": "cache"}
            }

        # Use AI for query planning
        queries, keyword_tokens = await self.build_query_plan_ai(raw_input)
        attempts = []

        explicit_handle = self._extract_explicit_handle(raw_input)
        if explicit_handle:
            try:
                entity = await self.client.get_entity(explicit_handle)
                if entity:
                    classified = EntityClassifier.classify(entity)
                    if self._is_allowed_kind(classified.kind):
                        total_score = 0.95
                        await self._cache_entity(classified)
                        return {
                            "status": "found",
                            "best": self._entity_to_dict(classified, score=total_score, confidence="high"),
                            "alternatives": [],
                            "debug": {"source": "direct_resolve"}
                        }
            except Exception as e:
                attempts.append({"type": "resolve", "target": explicit_handle, "status": "failed", "error": str(e)})

        candidates, used_queries = await self._search_candidates_with_early_stop(queries, keyword_tokens, attempts)
        
        # Fallback: if no candidates found, try rule-based expansion
        if not candidates:
            logger.info(f"AI search returned nothing for '{raw_input}'. Trying rule-based fallback...")
            queries_fb, kw_tokens_fb = self.build_query_plan(raw_input, language, region)
            # Filter queries already tried
            queries_fb = [q for q in queries_fb if q not in used_queries]
            if queries_fb:
                candidates_fb, used_queries_fb = await self._search_candidates_with_early_stop(queries_fb, kw_tokens_fb, attempts)
                candidates.extend(candidates_fb)
                used_queries.extend(used_queries_fb)
                keyword_tokens = list(set(keyword_tokens + kw_tokens_fb))

        ranked = self._rank_candidates(used_queries, keyword_tokens, candidates)

        if not ranked:
            return {
                "status": "not_found",
                "best": None,
                "alternatives": [],
                "debug": {"attempts": attempts, "queries": queries}
            }

        best = ranked[0]
        if best["score"] >= self.high_confidence_threshold:
            await self._cache_entity(best["entity"])
            return {
                "status": "found",
                "best": best,
                "alternatives": ranked[1:5],
                "debug": {"queries": queries, "attempts": attempts}
            }

        return {
            "status": "not_found",
            "best": None,
            "alternatives": ranked[:5],
            "debug": {"queries": queries, "attempts": attempts}
        }

    async def build_query_plan_ai(self, raw_input: str, count: int = 10) -> Tuple[List[str], List[str]]:
        """
        Build a query plan using AI-generated structured output.
        """
        logger.info(f"Generating AI query plan for: '{raw_input}'")
        ai_data = await ai_keyword_generator.generate_keywords(raw_input, count=count)
        
        # Combine all parts into a unique list of queries
        # Order: 1. Usernames (high priority) 2. Variations 3. Keywords
        queries = []
        queries.extend(ai_data.get("usernames", []))
        queries.extend(ai_data.get("variations", []))
        queries.extend(ai_data.get("keywords", []))
        
        # Add original input as fallback
        queries.append(raw_input)
        
        # Deduplicate while preserving priority
        unique_queries = []
        seen = set()
        for q in queries:
            q_clean = q.strip().lower()
            if q_clean and q_clean not in seen:
                unique_queries.append(q_clean)
                seen.add(q_clean)
        
        # Keyword tokens for ranking overlap
        tokens = set()
        for q in unique_queries:
            tokens.update(self._tokenize(q))
            
        return unique_queries[:self.max_query_variants], list(tokens)

    def build_query_plan(self, raw_input: str, language: Optional[str] = None, region: Optional[str] = None) -> Tuple[List[str], List[str]]:
        """
        Legacy rule-based query expansion (used as fallback).
        """
        raw = (raw_input or "").strip()
        norm = self._normalize_query(raw)
        tokens = [t for t in self._tokenize(norm) if t not in self._stopwords]
        base = " ".join(tokens)
        slug = "_".join(tokens)
        tight = "".join(tokens)

        queries: List[str] = []
        for q in [raw, norm, base, slug, tight]:
            if q:
                queries.append(q)

        # 1. Add tokens and username variants EARLY (high priority)
        if tokens:
            queries.extend(tokens[:3])
        queries.extend(self._username_variants(tokens, language, region))

        # 2. Add synonyms
        synonyms = self._expand_with_synonyms(tokens)
        queries.extend(synonyms)

        # 3. Add base token combinations
        if len(tokens) >= 2:
            queries.extend([
                " ".join(tokens[:2]),
                "_".join(tokens[:2]),
                "".join(tokens[:2]),
                " ".join(tokens[-2:]),
                "_".join(tokens[-2:]),
                "".join(tokens[-2:]),
            ])

        # 4. Add suffixes (lower priority, likely to be truncated)
        if base:
            for suffix in self._query_suffixes:
                queries.append(f"{base} {suffix}")
        if slug:
            for suffix in self._query_suffixes:
                queries.append(f"{slug}_{suffix}")
        if tight:
            for suffix in self._query_suffixes:
                queries.append(f"{tight}{suffix}")

        if language:
            lang = self._normalize_query(language)
            if lang:
                queries.append(f"{base} {lang}" if base else lang)
                queries.append(f"{slug}_{lang}" if slug else lang)
        if region:
            reg = self._normalize_query(region)
            if reg:
                queries.append(f"{base} {reg}" if base else reg)
                queries.append(f"{slug}_{reg}" if slug else reg)

        queries = self._unique_preserve_order(queries)
        queries = queries[:self.max_query_variants]

        keyword_tokens = set(tokens)
        for phrase in synonyms:
            keyword_tokens.update(self._tokenize(self._normalize_query(phrase)))
        if language:
            keyword_tokens.update(self._tokenize(self._normalize_query(language)))
        if region:
            keyword_tokens.update(self._tokenize(self._normalize_query(region)))

        return queries, list(keyword_tokens)

    async def _search_candidates(self, queries: List[str], attempts: List[Dict[str, Any]]) -> List[Candidate]:
        candidates: List[Candidate] = []
        seen_ids = set()
        for query in queries:
            if self.bot:
                await self.bot.wait_if_paused()
                if self.bot.topics_updated:
                    raise TopicsChangedInterruption()
            try:
                results = await self.client.search_public_channels(query, limit=self.max_results_per_query)
                for raw in results:
                    if getattr(raw, "scam", False) or getattr(raw, "fake", False):
                        continue
                    classified = self._classify_cached(raw)
                    if not self._is_allowed_kind(classified.kind):
                        continue
                    tg_id = int(classified.tg_id)
                    if tg_id in seen_ids:
                        continue
                    candidates.append(Candidate(entity=classified, about=getattr(raw, "about", None)))
                    seen_ids.add(tg_id)
                attempts.append({"type": "search", "query": query, "status": "success", "results": len(results)})
            except Exception as e:
                attempts.append({"type": "search", "query": query, "status": "failed", "error": str(e)})
        return candidates

    async def _search_candidates_with_early_stop(
        self,
        queries: List[str],
        keyword_tokens: List[str],
        attempts: List[Dict[str, Any]]
    ) -> Tuple[List[Candidate], List[str]]:
        candidates: List[Candidate] = []
        seen_ids = set()
        used_queries: List[str] = []
        for query in queries:
            if self.bot:
                await self.bot.wait_if_paused()
                if self.bot.topics_updated:
                    raise TopicsChangedInterruption()
            try:
                results = await self.client.search_public_channels(query, limit=self.max_results_per_query)
                for raw in results:
                    if getattr(raw, "scam", False) or getattr(raw, "fake", False):
                        continue
                    classified = self._classify_cached(raw)
                    if not self._is_allowed_kind(classified.kind):
                        continue
                    tg_id = int(classified.tg_id)
                    if tg_id in seen_ids:
                        continue
                    candidates.append(Candidate(entity=classified, about=getattr(raw, "about", None)))
                    seen_ids.add(tg_id)
                attempts.append({"type": "search", "query": query, "status": "success", "results": len(results)})
            except Exception as e:
                attempts.append({"type": "search", "query": query, "status": "failed", "error": str(e)})
            used_queries.append(query)
            ranked = self._rank_candidates(used_queries, keyword_tokens, candidates)
            if ranked and ranked[0]["score"] >= self.high_confidence_threshold:
                return candidates, used_queries
        return candidates, used_queries

    def _rank_candidates(self, queries: List[str], keyword_tokens: List[str], candidates: List[Candidate]) -> List[Dict[str, Any]]:
        query_norms = [self._normalize_query(q) for q in queries if q]
        query_norms = [q for q in query_norms if q]
        query_token_sets = [set(self._tokenize(q)) for q in query_norms]
        keyword_token_set = set(keyword_tokens)

        ranked: List[Dict[str, Any]] = []
        for c in candidates:
            entity = c.entity
            title = normalize_title(entity.title or "")
            username = normalize_username(entity.username or "") or ""
            desc = normalize_title(c.about or "")
            title_tokens = set(self._tokenize(title))
            desc_score = self._keyword_overlap(desc, keyword_token_set)

            best_score = 0.0
            best_query = ""
            for qn, qt in zip(query_norms, query_token_sets):
                # 1. Partial Username Search Optimization
                # Exact or partial match in username is HIGH priority
                user_match_score = 0.0
                qn_tight = qn.replace(" ", "")
                if username:
                    if qn_tight == username:
                        user_match_score = 1.0
                    elif qn_tight in username:
                        user_match_score = 0.8
                    else:
                        user_match_score = fuzz.ratio(qn_tight, username) / 100.0

                # 2. Title matching
                title_score = fuzz.token_set_ratio(qn, title) / 100.0 if title else 0.0
                
                # 3. Token overlap
                token_overlap = self._jaccard(qt, title_tokens)
                
                # Weighted Total: Prioritize Username (0.6) over Title (0.3)
                total = (user_match_score * 0.6) + (title_score * 0.2) + (token_overlap * 0.1) + (desc_score * 0.1)
                
                # Bonus for keyword in username
                if username and keyword_token_set and any(k in username for k in keyword_token_set):
                    total = min(1.0, total + 0.1)
                
                if total > best_score:
                    best_score = total
                    best_query = qn

            confidence = "low"
            if best_score >= self.high_confidence_threshold:
                confidence = "high"
            elif best_score >= self.min_confidence:
                confidence = "medium"

            ranked.append({
                "chat_id": int(entity.tg_id),
                "title": entity.title,
                "username": entity.username,
                "score": round(best_score, 2),
                "confidence": confidence,
                "best_query": best_query,
                "entity": entity
            })

        ranked.sort(key=lambda x: (x["score"], x["username"] is not None), reverse=True)
        return ranked[:self.max_ranked_candidates]

    async def _lookup_cache(self, title: str, username: Optional[str]) -> Optional[Entity]:
        async for session in get_db():
            if username:
                stmt = select(Entity).where(Entity.username == username)
                res = await session.execute(stmt)
                entity = res.scalar_one_or_none()
                if entity:
                    return entity

            stmt = select(Entity).where(Entity.title == title)
            res = await session.execute(stmt)
            entity = res.scalar_one_or_none()
            if entity:
                return entity
        return None

    def _classify_cached(self, raw: Any) -> ClassifiedEntity:
        raw_id = getattr(raw, "id", None)
        if raw_id is not None:
            cached = self._entity_cache.get(str(raw_id))
            if cached is not None:
                return cached
        classified = EntityClassifier.classify(raw)
        self._entity_cache.set(str(int(classified.tg_id)), classified)
        return classified

    def _is_allowed_kind(self, kind: EntityKind) -> bool:
        if kind == EntityKind.GROUP:
            return True
        if self.allow_channels and kind == EntityKind.CHANNEL:
            return True
        return False

    def _normalize_query(self, text: str) -> str:
        return normalize_title(text.replace("_", " ").replace("-", " "))

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _jaccard(self, a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _keyword_overlap(self, desc: str, keyword_tokens: set) -> float:
        if not desc or not keyword_tokens:
            return 0.0
        desc_tokens = set(self._tokenize(desc))
        overlap = len(desc_tokens & keyword_tokens)
        return overlap / max(1, len(keyword_tokens))

    def _unique_preserve_order(self, items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            item = (item or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _expand_with_synonyms(self, tokens: List[str]) -> List[str]:
        out: List[str] = []
        for t in tokens:
            out.extend(self._synonym_map.get(t, []))
        return out

    def _username_variants(self, tokens: List[str], language: Optional[str], region: Optional[str]) -> List[str]:
        root = tokens[0] if tokens else ""
        slug = "_".join(tokens)
        tight = "".join(tokens)
        seeds = [root, slug, tight]
        variants: List[str] = []
        for seed in seeds:
            if not seed:
                continue
            for suffix in self._username_suffixes:
                variants.append(f"{seed}_{suffix}")
                variants.append(f"{seed}{suffix}")
                variants.append(f"{seed}-{suffix}")
        if language:
            lang = self._normalize_query(language)
            if lang:
                for seed in seeds:
                    if seed:
                        variants.append(f"{seed}_{lang}")
                        variants.append(f"{lang}_{seed}")
        if region:
            reg = self._normalize_query(region)
            if reg:
                for seed in seeds:
                    if seed:
                        variants.append(f"{seed}_{reg}")
                        variants.append(f"{reg}_{seed}")
        return variants

    def _extract_explicit_handle(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        if "t.me/" in raw or "telegram.me/" in raw:
            return normalize_link(raw)
        raw_strip = raw.strip()
        if raw_strip.startswith("@"):
            return normalize_username(raw_strip)
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw_strip) and ("_" in raw_strip or any(ch.isdigit() for ch in raw_strip)):
            return normalize_username(raw_strip)
        return None

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
