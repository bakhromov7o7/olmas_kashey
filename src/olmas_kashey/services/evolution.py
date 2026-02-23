import asyncio
from typing import List, Set, Dict
from loguru import logger

from olmas_kashey.services.ai_keyword_generator import ai_keyword_generator
from olmas_kashey.core.settings import settings
from olmas_kashey.db.models import Entity

class KeywordEvolutionService:
    """
    Evolves the search space by generating new keywords based on recently discovered groups.
    """
    def __init__(self):
        self._evolved_pool: Set[str] = set()
        self._lock = asyncio.Lock()

    async def evolve_from_entities(self, entities: List[Entity]) -> List[str]:
        """
        Takes a list of entities (groups) and uses AI to generate related search terms.
        """
        if not entities:
            return []

        # Extract context from entities
        context_chunks = []
        for e in entities:
            context = f"{e.title or ''} (@{e.username or 'private'})"
            context_chunks.append(context)
        
        context_str = " | ".join(context_chunks[:5]) # Limit context to avoid token bloat
        logger.info(f"Evolving search keywords from context: {context_str}")

        try:
            # Use the existing variations generator but with group-specific context
            # We can use expand_single_keyword or generate_variations
            # Let's use a specialized prompt via AIKeywordGenerator expansion logic if possible, 
            # or just call it with the titles.
            
            new_keywords = []
            for e in entities[:3]: # Only use top 3 for evolution to keep it focused
                if e.title:
                    variations = await ai_keyword_generator.expand_single_keyword(e.title)
                    new_keywords.extend(variations)
            
            # Filter and deduplicate
            unique_new = [k.strip().lower() for k in new_keywords if k.strip()]
            
            async with self._lock:
                added = []
                for k in unique_new:
                    if k not in self._evolved_pool:
                        self._evolved_pool.add(k)
                        added.append(k)
                
                logger.info(f"Evolved {len(added)} new keywords from discovery results.")
                return added

        except Exception as e:
            logger.error(f"Keyword evolution failed: {e}")
            return []

    async def get_evolved_keywords(self) -> List[str]:
        """Returns all evolved keywords in the pool."""
        async with self._lock:
            return list(self._evolved_pool)

    async def clear_pool(self):
        """Clears the evolved keywords pool."""
        async with self._lock:
            self._evolved_pool.clear()

# Singleton
keyword_evolution_service = KeywordEvolutionService()
