"""Integration tests: config entry setup on a real Home Assistant core."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.regiedeseauxmpl.const import DOMAIN


async def test_setup_creates_device_and_sensor(hass, mock_api, config_entry):
    """The entry loads and registers one device + one water sensor per meter."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert (DOMAIN, "C0001") in device.identifiers
    assert device.name == "Eau potable"
    assert device.serial_number == "I23IA727517"
    assert device.via_device_id is None

    entities = er.async_entries_for_config_entry(
        er.async_get(hass), config_entry.entry_id
    )
    assert len(entities) == 1
    state = hass.states.get(entities[0].entity_id)
    assert state is not None
    assert float(state.state) == 123.456


async def test_setup_does_not_use_deprecated_device_info(
    hass, mock_api, config_entry, caplog
):
    """No deprecated DeviceInfo parameter is passed to the device registry.

    `via_device` is deprecated since HA 2026.8 (removed in 2027.8). When HA
    attributes the call to a core integration (e.g. setup triggered from the UI
    config flow, reported as integration 'config' in issue #1) it raises a
    RuntimeError and the sensors are never created.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert "deprecated" not in caplog.text
    assert "via_device" not in caplog.text


async def test_setup_from_ui_config_flow(hass, hass_client, mock_api):
    """Adding the integration from the UI creates the sensor (issue #1).

    Goes through the HTTP config-flow API like the frontend does, so the setup
    runs under the core `config` integration's request handler.
    """
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    with patch(
        "custom_components.regiedeseauxmpl.api.RegieDesEauxAPI.async_authenticate",
        new=AsyncMock(return_value=True),
    ):
        resp = await client.post(
            "/api/config/config_entries/flow", json={"handler": DOMAIN}
        )
        assert resp.status == 200
        flow = await resp.json()
        resp = await client.post(
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            json={"username": "test@example.com", "password": "secret"},
        )
        assert resp.status == 200, await resp.text()
        result = await resp.json()
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    entry = hass.config_entries.async_get_entry(result["result"]["entry_id"])
    assert entry.state is ConfigEntryState.LOADED
    assert len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 1


async def test_readings_synced_to_statistics_after_setup(hass, mock_api, config_entry):
    """After setup, readings are passed to the statistics import at their dates.

    HA timestamps live state changes at request time (not backdatable), so the
    integration forwards the readings to async_import_statistics with
    start = consumption day (dateReleve - 1 day).
    """
    from custom_components.regiedeseauxmpl.statistics import meter_entity_id

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = meter_entity_id(hass, "C0001")
    assert entity_id is not None

    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics.statistics_during_period",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_import_statistics"
        ) as mock_import,
    ):
        from custom_components.regiedeseauxmpl.statistics import (
            async_sync_meter_statistics,
        )

        coordinator = hass.data[DOMAIN][config_entry.entry_id]
        await async_sync_meter_statistics(hass, config_entry, coordinator)
        await hass.async_block_till_done()

    assert mock_import.call_count == 1
    metadata, stats = mock_import.call_args.args[1], mock_import.call_args.args[2]
    assert metadata["statistic_id"] == entity_id
    # readings 2026-10-19 and 2026-10-20 -> consumption days 2026-10-18/19
    assert [s["sum"] for s in stats] == [122.456, 123.456]
    assert [s["start"].date().isoformat() for s in stats] == ["2026-10-18", "2026-10-19"]


async def test_smooth_consumption_spreads_gap(hass, mock_api):
    """With the smoothing option on, a cumulative reading is spread over the gap."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.regiedeseauxmpl.const import (
        CONF_PASSWORD,
        CONF_SMOOTH_CONSUMPTION,
        CONF_USERNAME,
    )
    from custom_components.regiedeseauxmpl.statistics import (
        async_sync_meter_statistics,
        meter_entity_id,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="test@example.com",
        data={CONF_USERNAME: "test@example.com", CONF_PASSWORD: "secret"},
        options={CONF_SMOOTH_CONSUMPTION: True},
    )
    # gap: readings on 2026-10-19 and 2026-10-22 (1 m³ over a 3-day gap)
    readings = [
        {"date": "2026-10-19", "index": 122.0},
        {"date": "2026-10-22", "index": 123.0},
    ]
    with patch(
        "custom_components.regiedeseauxmpl.api.RegieDesEauxAPI.async_get_meter_readings",
        new=AsyncMock(return_value=readings),
    ):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id = meter_entity_id(hass, "C0001")
    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics.statistics_during_period",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_import_statistics"
        ) as mock_import,
    ):
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await async_sync_meter_statistics(hass, entry, coordinator)
        await hass.async_block_till_done()

    assert mock_import.call_count == 1
    stats = mock_import.call_args.args[2]
    # consumption days 10-18 (122.0) then 10-19..10-21 spread of 1 m³
    assert [s["start"].date().isoformat() for s in stats] == [
        "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21",
    ]
    assert [round(s["sum"], 3) for s in stats] == [122.0, 122.333, 122.667, 123.0]


async def test_history_import_wiring_and_once_guard(hass, mock_api, config_entry):
    """Point 4: setup schedules the one-time history import; the import itself
    fetches all available online data (wide window) and runs only once."""
    from custom_components.regiedeseauxmpl.const import HISTORY_LOOKBACK_DAYS
    from custom_components.regiedeseauxmpl.statistics import (
        async_import_history,
        meter_entity_id,
    )

    # 1) wiring: setup schedules async_import_history
    with patch(
        "custom_components.regiedeseauxmpl.async_import_history", new=AsyncMock()
    ) as mock_hist:
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_hist.call_count == 1

    # 2) real import: wide window + idempotent (guard via storage flag)
    entity_id = meter_entity_id(hass, "C0001")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics.statistics_during_period",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_import_statistics"
        ) as mock_import,
    ):
        await async_import_history(hass, config_entry, coordinator)
        await hass.async_block_till_done()
        assert mock_import.call_count == 1
        call = coordinator.api.async_get_meter_readings.call_args
        assert HISTORY_LOOKBACK_DAYS in (call.kwargs.get("days"), *call.args)

        # second call: persistent guard -> nothing re-imported
        await async_import_history(hass, config_entry, coordinator)
        await hass.async_block_till_done()
        assert mock_import.call_count == 1


async def test_history_import_overwrite_clears_first(hass, mock_api):
    """Point 4 overwrite mode: existing statistics are cleared through the
    recorder API (same path as the UI delete button) before re-importing."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.regiedeseauxmpl.const import (
        CONF_OVERWRITE_HISTORY,
        CONF_PASSWORD,
        CONF_USERNAME,
    )
    from custom_components.regiedeseauxmpl.statistics import (
        async_import_history,
        meter_entity_id,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="test@example.com",
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "secret",
            CONF_OVERWRITE_HISTORY: True,
        },
    )
    with patch(
        "custom_components.regiedeseauxmpl.async_import_history", new=AsyncMock()
    ):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id = meter_entity_id(hass, "C0001")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics.statistics_during_period",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_import_statistics"
        ) as mock_import,
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_clear_statistics"
        ) as mock_clear,
    ):
        await async_import_history(hass, entry, coordinator)
        await hass.async_block_till_done()

    mock_clear.assert_called_once_with(hass, entity_id)
    assert mock_import.call_count == 1
