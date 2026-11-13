"""Tests for the Régie des Eaux coordinator."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import time

from custom_components.regiedeseauxmpl.coordinator import (
    RegieDesEauxCoordinator,
    parse_update_time,
)
from custom_components.regiedeseauxmpl.const import (
    DEFAULT_UPDATE_TIME,
    DOMAIN,
)


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.helpers = MagicMock()
    hass.helpers.now = MagicMock(return_value=MagicMock(isoformat=MagicMock(return_value="2024-01-01T00:00:00")))
    return hass


@pytest.fixture
def mock_api():
    """Create a mock API with test data."""
    api = MagicMock()
    api.async_get_meters = AsyncMock(return_value=[
        {"id": "meter1", "name": "Compteur 1", "serial_number": "SN001"},
        {"id": "meter2", "name": "Compteur 2", "serial_number": "SN002"},
    ])
    api.async_get_meter_index = AsyncMock(return_value={"index": 123.456, "timestamp": "2024-01-01"})
    return api


@pytest.mark.asyncio
async def test_coordinator_init_default_update_time(mock_hass, mock_api):
    """Test coordinator initialization with default daily update time."""
    coordinator = RegieDesEauxCoordinator(mock_hass, mock_api)

    assert coordinator.name == DOMAIN
    assert coordinator.update_time == time(5, 0)
    assert coordinator.api == mock_api
    # No internal sliding timer: one refresh per day at a fixed time.
    assert coordinator.update_interval is None
    assert DEFAULT_UPDATE_TIME == "05:00"


@pytest.mark.asyncio
async def test_coordinator_init_custom_update_time(mock_hass, mock_api):
    """Test coordinator initialization with a custom daily update time."""
    coordinator = RegieDesEauxCoordinator(mock_hass, mock_api, "08:30")

    assert coordinator.update_time == time(8, 30)


def test_parse_update_time():
    """Test parsing of daily update time values."""
    assert parse_update_time(None) == time(5, 0)
    assert parse_update_time("05:00") == time(5, 0)
    assert parse_update_time("23:45") == time(23, 45)
    assert parse_update_time(time(7, 15)) == time(7, 15)


@pytest.mark.asyncio
async def test_setup_daily_update_registers_tracker(mock_hass, mock_api):
    """One async_track_time_change registration at the configured time."""
    coordinator = RegieDesEauxCoordinator(mock_hass, mock_api, "06:15")

    with patch(
        "custom_components.regiedeseauxmpl.coordinator.async_track_time_change"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        unsub = coordinator.setup_daily_update()

        mock_track.assert_called_once()
        assert mock_track.call_args.kwargs["hour"] == 6
        assert mock_track.call_args.kwargs["minute"] == 15
        assert mock_track.call_args.kwargs["second"] == 0

        unsub()
        mock_track.return_value.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_update_data_success(mock_hass, mock_api):
    """Test successful data update."""
    coordinator = RegieDesEauxCoordinator(mock_hass, mock_api)

    # Mock the data
    mock_api.async_get_meters = AsyncMock(return_value=[
        {"id": "meter1", "name": "Test Meter"},
    ])
    mock_api.async_get_meter_index = AsyncMock(return_value={"index": 100.5, "timestamp": "2024-01-01"})

    data = await coordinator._async_update_data()

    assert "meters" in data
    assert "meter1" in data["meters"]
    assert data["meters"]["meter1"]["index"] == 100.5
    assert data["meters"]["meter1"]["timestamp"] == "2024-01-01"
    assert "last_updated" in data


@pytest.mark.asyncio
async def test_coordinator_update_data_with_error(mock_hass):
    """Test data update with API error."""
    from custom_components.regiedeseauxmpl.exceptions import RegieDesEauxError

    mock_api = MagicMock()
    mock_api.async_get_meters = AsyncMock(side_effect=RegieDesEauxError("API Error"))

    coordinator = RegieDesEauxCoordinator(mock_hass, mock_api)

    with pytest.raises(Exception) as exc_info:
        await coordinator._async_update_data()

    assert "API Error" in str(exc_info.value)
