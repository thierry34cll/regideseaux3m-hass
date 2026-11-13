"""Integration Régie des Eaux Montpellier."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RegieDesEauxAPI
from .const import (
    CONF_PASSWORD,
    CONF_UPDATE_TIME,
    CONF_USERNAME,
    DEFAULT_UPDATE_TIME,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .coordinator import RegieDesEauxCoordinator
from .statistics import async_sync_meter_statistics


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Régie des Eaux Montpellier from a config entry."""
    session = async_get_clientsession(hass)

    update_time = entry.options.get(
        CONF_UPDATE_TIME,
        entry.data.get(CONF_UPDATE_TIME, DEFAULT_UPDATE_TIME),
    )

    api = RegieDesEauxAPI(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    coordinator = RegieDesEauxCoordinator(hass, api, update_time)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # One refresh per day at the configured time, so the reading time does
    # not depend on the last Home Assistant restart.
    entry.async_on_unload(coordinator.setup_daily_update())
    # Reload the entry when its options change so the new time applies.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Import each new reading into the recorder statistics at its real
    # consumption date (the live state itself is always timestamped at
    # request time, which cannot be backdated).
    @callback
    def _schedule_stats_sync() -> None:
        hass.async_create_task(async_sync_meter_statistics(hass, entry, coordinator))

    entry.async_on_unload(coordinator.async_add_listener(_schedule_stats_sync))
    hass.async_create_task(async_sync_meter_statistics(hass, entry, coordinator))

    # Register services
    async def handle_refresh(call):
        """Handle service call to refresh meters."""
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "refresh_meters", handle_refresh)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

        # Unregister services
        if hass.services.has_service(DOMAIN, "refresh_meters"):
            hass.services.async_remove(DOMAIN, "refresh_meters")

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry format to new one."""
    # Migration from version 0 (no scan_interval) to version 1 (with scan_interval)
    if entry.version < 1:
        LOGGER.debug("Migrating config entry from version %s to 1", entry.version)
        hass.config_entries.async_update_entry(
            entry,
            version=1,
        )

    # Migration to version 2: replace the sliding scan interval with a daily
    # update time (default 05:00).
    if entry.version < 2:
        LOGGER.debug("Migrating config entry from version %s to 2", entry.version)
        from .const import CONF_SCAN_INTERVAL

        new_options = {**entry.options}
        if CONF_UPDATE_TIME not in new_options and CONF_UPDATE_TIME not in entry.data:
            new_options[CONF_UPDATE_TIME] = DEFAULT_UPDATE_TIME
        new_data = {k: v for k, v in entry.data.items() if k != CONF_SCAN_INTERVAL}
        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options,
            version=2,
        )

    return True
