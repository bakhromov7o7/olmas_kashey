import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from olmas_kashey.services.group_discovery import GroupDiscoveryService
from olmas_kashey.core.types import EntityKind
from olmas_kashey.services.discovery_pipeline import Candidate
from olmas_kashey.telegram.entity_classifier import ClassifiedEntity

@pytest.mark.asyncio
async def test_process_keyword_success():
    # Mock mocks
    mock_client = AsyncMock()
    mock_planner = AsyncMock()
    
    from unittest.mock import patch
    
    with patch("olmas_kashey.services.group_discovery.DiscoveryPipeline.search_candidates", new_callable=AsyncMock) as mock_search_candidates:
        mock_result_entity = ClassifiedEntity(EntityKind.GROUP, 12345, "Test Group", "testgroup")
        mock_search_candidates.return_value = [Candidate(mock_result_entity)]
        
        # Mock DB
        # GroupDiscoveryService uses `async for session in get_db():`
        # We need to patch get_db to return a mock session.
        
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None # No existing entity
        
        # Mock generator for get_db
        async def mock_get_db_gen():
            yield mock_session
            
        with patch("olmas_kashey.services.group_discovery.get_db", side_effect=mock_get_db_gen):
            service = GroupDiscoveryService(mock_client, mock_planner)
            
            await service._process_keyword("test_keyword")
            
            # Assertions
            mock_search_candidates.assert_called_once_with("test_keyword")
            
            # Check session.add called for New Entity, Event, Membership, SearchRun
            assert mock_session.add.call_count >= 4 
            # 1 Entity, 1 Event, 1 Membership, 1 SearchRun (maybe more if multiple results)
            
            mock_session.commit.assert_called()

@pytest.mark.asyncio
async def test_run_loop():
    mock_client = AsyncMock()
    mock_planner = AsyncMock()
    
    # Planner returns [kw1, kw2, None]
    mock_planner.get_next_query.side_effect = ["kw1", "kw2", None]
    
    service = GroupDiscoveryService(mock_client, mock_planner)
    service._process_keyword = AsyncMock() # Mock internal to avoid complex DB setup
    
    await service.run(iterations=5)
    
    assert service._process_keyword.call_count == 2
    service._process_keyword.assert_any_call("kw1")
    service._process_keyword.assert_any_call("kw2")
