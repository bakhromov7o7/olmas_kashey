import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from olmas_kashey.services.membership_monitor import MembershipMonitor
from olmas_kashey.db.models import Membership, MembershipState, EntityKind

@pytest.mark.asyncio
async def test_monitor_check_all():
    # Setup Mocks
    mock_client = AsyncMock()
    mock_client.check_membership.side_effect = ["joined", "left", "banned"]
    
    # Mock DB objects
    # We need to mock the result of the JOIN query
    # It returns list of (Membership, Entity) tuples
    
    mem1 = MagicMock(spec=Membership); mem1.state = MembershipState.JOINED
    ent1 = MagicMock(); ent1.id=1; ent1.username="user1"
    
    mem2 = MagicMock(spec=Membership); mem2.state = MembershipState.JOINED
    ent2 = MagicMock(); ent2.id=2; ent2.username="user2"

    mem3 = MagicMock(spec=Membership); mem3.state = MembershipState.JOINED
    ent3 = MagicMock(); ent3.id=3; ent3.username="user3"
    
    mock_results = [(mem1, ent1), (mem2, ent2), (mem3, ent3)]
    
    mock_session = AsyncMock()
    mock_session.execute.return_value.scalars.return_value.all.return_value = [mem1, mem2, mem3] # For first query
    mock_session.execute.return_value.all.return_value = mock_results # For second query with join
    
    async def mock_get_db():
        yield mock_session
        yield mock_session # Yield twice because check_all calls it twice

    with patch("olmas_kashey.services.membership_monitor.get_db", side_effect=mock_get_db):
        monitor = MembershipMonitor(mock_client)
        monitor.per_check_delay = 0 # speed up test
        
        await monitor.check_all()
        
        # Verify interactions
        assert mock_client.check_membership.call_count == 3
        
        # User 1: Joined -> No state change
        assert mem1.state == MembershipState.JOINED
        
        # User 2: Left -> State change to LEFT
        assert mem2.state == MembershipState.LEFT
        assert mem2.left_at is not None
        
        # User 3: Banned -> State change to REMOVED
        assert mem3.state == MembershipState.REMOVED  # Using REMOVED as per models.py definition for "banned" logic mapped in service
        
        # Ensure events added for user 2 and 3
        assert mock_session.add.call_count >= 2
