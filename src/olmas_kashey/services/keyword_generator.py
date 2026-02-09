import random
from typing import Iterator, List, Optional

from olmas_kashey.core.settings import settings

class KeywordGenerator:
    """
    Generates search queries for Telegram group discovery.
    """

    BASE_KEYWORDS = [
        # Simple, effective keywords
        "ielts", "ielts uzbek", "ielts speaking", "ielts writing",
        "english", "english group", "ingliz tili", 
        "study abroad", "xorijda o'qish",
        "scholarship", "grant", "stipendiya",
        "cefr", "dtm", "dtm 2025",
        "tashkent", "toshkent", "samarkand", "bukhara",
        "uzbekistan", "o'zbekiston",
        "university", "universitet", "talaba",
        "education", "ta'lim", "o'quv markaz",
        "english course", "ingliz tili kursi",
        "репетитор", "английский", "ташкент",
        "работа ташкент", "вакансии",
    ]

    MODIFIERS = [
        "guruh", "chat", "group", "community",
        "2024", "2025", "official", "rasmiy"
    ]

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)

    def _normalize(self, text: str) -> str:
        """
        Normalize text by lowercasing and stripping whitespace.
        Additional normalization (e.g., removing emojis or special chars) could be added here.
        """
        return text.strip().lower()

    def generate(self, batch_size: int = 100) -> Iterator[str]:
        """
        Generates a stream of search queries.
        Combines base keywords with modifiers and shuffles them.
        """
        
        combined = []
        
        # 1. Base keywords alone
        for kw in self.BASE_KEYWORDS:
            combined.append(self._normalize(kw))
            
        # 2. Base + Modifier
        for kw in self.BASE_KEYWORDS:
            for mod in self.MODIFIERS:
                combined.append(self._normalize(f"{kw} {mod}"))
                combined.append(self._normalize(f"{mod} {kw}")) # Reverse order too? Maybe less common but possible.

        # Deduplicate
        unique_queries = list(set(combined))
        
        # Shuffle deterministically
        self._rng.shuffle(unique_queries)
        
        for query in unique_queries:
            yield query

keyword_generator = KeywordGenerator()
