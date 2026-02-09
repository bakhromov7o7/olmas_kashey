import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from olmas_kashey.services.group_discovery import GroupDiscoveryService
from olmas_kashey.core.types import EntityKind
from olmas_kashey.telegram.entity_classifier import ClassifiedEntity

@pytest.mark.asyncio
async def test_process_keyword_success():
    # Mock mocks
    mock_client = AsyncMock()
    mock_planner = AsyncMock()
    
    # Mock search results
    # We need raw entities that classifier expects.
    # Logic: client returns raw list -> classifier.classify(raw) -> Entity
    # We can mock classifier OR mock raw entities to satisfy classifier.
    # GroupDiscoveryService imports EntityClassifier.
    # Easier to mock client returning objects that Classifier handles or mock Classifier.classify?
    # Classifier is static method `classify`. Hard to mock static on class usage inside function without patch.
    # Let's patch EntityClassifier.classify.
    
    from unittest.mock import patch
    
    with patch("olmas_kashey.services.group_discovery.EntityClassifier.classify") as mock_classify:
        # Setup mocks
        mock_result_entity = ClassifiedEntity(EntityKind.GROUP, 12345, "Test Group", "testgroup")
        mock_classify.return_value = mock_result_entity
        
        mock_client.search_public_channels.return_value = ["some_raw_obj"]
        
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
            mock_client.search_public_channels.assert_called_once_with("test_keyword", limit=50)
            mock_classify.assert_called_once_with("some_raw_obj")
            
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
