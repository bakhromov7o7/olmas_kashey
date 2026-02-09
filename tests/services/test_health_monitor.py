import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telethon import errors
from olmas_kashey.services.health_monitor import HealthMonitor

@pytest.mark.asyncio
async def test_health_monitor_healthy():
    mock_client = AsyncMock()
    # Mock get_entity returning something (success)
    mock_client.get_entity.return_value = MagicMock() 
    
    # Mock send/delete message
    msg_mock = MagicMock()
    msg_mock.id = 123
    mock_client.client.send_message.return_value = msg_mock
    
    monitor = HealthMonitor(mock_client)
    
    is_healthy = await monitor.check_health()
    
    assert is_healthy is True
    assert monitor.is_restricted is False
    mock_client.client.send_message.assert_called()
    mock_client.client.delete_messages.assert_called()

@pytest.mark.asyncio
async def test_health_monitor_restricted_flood():
    mock_client = AsyncMock()
    mock_client.get_entity.return_value = MagicMock()
    
    # Raise PeerFloodError on send
    mock_client.client.send_message.side_effect = errors.PeerFloodError("Too many messages")
    
    monitor = HealthMonitor(mock_client)
    
    is_healthy = await monitor.check_health()
    
    assert is_healthy is False
    assert monitor.is_restricted is True
    assert "PeerFloodError" in monitor.restriction_reason
