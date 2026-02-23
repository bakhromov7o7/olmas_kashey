"""
AI-powered keyword generator using GROQ API.
Generates smart search keywords for Telegram group discovery with fuzzy/partial matching.
"""
import asyncio
from typing import List, Optional, Dict
from loguru import logger

import google.generativeai as genai
from groq import AsyncGroq

from olmas_kashey.core.settings import settings


class AIKeywordGenerator:
    """
    Uses GROQ LLM to generate intelligent search keywords for Telegram groups.
    Supports fuzzy matching by generating variations of keywords.
    Understands Telegram username rules.
    """
    
    SYSTEM_PROMPT = """Siz Telegram tarmoqlarida guruh/kanal qidirish bo'yicha eng zo'r ekspertsiz. 
Maqsadingiz: Bitta mavzu bo'yicha imkon qadar ko'p va hayotiy qidiruv kalit so'zlarini (keywords) o'ylab topish. Odamlar telegramda guruh nomini qanday atashsa shunday yozing.

🔴 TELEGRAM QIDIRUV QOIDALARI:
1. MAXIMAL KO'P GURUH TOPISH KERAK. Shuning uchun kalit so'zlarga albatta qo'shimchalar qo'shing.
2. Suffixlar: 'chat', 'guruh', 'group', 'uz', 'uzb', 'toshkent', 'discussion', 'obsujdenie', 'chatlar', 'bazasi', 'reklama', 'elonlar', 'bozori'.
3. Kirill va Lotin alifbosini aralashtirib yozing (masalan, 'ayollar gruppa', 'аёллар чат', 'savdo sotiq', 'савдо сотик').
4. Ingliz, O'zbek va Rus tillarini aralashtiring. Slang so'zlarni ham ishlating (masalan, 'ielts prep', 'ielts mock', 'study uz').
5. Juda qisqa va juda uzun variatsiyalarni ham qo'shing.

🔴 OUTPUT FORMAT:
You MUST return a JSON object with:
- "keywords": list of 30+ natural language keywords (spaces allowed) for general search.
- "usernames": list of 30+ Telegram-compatible usernames (no spaces, only a-z, 0-9, _).
- "variations": list of 30+ intense variations using underscores, prefixes ('uz_', 'chat_'), suffixes ('_chat', '_guruh', '_toshkent').

Example for 'biznes':
{
  "keywords": ["biznes chat", "biznes guruh uz", "tadbirkorlar", "biznes obsujdenie", "biznesmenlar", "pul ishlash", "savdo sotiq", "савдо сотик"],
  "usernames": ["biznes_chat", "biznes_uz", "tadbirkorlar", "biznes_guruh", "savdo_sotiq_uz", "biznes_toshkent"],
  "variations": ["biznes_chatlar", "uz_biznes", "biznes_toshkent", "biznes_discussion", "biznes_elonlar"]
}
"""

    def __init__(self):
        self.api_key = settings.groq.api_key
        self.primary_model = settings.groq.model
        self.fallback_models = ["mixtral-8x7b-32768", "llama3-8b-8192", "gemma2-9b-it"]
        self.max_tokens = settings.groq.max_tokens
        self.client = None
        if self.api_key:
            try:
                self.client = AsyncGroq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
        
        # Gemini Setup
        self.gemini_api_key = settings.gemini.api_key
        self.gemini_model_name = settings.gemini.model
        self.gemini_fallbacks = ["gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-1.0-pro"]
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.gemini_model = None # Initialized lazily or per request to support fallbacks
        else:
            self.gemini_model = None
    
    async def generate_keywords(self, topic: str = "education", count: int = 20) -> Dict[str, List[str]]:
        """
        Generate structured keywords and usernames for a specific topic.
        """
        user_prompt = f"Generate {count} intense search terms for topic: '{topic}'. Use the required JSON format and max broadness."

        # 1. Try Gemini first if available (with fallbacks)
        if self.gemini_api_key:
            for model_name in [self.gemini_model_name] + self.gemini_fallbacks:
                try:
                    logger.info(f"Generating structured keywords using Gemini ({model_name})")
                    model = genai.GenerativeModel(model_name)
                    response = await model.generate_content_async(
                        f"{self.SYSTEM_PROMPT}\n\nUser Request: {user_prompt}",
                        generation_config=genai.GenerationConfig(
                            response_mime_type="application/json",
                        )
                    )
                    import json
                    data = json.loads(response.text)
                    return {
                        "keywords": [str(k).lower() for k in data.get("keywords", [])],
                        "usernames": [str(u).lower().replace(" ", "") for u in data.get("usernames", [])],
                        "variations": [str(v).lower() for v in data.get("variations", [])]
                    }
                except Exception as e:
                    logger.warning(f"Gemini model {model_name} failed: {e}")
                    continue # Try next Gemini model

        # 2. Try Groq/Models fallback
        if self.client:
            models_to_try = [self.primary_model] + self.fallback_models
            for model in models_to_try:
                try:
                    response = await self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        max_tokens=self.max_tokens,
                        temperature=0.8,
                        response_format={"type": "json_object"}
                    )
                
                    import json
                    content = response.choices[0].message.content
                    if not content:
                        continue
                    
                    data = json.loads(content)
                    return {
                        "keywords": [str(k).lower() for k in data.get("keywords", [])],
                        "usernames": [str(u).lower().replace(" ", "") for u in data.get("usernames", [])],
                        "variations": [str(v).lower() for v in data.get("variations", [])]
                    }
                except Exception as e:
                    logger.warning(f"Model {model} failed: {e}")
                    continue
                
        logger.error(f"All AI models failed for structured keywords. Using fallback.")
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
        if not self.client:
            return []
            
        keywords_str = ", ".join(base_keywords[:10])
        user_prompt = f"""Quyidagi keyword'lar asosida {count} ta yangi FUZZY variatsiya yarat:
{keywords_str}

Har bir keyword uchun:
- Boshqa suffikslar qo'sh (-lik, -lar, -chilar, -soy)
- Rus tilida yoz (masalan, obsujdenie, chat, gruppa)
- "group", "chat", "guruh", "uzb" bilan aralashtir.

Faqat keyword'larni vergul bilan ajrat."""

        models_to_try = [self.primary_model] + self.fallback_models
        for model in models_to_try:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=self.max_tokens,
                    temperature=0.9,
                )
            
                content = response.choices[0].message.content
                if not content:
                    continue
                
                variations = [kw.strip().lower() for kw in content.split(",") if kw.strip()]
                logger.info(f"Generated {len(variations)} variations using {model}")
                return variations
                
            except Exception as e:
                logger.warning(f"Model {model} failed generating variations: {e}")
                
        return []
    
    async def expand_single_keyword(self, keyword: str) -> List[str]:
        """
        Expand a single keyword into multiple fuzzy search terms.
        This is useful for immediate searching.
        """
        if not self.client:
            return self._generate_fallback_variations(keyword)

        user_prompt = f"""'{keyword}' qidiruvida telegramdan maksimal ko'p guruh topish uchun uni 25 ta turli xil jozibali qidiruv so'zlariga (keywords) aylantir.

O'ylangan variatsiyalar:
- {keyword} chat, {keyword} guruh, {keyword} uzb
- ruscha va kirillchada ({keyword} gruppa)
- shaharlar bilan ({keyword} toshkent)

Faqat variatsiyalarni vergul bilan ajrat."""

        models_to_try = [self.primary_model] + self.fallback_models
        for model in models_to_try:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=512,
                    temperature=0.8,
                )
            
                content = response.choices[0].message.content
                if not content:
                    continue
                
                variations = [kw.strip().lower() for kw in content.split(",") if kw.strip()]
                all_variations = list(set(variations + self._generate_fallback_variations(keyword)))
                logger.info(f"Expanded '{keyword}' into {len(all_variations)} variations using {model}")
                return all_variations
                
            except Exception as e:
                logger.warning(f"Model {model} failed expanding single keyword: {e}")
                
        return self._generate_fallback_variations(keyword)
    
    async def suggest_topics(self) -> List[str]:
        """
        Suggest related topics for Uzbekistan education/study context.
        """
        if not self.client:
            return []
            
        user_prompt = """O'zbekistonlik foydalanuvchilar qiziqadigan, lekin juda ham aktiv 25 ta guruh mavzularini yoz.
Masalan: Ta'lim, biznes, arenda, uy joy, mashina bozori, IT, til o'rganish, ayollar maslahati.

Faqat mavzu nomlarini vergul bilan ajratib yoz."""

        models_to_try = [self.primary_model] + self.fallback_models
        for model in models_to_try:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=512,
                    temperature=0.8,
                )
            
                content = response.choices[0].message.content
                if not content:
                    continue
                
                topics = [t.strip() for t in content.split(",") if t.strip()]
                logger.info(f"Suggested {len(topics)} topics using {model}")
                return topics
                
            except Exception as e:
                logger.warning(f"Model {model} failed suggesting topics: {e}")
                
        return []

    def _generate_fallback_variations(self, keyword: str) -> List[str]:
        """Simple offline variation generator."""
        clean = keyword.replace(" ", "_")
        return [
            f"{keyword} chat", f"{keyword} guruh", f"{keyword} uz",
            f"{clean}_chat", f"{clean}_guruh", f"{clean}_uzb"
        ]


# Singleton instance
ai_keyword_generator = AIKeywordGenerator()

