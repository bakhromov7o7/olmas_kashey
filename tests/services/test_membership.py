import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from olmas_kashey.services.membership import MembershipService, MembershipState
from olmas_kashey.db.models import AllowlistItem, Entity, Membership, EntityKind

@pytest.fixture
def mock_client():
    return AsyncMock()

@pytest.fixture
def service(mock_client):
    return MembershipService(mock_client)

@pytest.mark.asyncio
async def test_add_remove_allowlist():
    # Mock DB session
    mock_session = AsyncMock()
    mock_session.execute.return_value.scalar_one_or_none.return_value = None # Not existing

    async def mock_get_db():
        yield mock_session

    with patch("olmas_kashey.services.membership.get_db", side_effect=mock_get_db):
        svc = MembershipService(AsyncMock())
        result = await svc.add_to_allowlist("test_user")
        assert result is True
        mock_session.add.assert_called()
        
        # Test remove
        mock_session.execute.return_value.scalar_one_or_none.return_value = AllowlistItem(target="test_user")
        result_remove = await svc.remove_from_allowlist("test_user")
        assert result_remove is True
        mock_session.delete.assert_called()

@pytest.mark.asyncio
async def test_process_joins_rate_limit():
    # Mock joins_today count to be at limit
    mock_session = AsyncMock()
    mock_session.execute.return_value.scalar_one.return_value = 5 # max per day

    async def mock_get_db():
        yield mock_session

    with patch("olmas_kashey.services.membership.get_db", side_effect=mock_get_db):
        svc = MembershipService(AsyncMock())
        svc.max_joins_per_day = 5
        
        await svc.process_joins()
        
        # Should return early, no client calls
        svc.client.join_channel.assert_not_called()

@pytest.mark.asyncio
async def test_process_joins_success():
    mock_session = AsyncMock()
    
    # Mock 1: Daily joins count -> 0
    # Mock 2: Fetch allowlist -> [item]
    # Mock 3: Fetch candidates -> [entity]
    # Mock 4: Check recent failure -> None
    
    # Side effects for execute() calls in sequence
    mock_joins_cnt = MagicMock(); mock_joins_cnt.scalar_one.return_value = 0
    
    mock_allowlist = MagicMock(); mock_allowlist.scalars.return_value.all.return_value = [AllowlistItem(target="test_group")]
    
    entity = Entity(id=1, username="test_group", kind=EntityKind.GROUP, memberships=None)
    mock_candidates = MagicMock(); mock_candidates.scalars.return_value.all.return_value = [entity]
    
    mock_fail_check = MagicMock(); mock_fail_check.scalar_one_or_none.return_value = None

    # Sequence of returns for execute()
    mock_session.execute.side_effect = [
        mock_joins_cnt,   # count
        mock_allowlist,   # allowlist
        mock_candidates,  # candidates query
        mock_fail_check   # recent failure check
    ]

    async def mock_get_db():
        yield mock_session

    with patch("olmas_kashey.services.membership.get_db", side_effect=mock_get_db):
        mock_client = AsyncMock()
        svc = MembershipService(mock_client)
        svc.max_joins_per_day = 5
        
        await svc.process_joins()
        
        mock_client.join_channel.assert_called_once_with("test_group")
        assert mock_session.add.call_count >= 2 # Membership, Event
        mock_session.commit.assert_called()
