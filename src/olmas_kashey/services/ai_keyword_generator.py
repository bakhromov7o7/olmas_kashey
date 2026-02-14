"""
AI-powered keyword generator using GROQ API.
Generates smart search keywords for Telegram group discovery with fuzzy/partial matching.
"""
import asyncio
from typing import List, Optional, Dict
from loguru import logger

from groq import AsyncGroq

from olmas_kashey.core.settings import settings


class AIKeywordGenerator:
    """
    Uses GROQ LLM to generate intelligent search keywords for Telegram groups.
    Supports fuzzy matching by generating variations of keywords.
    Understands Telegram username rules.
    """
    
    SYSTEM_PROMPT = """You are a Telegram search query expert. 
Your goal is to generate search terms to find relevant groups/channels for a given topic.

🔴 TELEGRAM USERNAME RULES:
1. NO SPACES - everything joined.
2. Only lowercase letters (a-z), numbers (0-9), and underscore (_).
3. At least 5 characters for usernames.
4. NO non-Latin characters.

🔴 OUTPUT FORMAT:
You MUST return a JSON object with:
- "keywords": list of natural language keywords (spaces allowed) for general search.
- "usernames": list of Telegram-compatible usernames (no spaces, only a-z, 0-9, _).
- "variations": list of variations including underscores, prefixes, and suffixes.

Example for 'IELTS':
{
  "keywords": ["ielts preparation", "ielts speaking club", "mock exam"],
  "usernames": ["ielts_prep", "ielts_speaking", "ieltsuz", "ielts_2026"],
  "variations": ["ielts_study", "ielts_group", "ielts_bot", "ielts_chat"]
}
"""

    def __init__(self):
        self.client = AsyncGroq(api_key=settings.groq.api_key)
        self.model = settings.groq.model
        self.max_tokens = settings.groq.max_tokens
    
    async def generate_keywords(self, topic: str = "education", count: int = 20) -> Dict[str, List[str]]:
        """
        Generate structured keywords and usernames for a specific topic.
        """
        try:
            user_prompt = f"Generate {count} search terms for topic: '{topic}'. Use the required JSON format."

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            import json
            content = response.choices[0].message.content
            if not content:
                logger.warning("Empty response from GROQ API")
                return self._fallback_structured(topic)
            
            data = json.loads(content)
            # Ensure all keys exist and are lowercase
            result = {
                "keywords": [str(k).lower() for k in data.get("keywords", [])],
                "usernames": [str(u).lower().replace(" ", "") for u in data.get("usernames", [])],
                "variations": [str(v).lower() for v in data.get("variations", [])]
            }
            
            logger.info(f"Generated structured keywords for topic '{topic}'")
            return result
            
        except Exception as e:
            logger.error(f"Error generating structured keywords: {e}")
            return self._fallback_structured(topic)
    
    def _fallback_structured(self, topic: str) -> Dict[str, List[str]]:
        """
        Fallback structured output.
        """
        import re
        clean_topic = re.sub(r'[^a-z0-9_]', '', topic.lower())
        return {
            "keywords": [topic.lower()],
            "usernames": [clean_topic, f"{clean_topic}_group", f"{clean_topic}_chat"],
            "variations": [f"{clean_topic}_uz", f"{clean_topic}_official"]
        }
    
    async def generate_variations(self, base_keywords: List[str], count: int = 10) -> List[str]:
        """
        Generate fuzzy variations of existing keywords.
        """
        try:
            keywords_str = ", ".join(base_keywords[:10])
            
            user_prompt = f"""Quyidagi keyword'lar asosida {count} ta yangi FUZZY variatsiya yarat:
{keywords_str}

Har bir keyword uchun:
- Boshqa suffikslar qo'sh (-lik, -lar, -chilar, -soy)
- Rus tilida yoz
- "group", "chat", "guruh" bilan kombinatsiyalar

Faqat keyword'larni vergul bilan ajrat."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=0.9,
            )
            
            content = response.choices[0].message.content
            if not content:
                return []
            
            variations = [kw.strip().lower() for kw in content.split(",") if kw.strip()]
            logger.info(f"Generated {len(variations)} keyword variations")
            return variations
            
        except Exception as e:
            logger.error(f"Error generating variations: {e}")
            return []
    
    async def expand_single_keyword(self, keyword: str) -> List[str]:
        """
        Expand a single keyword into multiple fuzzy search terms.
        This is useful for immediate searching.
        """
        try:
            user_prompt = f"""'{keyword}' so'zini Telegram'da qidirish uchun 15 xil variatsiyaga aylantir.

O'ylangan variatsiyalar:
- {keyword}lik, {keyword}lar, {keyword}chilar
- rus tilida
- group, chat, guruh bilan

Faqat variatsiyalarni vergul bilan ajrat."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=512,
                temperature=0.7,
            )
            
            content = response.choices[0].message.content
            if not content:
                return self._generate_fallback_variations(keyword)
            
            variations = [kw.strip().lower() for kw in content.split(",") if kw.strip()]
            # Always include fallback variations
            all_variations = list(set(variations + self._generate_fallback_variations(keyword)))
            
            logger.info(f"Expanded '{keyword}' into {len(all_variations)} variations")
            return all_variations
            
        except Exception as e:
            logger.error(f"Error expanding keyword: {e}")
            return self._generate_fallback_variations(keyword)
    
    async def suggest_topics(self) -> List[str]:
        """
        Suggest related topics for Uzbekistan education/study context.
        """
        try:
            user_prompt = """O'zbekistonlik talabalar uchun qiziq bo'lishi mumkin bo'lgan 15 ta mavzu taklif qil.
Ta'lim, xorijda o'qish, tillarni o'rganish, kasblar, IT va boshqa sohalar bo'lishi mumkin.

Faqat mavzu nomlarini vergul bilan ajratib yoz."""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=512,
                temperature=0.7,
            )
            
            content = response.choices[0].message.content
            if not content:
                return []
            
            topics = [t.strip() for t in content.split(",") if t.strip()]
            logger.info(f"Suggested {len(topics)} topics")
            return topics
            
        except Exception as e:
            logger.error(f"Error suggesting topics: {e}")
            return []


# Singleton instance
ai_keyword_generator = AIKeywordGenerator()

