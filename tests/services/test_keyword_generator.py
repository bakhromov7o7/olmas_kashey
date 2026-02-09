import pytest
from olmas_kashey.services.keyword_generator import KeywordGenerator

def test_normalization():
    gen = KeywordGenerator()
    assert gen._normalize("   IELTS   ") == "ielts"
    assert gen._normalize("Tashkent") == "tashkent"

def test_generation_seeded():
    gen1 = KeywordGenerator(seed=42)
    gen2 = KeywordGenerator(seed=42)
    
    list1 = list(gen1.generate())
    list2 = list(gen2.generate())
    
    assert len(list1) > 0
    assert list1 == list2

def test_deduplication():
    # Mock base attributes to force duplicates if logic failed
    gen = KeywordGenerator()
    gen.BASE_KEYWORDS = ["test", "test"]
    gen.MODIFIERS = []
    
    results = list(gen.generate())
    assert len(results) == 1
    assert results[0] == "test"
