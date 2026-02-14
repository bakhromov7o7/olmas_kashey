import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olmas_kashey.core.types import EntityKind
from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline, Candidate
from olmas_kashey.telegram.entity_classifier import ClassifiedEntity


def test_build_query_plan_expands_variants():
    pipeline = DiscoveryPipeline(AsyncMock())
    queries, keywords = pipeline.build_query_plan("IELTS Study Club")
    qset = set(queries)
    assert "ielts_prep" in qset
    assert "ielts_study" in qset
    assert "ielts_study_club" in qset


def test_rank_candidates_prefers_relevant():
    pipeline = DiscoveryPipeline(AsyncMock())
    queries, keywords = pipeline.build_query_plan("IELTS study")

    cand1 = Candidate(ClassifiedEntity(EntityKind.GROUP, 1, "IELTS Study Club", "ielts_xyz"), about="IELTS preparation")
    cand2 = Candidate(ClassifiedEntity(EntityKind.GROUP, 2, "Cooking Club", "cooking_uz"), about=None)

    ranked = pipeline._rank_candidates(queries, keywords, [cand2, cand1])
    assert ranked[0]["chat_id"] == 1


@pytest.mark.asyncio
async def test_discover_with_mocked_search():
    mock_client = AsyncMock()
    raw = MagicMock()
    raw.id = 123
    raw.title = "IELTS Study Club"
    raw.username = "ielts_xyz"
    raw.scam = False
    raw.fake = False
    mock_client.search_public_channels.return_value = [raw]

    pipeline = DiscoveryPipeline(mock_client)

    with patch("olmas_kashey.services.discovery_pipeline.EntityClassifier.classify") as mock_classify:
        mock_classify.return_value = ClassifiedEntity(EntityKind.GROUP, 123, "IELTS Study Club", "ielts_xyz")
        result = await pipeline.discover("IELTS Study Club")
        assert result["status"] == "found"
        assert result["best"]["username"] == "ielts_xyz"
        assert mock_client.search_public_channels.call_count > 0
