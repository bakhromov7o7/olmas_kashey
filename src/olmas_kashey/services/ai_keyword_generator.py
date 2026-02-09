"""
AI-powered keyword generator using GROQ API.
Generates smart search keywords for Telegram group discovery with fuzzy/partial matching.
"""
import asyncio
from typing import List, Optional
from loguru import logger

from groq import Groq

from olmas_kashey.core.settings import settings


class AIKeywordGenerator:
    """
    Uses GROQ LLM to generate intelligent search keywords for Telegram groups.
    Supports fuzzy matching by generating variations of keywords.
    Understands Telegram username rules.
    """
    
    SYSTEM_PROMPT = """Sen Telegram guruhlarini qidirish uchun keyword generator'san. 
Foydalanuvchi bergan so'z bo'yicha Telegram'da guruh qidirish uchun keyword'larni yaratishing kerak.

🔴 TELEGRAM USERNAME QOIDALARI:
1. Username'da BO'SH JOY YO'Q - hammasi yopishtirib yoziladi
2. Faqat harflar (a-z), raqamlar (0-9) va pastki chiziq (_) ishlatiladi
3. Kamida 5 ta belgi bo'lishi kerak
4. Kirill (rus) harflari ISHLATILMAYDI - faqat lotin harflari

📝 QOIDALAR:
1. Keyword'larni username formatida yoz - BO'SH JOYSIZ, yopishtirib
2. Variatsiyalarni qo'sh: -lik, -lar, -soy, -chilar, _group, _chat
3. Pastki chiziq (_) bilan ham variatsiyalar: koson_group, koson_chat
4. Faqat keyword'larni vergul bilan ajratib yoz

✅ TO'G'RI MISOL - "Koson" uchun:
koson, kosonsoy, kosonlik, kosonliklar, kosonchilar, koson_group, koson_chat, kosonsoylik, kosonlar, koson_guruh, kosonchat, kosongroup

❌ NOTO'G'RI (bo'sh joy bor, rus harflari):
koson group, koson chat, кошон, кошонсой

✅ TO'G'RI MISOL - "Tashkent" uchun:
tashkent, toshkent, tashkentlik, tashkentliklar, tashkent_group, toshkent_chat, tashkentchilar, tashkent_uz"""

    def __init__(self):
        self.client = Groq(api_key=settings.groq.api_key)
        self.model = settings.groq.model
        self.max_tokens = settings.groq.max_tokens
    
    def generate_keywords(self, topic: str = "education", count: int = 20) -> List[str]:
        """
        Generate keywords with fuzzy variations for a specific topic.
        
        Args:
            topic: The topic/word to generate variations for
            count: Number of keywords to generate
            
        Returns:
            List of generated keywords including fuzzy variations
        """
        try:
            user_prompt = f"""'{topic}' so'zi/mavzusi uchun Telegram guruhlarini qidirish uchun {count} ta keyword yarat.

MUHIM: 
- '{topic}' so'zining barcha mumkin bo'lgan variatsiyalarini yarat
- Suffikslar bilan: {topic}lik, {topic}lar, {topic}chilar, {topic}soy, {topic}ning
- Boshqa tillarida ham yoz (rus, ingliz)
- group, chat, guruh, community so'zlari bilan kombinatsiyalar

Faqat keyword'larni vergul bilan ajrat, boshqa hech narsa yozma."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=0.8,
            )
            
            content = response.choices[0].message.content
            if not content:
                logger.warning("Empty response from GROQ API")
                return self._generate_fallback_variations(topic)
            
            # Parse comma-separated keywords
            keywords = [kw.strip().lower() for kw in content.split(",") if kw.strip()]
            
            # Always add base variations manually to ensure they're included
            base_variations = self._generate_fallback_variations(topic)
            all_keywords = list(set(keywords + base_variations))
            
            logger.info(f"Generated {len(all_keywords)} keywords for topic '{topic}'")
            return all_keywords
            
        except Exception as e:
            logger.error(f"Error generating keywords: {e}")
            return self._generate_fallback_variations(topic)
    
    def _generate_fallback_variations(self, word: str) -> List[str]:
        """
        Generate basic variations of a word without AI (fallback).
        Generates Telegram username-compatible keywords (no spaces, only a-z, 0-9, _).
        """
        import re
        
        # Clean word - remove non-alphanumeric except underscore
        word = word.lower().strip()
        word = re.sub(r'[^a-z0-9_]', '', word)
        
        if not word:
            return []
        
        # Username-compatible suffixes (yopishtirib)
        suffixes = ["", "lik", "liklar", "lar", "chilar", "soy", "ning", "uz", "group", "chat", "guruh"]
        
        # Username-compatible prefixes (with underscore or attached)
        underscore_prefixes = ["", "guruh_", "chat_", "group_", "uz_"]
        attached_prefixes = ["", "guruh", "chat", "group"]
        
        variations = set()
        
        # Base word
        variations.add(word)
        
        # With suffixes (attached)
        for suffix in suffixes:
            variations.add(f"{word}{suffix}")
        
        # With underscore suffixes
        for suffix in ["_group", "_chat", "_guruh", "_uz", "_official"]:
            variations.add(f"{word}{suffix}")
        
        # With underscore prefixes
        for prefix in underscore_prefixes:
            if prefix:
                variations.add(f"{prefix}{word}")
        
        # Attached prefix + word
        for prefix in attached_prefixes:
            if prefix:
                variations.add(f"{prefix}{word}")
        
        # Common combinations
        variations.add(f"{word}lar")
        variations.add(f"{word}liklar") 
        variations.add(f"{word}chilar")
        variations.add(f"{word}_official")
        variations.add(f"official_{word}")
        
        # Filter out too short (Telegram needs minimum 5 chars for username)
        # But for search, shorter is OK
        return list(variations)
    
    def generate_variations(self, base_keywords: List[str], count: int = 10) -> List[str]:
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

            response = self.client.chat.completions.create(
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
    
    def expand_single_keyword(self, keyword: str) -> List[str]:
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

            response = self.client.chat.completions.create(
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
    
    def suggest_topics(self) -> List[str]:
        """
        Suggest related topics for Uzbekistan education/study context.
        """
        try:
            user_prompt = """O'zbekistonlik talabalar uchun qiziq bo'lishi mumkin bo'lgan 15 ta mavzu taklif qil.
Ta'lim, xorijda o'qish, tillarni o'rganish, kasblar, IT va boshqa sohalar bo'lishi mumkin.

Faqat mavzu nomlarini vergul bilan ajratib yoz."""

            response = self.client.chat.completions.create(
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

