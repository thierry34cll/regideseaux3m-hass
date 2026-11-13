"""Import water-meter readings into Home Assistant statistics.

Each reading from the Régie carries the date it was taken (``dateReleve``).
The utility publishes the previous day's reading overnight, so a reading
dated D is attributed to the consumption of day D - READING_DATE_OFFSET_DAYS.

HA always timestamps live state changes at request time, which cannot be
backdated, so dated readings are written to the recorder statistics with
``async_import_statistics`` — this is what the Energy dashboard uses.

All writes go through the recorder's own APIs (``async_import_statistics`` /
``Recorder.async_clear_statistics``), never through direct database access.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SMOOTH_CONSUMPTION,
    DEFAULT_SMOOTH_CONSUMPTION,
    DOMAIN,
    LOGGER,
    READING_DATE_OFFSET_DAYS,
)
from .coordinator import RegieDesEauxCoordinator


def consumption_date(reading_date: str) -> date:
    """Return the consumption day for a reading date (published D = consumed D-1)."""
    day = datetime.fromisoformat(str(reading_date)[:10]).date()
    return day - timedelta(days=READING_DATE_OFFSET_DAYS)


def compute_daily_rows(
    readings: list[dict], smooth: bool = False
) -> list[tuple[date, float]]:
    """Compute (consumption_day, cumulative_sum) rows from readings.

    ``readings`` is a list of {"date": "YYYY-MM-DD", "index": m³} entries.

    Without smoothing, each reading produces one row on its consumption day.
    With smoothing, when no reading happened for N days, the delta is spread
    evenly over those N days (e.g. 1 m³ appearing after a 3-day gap becomes
    ~0.333 m³ per day).
    """
    rows: dict[date, float] = {}
    prev_day: date | None = None
    prev_index: float | None = None
    for reading in sorted(readings, key=lambda r: r["date"]):
        day = consumption_date(reading["date"])
        index = float(reading["index"])
        if prev_day is not None and smooth and (day - prev_day).days > 1:
            gap = (day - prev_day).days
            share = (index - prev_index) / gap
            for k in range(1, gap + 1):
                rows[prev_day + timedelta(days=k)] = round(prev_index + share * k, 6)
        else:
            rows[day] = index
        prev_day, prev_index = day, index
    return sorted(rows.items())


def meter_entity_id(hass: HomeAssistant, meter_id: str) -> str | None:
    """Return the sensor entity_id for a meter (unique_id = f"{DOMAIN}_{meter_id}")."""
    registry = async_get_entity_registry(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{meter_id}")


async def async_import_readings(
    hass: HomeAssistant,
    statistic_id: str,
    name: str,
    readings: list[dict],
    smooth: bool = False,
) -> int:
    """Import readings as daily statistics, skipping days that already exist.

    Returns the number of rows actually imported (idempotent: existing
    statistics for the same statistic_id and day are never duplicated).
    """
    rows = compute_daily_rows(readings, smooth)
    if not rows:
        return 0

    first_start = dt_util.start_of_local_day(
        datetime.combine(rows[0][0], time.min)
    ).astimezone(UTC)
    last_start = dt_util.start_of_local_day(
        datetime.combine(rows[-1][0], time.min)
    ).astimezone(UTC) + timedelta(days=1)

    existing = await statistics_during_period(
        hass,
        first_start,
        last_start,
        {statistic_id},
        period="day",
        units=None,
        types={"sum"},
    )
    existing_starts = {row["start"] for row in existing.get(statistic_id, [])}

    stats = []
    for day, cumulative in rows:
        start = dt_util.start_of_local_day(
            datetime.combine(day, time.min)
        ).astimezone(UTC)
        if start in existing_starts:
            continue
        stats.append(StatisticData(start=start, state=cumulative, sum=cumulative))

    if not stats:
        return 0

    metadata = StatisticMetaData(
        statistic_id=statistic_id,
        source=DOMAIN,
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        has_mean=False,
        has_sum=True,
        name=name,
    )
    async_import_statistics(hass, metadata, stats)
    return len(stats)


def async_clear_statistics(hass: HomeAssistant, statistic_id: str) -> None:
    """Clear all statistics for a statistic_id.

    Uses the recorder's own queued job — the same code path as the
    "delete" button in Developer tools > Statistics.
    """
    try:
        instance = get_instance(hass)
    except Exception:  # noqa: BLE001 — recorder may not be running
        LOGGER.warning("Recorder not available, cannot clear %s", statistic_id)
        return
    instance.async_clear_statistics([statistic_id])


async def async_sync_meter_statistics(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: RegieDesEauxCoordinator
) -> None:
    """Import any new readings of every meter as dated statistics."""
    smooth = bool(
        entry.options.get(
            CONF_SMOOTH_CONSUMPTION,
            entry.data.get(CONF_SMOOTH_CONSUMPTION, DEFAULT_SMOOTH_CONSUMPTION),
        )
    )
    await hass.async_block_till_done()
    readings_map = coordinator.data.get("readings", {})
    for meter_id, meter in coordinator.data.get("meters", {}).items():
        entity_id = meter_entity_id(hass, meter_id)
        if not entity_id:
            LOGGER.debug("No entity yet for meter %s, skipping statistics", meter_id)
            continue
        readings = readings_map.get(meter_id) or []
        try:
            imported = await async_import_readings(
                hass, entity_id, meter.get("name") or meter_id, readings, smooth
            )
            if imported:
                LOGGER.info(
                    "Imported %d dated statistics rows for %s", imported, entity_id
                )
        except Exception as err:  # noqa: BLE001 — statistics must never break polling
            LOGGER.warning("Could not import statistics for %s: %s", entity_id, err)
