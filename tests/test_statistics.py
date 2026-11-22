"""Tests for the dated-statistics computation (Régie des Eaux readings)."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.regiedeseauxmpl.statistics import (
    async_import_readings,
    compute_daily_rows,
    consumption_date,
)
from custom_components.regiedeseauxmpl.const import READING_DATE_OFFSET_DAYS

READINGS = [
    {"date": "2026-11-02", "index": 100.0},
    {"date": "2026-11-03", "index": 101.0},
    # no reading on 2026-11-04 / 2026-11-05
    {"date": "2026-11-06", "index": 102.0},
]


def test_consumption_date_offset():
    """dateReleve is the consumption day itself (verified vs Régie website)."""
    assert READING_DATE_OFFSET_DAYS == 0
    assert consumption_date("2026-11-06") == date(2026, 11, 6)


def test_compute_daily_rows_without_smoothing():
    """One row per reading, on its consumption day, cumulative sum."""
    rows = compute_daily_rows(READINGS, smooth=False)
    assert rows == [
        (date(2026, 11, 2), 100.0),
        (date(2026, 11, 3), 101.0),
        (date(2026, 11, 6), 102.0),
    ]


def test_compute_daily_rows_with_smoothing():
    """A 1 m³ delta appearing after a 3-day gap is spread over the 3 days."""
    rows = compute_daily_rows(READINGS, smooth=True)
    assert rows == [
        (date(2026, 11, 2), 100.0),
        (date(2026, 11, 3), 101.0),
        (date(2026, 11, 4), round(101.0 + 1 / 3, 6)),
        (date(2026, 11, 5), round(101.0 + 2 / 3, 6)),
        (date(2026, 11, 6), 102.0),
    ]


def test_compute_daily_rows_user_example():
    """1 m³ on Nov 6 after no data on Nov 3-5 -> 0.25 m³/day over 4 days."""
    readings = [
        {"date": "2026-11-02", "index": 50.0},
        {"date": "2026-11-06", "index": 51.0},
    ]
    rows = compute_daily_rows(readings, smooth=True)
    # consumption days are the reading dates: 11-02 then 11-06, gap of 4 days
    # -> 1 m3 spread as 0.25/day over 11-03..11-06
    assert rows == [
        (date(2026, 11, 2), 50.0),
        (date(2026, 11, 3), 50.25),
        (date(2026, 11, 4), 50.5),
        (date(2026, 11, 5), 50.75),
        (date(2026, 11, 6), 51.0),
    ]


def test_compute_daily_rows_empty():
    assert compute_daily_rows([], smooth=True) == []


@pytest.mark.asyncio
async def test_import_readings_skips_existing_days():
    """Idempotency guard: days that already have statistics are not re-imported.

    StatisticsRow["start"] is a unix timestamp (float), not a datetime.
    """
    hass = MagicMock()
    readings = [
        {"date": "2026-11-02", "index": 100.0},
        {"date": "2026-11-03", "index": 101.0},
    ]
    existing_start = datetime(2026, 11, 2, 23, 0, tzinfo=UTC).timestamp()  # reading 11-02 stamped 23:30

    from types import SimpleNamespace

    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics._existing_start_timestamps",
            new=AsyncMock(return_value={existing_start}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.slugify",
            new=lambda s: s.lower(),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.StatisticData",
            new=lambda **kw: SimpleNamespace(**kw),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.StatisticMetaData",
            new=lambda **kw: SimpleNamespace(**kw),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_add_external_statistics"
        ) as mock_import,
    ):
        imported = await async_import_readings(
            hass, "C0001", "Compteur", readings, smooth=False
        )

    # relative sums (base = first reading 100.0): only the new 11-03 row,
    # with sum = 101.0 - 100.0 = 1.0; the 11-02 row already exists
    assert imported == 1
    assert mock_import.call_count == 1
    metadata, stats = mock_import.call_args.args[1], mock_import.call_args.args[2]
    # external statistic, source aligned with the statistic_id domain
    assert metadata.statistic_id == "regiedeseauxmpl:c0001"
    assert metadata.source == "regiedeseauxmpl"
    assert [(st.start, st.sum) for st in stats] == [
        (datetime(2026, 11, 3, 23, 0, tzinfo=UTC), 1.0),
    ]


@pytest.mark.asyncio
async def test_import_readings_nothing_new():
    """When everything already exists, no import call is made."""
    hass = MagicMock()
    readings = [{"date": "2026-11-02", "index": 100.0}]
    with (
        patch(
            "custom_components.regiedeseauxmpl.statistics._existing_start_timestamps",
            new=AsyncMock(return_value={datetime(2026, 11, 2, 23, 0, tzinfo=UTC).timestamp()}),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.slugify",
            new=lambda s: s.lower(),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.StatisticData",
            new=lambda **kw: SimpleNamespace(**kw),
        ),
        patch(
            "custom_components.regiedeseauxmpl.statistics.async_add_external_statistics"
        ) as mock_import,
    ):
        imported = await async_import_readings(
            hass, "C0001", "Compteur", readings, smooth=False
        )

    assert imported == 0
    mock_import.assert_not_called()


@pytest.mark.asyncio
async def test_existing_starts_read_via_executor_job():
    """statistics_during_period is a SYNC DB function: it must run in the
    recorder executor (async_add_executor_job), never awaited directly."""
    from custom_components.regiedeseauxmpl.statistics import (
        _existing_start_timestamps,
        statistics_during_period,
    )

    hass = MagicMock()
    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(
        return_value={"regiedeseauxmpl:c0001": [{"start": 1234.0, "sum": 1.0}]}
    )
    with patch(
        "custom_components.regiedeseauxmpl.statistics.get_instance",
        return_value=instance,
    ):
        res = await _existing_start_timestamps(
            hass, "regiedeseauxmpl:c0001", MagicMock(), MagicMock()
        )

    assert res == {1234.0}
    # the sync DB function is the executor job target, not awaited
    assert instance.async_add_executor_job.call_args.args[0] is statistics_during_period
