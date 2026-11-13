"""DataUpdateCoordinator for Régie des Eaux Montpellier."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import RegieDesEauxAPI
from .const import DEFAULT_UPDATE_TIME, DOMAIN, LOGGER
from .exceptions import RegieDesEauxError


def parse_update_time(value: str | time | None) -> time:
    """Parse a daily update time given as a "HH:MM" string or a time object."""
    if value is None:
        value = DEFAULT_UPDATE_TIME
    if isinstance(value, time):
        return value
    hour, _, minute = str(value).partition(":")
    return time(hour=int(hour), minute=int(minute or 0))


class RegieDesEauxCoordinator(DataUpdateCoordinator[dict]):
    """Data update coordinator for Régie des Eaux Montpellier.

    The utility publishes a new reading only once a day, so instead of a
    sliding update interval the coordinator triggers one refresh per day at
    a fixed, configurable time (`update_time`, default 05:00). Manual
    refreshes stay available through the `refresh_meters` service.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: RegieDesEauxAPI,
        update_time: str | time | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: HomeAssistant instance
            api: API client instance
            update_time: Daily wall-clock time ("HH:MM") of the refresh.
                         If None, uses DEFAULT_UPDATE_TIME.
        """
        # No internal timer: the daily refresh is scheduled at a fixed time.
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.api = api
        self.update_time = parse_update_time(update_time)

    @callback
    def setup_daily_update(self) -> Callable[[], None]:
        """Schedule the daily refresh at `update_time`.

        Returns an unsubscribe callback (to be registered with
        `entry.async_on_unload`).
        """
        unsub = async_track_time_change(
            self.hass,
            self._async_daily_refresh,
            hour=self.update_time.hour,
            minute=self.update_time.minute,
            second=0,
        )

        @callback
        def _unsub() -> None:
            unsub()

        return _unsub

    async def _async_daily_refresh(self, now: datetime) -> None:
        """Handle the daily refresh triggered by the time tracker."""
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict:
        """Fetch data from the API."""
        try:
            meters = await self.api.async_get_meters()
            data = {"meters": {}, "readings": {}, "last_updated": None}

            for meter in meters:
                meter_id = meter["id"]
                readings = await self.api.async_get_meter_readings(meter_id)
                data["readings"][meter_id] = readings
                if readings:
                    latest = readings[-1]
                    index_info = {"index": latest["index"], "timestamp": latest["date"]}
                else:
                    index_info = {"index": None, "timestamp": None}
                data["meters"][meter_id] = {
                    **meter,
                    **index_info,
                }

            data["last_updated"] = dt_util.now().isoformat()
            return data

        except RegieDesEauxError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
