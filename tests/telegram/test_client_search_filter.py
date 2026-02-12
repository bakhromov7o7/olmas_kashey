import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telethon.tl.types import Channel

from olmas_kashey.core.types import EntityKind
from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.telegram.entity_classifier import ClassifiedEntity


@pytest.mark.asyncio
async def test_search_includes_left_megagroup():
    client = OlmasClient(client=AsyncMock())
    channel = MagicMock(spec=Channel)
    channel.left = True
    channel.megagroup = True
    result = SimpleNamespace(chats=[channel])

    with patch.object(client, "_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = result
        found = await client.search_public_channels("ielts", limit=10)
        assert len(found) == 1


@pytest.mark.asyncio
async def test_pipeline_finds_left_megagroup():
    client = OlmasClient(client=AsyncMock())
    channel = MagicMock(spec=Channel)
    channel.left = True
    channel.megagroup = True
    result = SimpleNamespace(chats=[channel])

    with patch.object(client, "_call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = result
        pipeline = DiscoveryPipeline(client)
        with patch.object(pipeline, "_lookup_cache", new_callable=AsyncMock) as mock_cache:
            mock_cache.return_value = None
            with patch.object(pipeline, "_cache_entity", new_callable=AsyncMock) as mock_cache_entity:
                mock_cache_entity.return_value = None
                with patch("olmas_kashey.services.discovery_pipeline.EntityClassifier.classify") as mock_classify:
                    mock_classify.return_value = ClassifiedEntity(EntityKind.GROUP, 2, "IELTS Study Group", "ielts_study")
                    res = await pipeline.discover("IELTS Study Group")
                    assert res["status"] == "found"
