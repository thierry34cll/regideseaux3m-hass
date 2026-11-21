"""Import water-meter readings as external Home Assistant statistics.

Each reading from the Régie carries the date it was taken (``dateReleve``).
The reading dated D (``dateReleve``) is attributed to the consumption of
that same day D (READING_DATE_OFFSET_DAYS = 0, verified against the Régie
des Eaux website which labels the same dates).

HA always timestamps live state changes at request time, which cannot be
backdated, and the water sensor is TOTAL_INCREASING (HA already computes its
own sums from the states). So readings are written as a **separate external
statistic** ``regiedeseauxmpl:<meter_id>`` via ``async_add_external_statistics``
— the user then selects it in the Energy dashboard (Eau / Water). The
sensor's own statistics are left untouched.

All reads/writes go through the recorder's own APIs, never direct DB access.
Note: ``statistics_during_period`` is a *sync* DB function, so it must be
called via ``Recorder.async_add_executor_job`` (never awaited directly).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import VOLUME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CONF_OVERWRITE_HISTORY,
    CONF_SMOOTH_CONSUMPTION,
    DEFAULT_OVERWRITE_HISTORY,
    DEFAULT_SMOOTH_CONSUMPTION,
    DOMAIN,
    HISTORY_LOOKBACK_DAYS,
    LOGGER,
    READING_DATE_OFFSET_DAYS,
    STORAGE_KEY_HISTORY,
)
from .coordinator import RegieDesEauxCoordinator
from .entity import _short_name

CLEAR_TIMEOUT = 30  # seconds


def external_statistic_id(meter_id: str) -> str:
    """External statistic id for a meter: "<domain>:<slugified meter_id>".

    The object part must be a valid entity-id-like slug (lowercase), hence
    the slugify — contract ids like "C0001" would be rejected by HA.
    """
    return f"{DOMAIN}:{slugify(meter_id)}"


def consumption_date(reading_date: str) -> date:
    """Return the consumption day for a reading date (dateReleve = consumption day)."""
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


async def _existing_start_timestamps(
    hass: HomeAssistant,
    statistic_id: str,
    first_start: datetime,
    last_start: datetime,
) -> set[float]:
    """Return the unix timestamps of the days that already have statistics.

    ``statistics_during_period`` is a sync DB function: it must run in the
    recorder's executor, never awaited directly (that would raise TypeError
    and block the event loop).
    """
    instance = get_instance(hass)
    rows = await instance.async_add_executor_job(
        statistics_during_period,
        hass,
        first_start,
        last_start,
        {statistic_id},
        "day",
        None,
        {"sum"},
    )
    # StatisticsRow["start"] is a unix timestamp (float), not a datetime.
    return {row["start"] for row in rows.get(statistic_id, [])}


async def async_import_readings(
    hass: HomeAssistant,
    meter_id: str,
    name: str,
    readings: list[dict],
    smooth: bool = False,
) -> int:
    """Import readings as daily external statistics, skipping existing days.

    Returns the number of rows actually imported (idempotent: days that
    already have statistics for this statistic_id are never re-imported).
    """
    statistic_id = external_statistic_id(meter_id)
    rows = compute_daily_rows(readings, smooth)
    if not rows:
        return 0

    # Baseline row the day BEFORE the first reading, with the same cumulative
    # value: without it, HA treats the first row's "sum" as a one-off
    # consumption (e.g. the full 300 m³ index shown on a single day).
    first_day, first_cumulative = rows[0]
    rows = [(first_day - timedelta(days=1), first_cumulative)] + rows

    first_start = dt_util.start_of_local_day(
        datetime.combine(rows[0][0], time.min)
    ).astimezone(UTC)
    last_start = dt_util.start_of_local_day(
        datetime.combine(rows[-1][0], time.min)
    ).astimezone(UTC) + timedelta(days=1)

    existing_starts = await _existing_start_timestamps(
        hass, statistic_id, first_start, last_start
    )

    stats = []
    for day, cumulative in rows:
        start = dt_util.start_of_local_day(
            datetime.combine(day, time.min)
        ).astimezone(UTC)
        if start.timestamp() in existing_starts:
            continue
        stats.append(StatisticData(start=start, state=cumulative, sum=cumulative))

    if not stats:
        return 0

    metadata = StatisticMetaData(
        statistic_id=statistic_id,
        source=DOMAIN,
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        unit_class=VOLUME,
        has_mean=False,
        has_sum=True,
        mean_type=StatisticMeanType.NONE,
        name=name,
    )
    # async_add_external_statistics validates statistic_id/source and the
    # presence of mean_type/unit_class (required since HA 2026.11).
    async_add_external_statistics(hass, metadata, stats)
    return len(stats)


async def async_clear_statistics(hass: HomeAssistant, meter_id: str) -> None:
    """Clear all statistics of the external statistic for a meter, and WAIT
    for the recorder job to complete (so a subsequent read of existing days
    does not race with the clear).

    Uses the recorder's own queued job with on_done — the same code path as
    the "delete" button in Developer tools > Statistics.
    """
    instance = get_instance(hass)
    done = asyncio.Event()
    instance.async_clear_statistics(
        [external_statistic_id(meter_id)],
        on_done=lambda: hass.loop.call_soon_threadsafe(done.set),
    )
    await asyncio.wait_for(done.wait(), timeout=CLEAR_TIMEOUT)


async def _load_history_store(hass: HomeAssistant) -> Store:
    return Store(hass, 1, STORAGE_KEY_HISTORY)


async def async_sync_meter_statistics(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: RegieDesEauxCoordinator
) -> None:
    """Import any new readings of every meter as dated external statistics."""
    smooth = bool(
        entry.options.get(
            CONF_SMOOTH_CONSUMPTION,
            entry.data.get(CONF_SMOOTH_CONSUMPTION, DEFAULT_SMOOTH_CONSUMPTION),
        )
    )
    readings_map = coordinator.data.get("readings", {})
    for meter_id, meter in coordinator.data.get("meters", {}).items():
        readings = readings_map.get(meter_id) or []
        try:
            imported = await async_import_readings(
                hass,
                meter_id,
                _short_name(meter.get("name") or meter_id),
                readings,
                smooth,
            )
            if imported:
                LOGGER.info(
                    "Imported %d dated statistics rows for %s",
                    imported,
                    external_statistic_id(meter_id),
                )
        except Exception as err:  # noqa: BLE001 — statistics must never break polling
            LOGGER.warning(
                "Could not import statistics for %s: %s",
                external_statistic_id(meter_id),
                err,
            )


async def async_import_history(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: RegieDesEauxCoordinator
) -> None:
    """One-time import of all readings available online (install option).

    Guards against duplicates/re-runs:
    - the "imported" flag is stored per statistic_id (stable across
      reinstalls, unlike the config entry id), and only for meters that were
      actually processed;
    - async_import_readings never duplicates a day that already has
      statistics, so even a lost flag only fills the gaps;
    - with the "overwrite" option, the external statistic of each meter is
      cleared first AND the clear is awaited before re-reading existing days
      (no race), through the recorder API only — never direct DB access.
    """
    store = await _load_history_store(hass)
    data = await store.async_load() or {}
    done: dict = data.setdefault("done", {})
    entries: dict = data.setdefault("entries", {})

    overwrite = bool(
        entry.options.get(CONF_OVERWRITE_HISTORY)
        or entry.data.get(CONF_OVERWRITE_HISTORY, DEFAULT_OVERWRITE_HISTORY)
    )
    smooth = bool(
        entry.options.get(
            CONF_SMOOTH_CONSUMPTION,
            entry.data.get(CONF_SMOOTH_CONSUMPTION, DEFAULT_SMOOTH_CONSUMPTION),
        )
    )

    for meter_id, meter in coordinator.data.get("meters", {}).items():
        statistic_id = external_statistic_id(meter_id)
        if done.get(statistic_id):
            LOGGER.debug("History already imported for %s, skipping", statistic_id)
            continue
        try:
            if overwrite:
                LOGGER.info("Overwrite: clearing existing statistics for %s", statistic_id)
                await async_clear_statistics(hass, meter_id)  # awaited: no race with the read below

            readings = await coordinator.api.async_get_meter_readings(
                meter_id, days=HISTORY_LOOKBACK_DAYS
            )
            imported = await async_import_readings(
                hass,
                meter_id,
                _short_name(meter.get("name") or meter_id),
                readings,
                smooth,
            )
            LOGGER.info(
                "History import for %s: %d readings over %d days -> %d statistics rows",
                statistic_id, len(readings), HISTORY_LOOKBACK_DAYS, imported,
            )
            done[statistic_id] = True
            entry_sids = entries.setdefault(entry.entry_id, [])
            if statistic_id not in entry_sids:
                entry_sids.append(statistic_id)
            await store.async_save(data)  # flag only this processed meter
        except Exception as err:  # noqa: BLE001 — history must never break setup
            LOGGER.warning("History import failed for %s: %s", statistic_id, err)


async def async_remove_history_flags(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the history-import flags of a removed config entry.

    Without this, a reinstall (new entry_id) would keep the old statistic_id
    flags and skip the history import entirely (e.g. with "overwrite").
    """
    store = await _load_history_store(hass)
    data = await store.async_load()
    if not data:
        return
    entries: dict = data.get("entries", {})
    sids = entries.pop(entry.entry_id, [])
    done: dict = data.get("done", {})
    for sid in sids:
        done.pop(sid, None)
    await store.async_save(data)
