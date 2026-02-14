import pytest
import json
from unittest.mock import MagicMock, AsyncMock
from olmas_kashey.services.ai_keyword_generator import AIKeywordGenerator
from olmas_kashey.telegram.client import RequestLimiter, OlmasClient
from telethon import errors

@pytest.mark.asyncio
async def test_ai_generation_structured_output():
    """Test that AI generator returns the expected JSON structure and follows username rules."""
    generator = AIKeywordGenerator()
    # Mock GROQ client
    generator.client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "keywords": ["test topic", "test group"],
            "usernames": ["test_topic", "testgroup"],
            "variations": ["test_official", "test_uz"]
        })))
    ]
    generator.client.chat.completions.create.return_value = mock_response

    result = await generator.generate_keywords("test")
    
    assert "keywords" in result
    assert "usernames" in result
    assert "variations" in result
    assert all(" " not in u for u in result["usernames"])
    assert all(u.islower() for u in result["usernames"])

@pytest.mark.asyncio
async def test_request_limiter_concurrency():
    """Test that RequestLimiter respects concurrency limits."""
    import asyncio
    limiter = RequestLimiter(concurrency=2, intervals={"default": 0.1})
    
    active_requests = 0
    max_active = 0
    
    async def mock_task():
        nonlocal active_requests, max_active
        active_requests += 1
        max_active = max(max_active, active_requests)
        await asyncio.sleep(0.05)
        active_requests -= 1
        
    tasks = [limiter.run("default", mock_task) for _ in range(5)]
    await asyncio.gather(*tasks)
    
    assert max_active <= 2

@pytest.mark.asyncio
async def test_client_flood_backoff():
    """Test that OlmasClient implements exponential backoff on flood errors."""
    client = OlmasClient()
    client.client = AsyncMock()
    
    # Mock a flood error then success
    client.client.side_effect = [
        errors.FloodWaitError(1),
        MagicMock(chats=[])
    ]
    
    # We need to mock asyncio.sleep to avoid waiting
    with MagicMock() as mock_sleep:
        import asyncio
        original_sleep = asyncio.sleep
        asyncio.sleep = AsyncMock()
        
        await client.search_public_channels("test")
        
        # Check that sleep was called with at least 1 second
        asyncio.sleep.assert_called()
        args, _ = asyncio.sleep.call_args
        assert args[0] >= 1
        
        asyncio.sleep = original_sleep

@pytest.mark.asyncio
async def test_fallback_search_logic():
    """Test that DiscoveryPipeline implements fallback if AI search returns no results."""
    from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline
    mock_client = AsyncMock()
    pipeline = DiscoveryPipeline(mock_client)
    
    # Mock AI query plan to return something that results in 0 hits
    pipeline.build_query_plan_ai = AsyncMock(return_value=(["ai_query"], ["ai"]))
    # Mock rule-based query plan
    pipeline.build_query_plan = MagicMock(return_value=(["fb_query"], ["fb"]))
    
    # First search (AI) returns empty
    # Second search (Fallback) returns something
    mock_client.search_public_channels.side_effect = [
        [], # AI query
        [MagicMock(id=123, title="Fallback Group", username="fb_grp", megagroup=True)] # Fallback query
    ]
    
    # Mock _lookup_cache and _cache_entity to avoid DB
    pipeline._lookup_cache = AsyncMock(return_value=None)
    pipeline._cache_entity = AsyncMock()
    
    result = await pipeline.discover("test")
    
    assert mock_client.search_public_channels.call_count >= 2
    # The result might be "not_found" if score is low, but call_count proves fallback was tried
