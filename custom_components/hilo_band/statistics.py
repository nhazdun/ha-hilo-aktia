"""Import historical Hilo measurements into the Home Assistant recorder.

Blood-pressure readings arrive with timestamps in the past — often days or
months old on a first sync. Ordinary sensor states cannot express that: the
recorder timestamps states when it sees them. So history goes in as **external
statistics** instead, which is the sanctioned way to backfill a time series
from an outside source.

Each measurement stream (systolic, diastolic, heart rate) becomes one external
statistic bucketed hourly with mean/min/max. They are deliberately kept
separate from the live sensors' own statistics so the two never fight over the
same statistic_id.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import AktiiaClient, Measurement
from .const import DOMAIN, STAT_STREAMS

_LOGGER = logging.getLogger(__name__)

# How far back to reach on a first import when the account has no recorded
# "first measurement" date to anchor to.
DEFAULT_BACKFILL_DAYS = 365


def _mean_kwargs() -> dict:
    """Describe an arithmetic-mean statistic for whichever core we run on.

    Home Assistant 2025.11 replaced ``has_mean=True`` with a ``mean_type``
    enum and warns when the old form is used. The enum has lived at more than
    one import path, so try each before falling back.
    """
    for module in (
        "homeassistant.components.recorder.models.statistics",
        "homeassistant.components.recorder.models",
        "homeassistant.components.recorder.statistics",
    ):
        try:
            mod = __import__(module, fromlist=["StatisticMeanType"])
            return {"mean_type": mod.StatisticMeanType.ARITHMETIC}
        except (ImportError, AttributeError):
            continue
    _LOGGER.warning(
        "This Home Assistant has no StatisticMeanType; falling back to the "
        "deprecated has_mean flag"
    )
    return {"has_mean": True}


_MEAN_KWARGS = _mean_kwargs()


def _statistic_id(slug: str, key: str) -> str:
    """Build an external statistic id.

    External ids use ``domain:object_id`` — a colon, not a dot, which is what
    keeps them out of the entity namespace.
    """
    return f"{DOMAIN}:{slug}_{key}"


class HiloStatisticsImporter:
    """Backfills and then incrementally extends the measurement history."""

    def __init__(
        self, hass: HomeAssistant, client: AktiiaClient, slug: str, device_name: str
    ) -> None:
        self.hass = hass
        self._client = client
        self._slug = slug
        self._device_name = device_name

    async def async_import(self, *, full: bool = False) -> int:
        """Import measurements into statistics.

        Args:
            full: ignore existing statistics and re-import the whole history.

        Returns:
            The number of measurements imported.
        """
        start = await self._async_resolve_start(full=full)
        end = dt_util.now().date() + timedelta(days=1)

        if start > end:
            return 0

        _LOGGER.debug("Importing Hilo history from %s to %s", start, end)
        measurements = await self._client.async_get_measurement_history(start, end)
        if not measurements:
            _LOGGER.debug("No Hilo measurements returned for %s..%s", start, end)
            return 0

        for key, meta in STAT_STREAMS.items():
            self._write_stream(key, meta, measurements)

        _LOGGER.info(
            "Imported %s Hilo measurements into statistics (from %s)",
            len(measurements),
            start,
        )
        return len(measurements)

    async def _async_resolve_start(self, *, full: bool) -> date:
        """Work out the first day we still need to import."""
        today = dt_util.now().date()

        if not full:
            last = await self._async_last_statistic_time()
            if last is not None:
                # Re-import the final hour: it may have been partial.
                return (last - timedelta(hours=1)).astimezone(
                    dt_util.get_default_time_zone()
                ).date()

        first = await self._client.async_get_first_measurement_date()
        if first is not None:
            return first.astimezone(dt_util.get_default_time_zone()).date()
        return today - timedelta(days=DEFAULT_BACKFILL_DAYS)

    async def _async_last_statistic_time(self) -> datetime | None:
        """Timestamp of the newest statistic we have already written."""
        statistic_id = _statistic_id(self._slug, "systolic")
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, set()
        )
        rows = last.get(statistic_id) if last else None
        if not rows:
            return None
        start = rows[0].get("start")
        if start is None:
            return None
        # Recorder hands back a float epoch in recent versions.
        if isinstance(start, (int, float)):
            return dt_util.utc_from_timestamp(start)
        return start

    def _write_stream(
        self, key: str, meta: dict[str, str], measurements: list[Measurement]
    ) -> None:
        """Bucket one value stream by hour and hand it to the recorder."""
        buckets: dict[datetime, list[float]] = defaultdict(list)

        for measurement in measurements:
            value = getattr(measurement, meta["attr"])
            if value is None or measurement.taken_at is None:
                continue
            # Statistics buckets must start exactly on the hour, in UTC.
            hour = dt_util.as_utc(measurement.taken_at).replace(
                minute=0, second=0, microsecond=0
            )
            buckets[hour].append(float(value))

        if not buckets:
            return

        statistics: list[StatisticData] = [
            StatisticData(
                start=hour,
                mean=sum(values) / len(values),
                min=min(values),
                max=max(values),
            )
            for hour, values in sorted(buckets.items())
        ]

        metadata = StatisticMetaData(
            has_sum=False,
            name=f"{self._device_name} {meta['name']}",
            source=DOMAIN,
            statistic_id=_statistic_id(self._slug, key),
            unit_of_measurement=meta["unit"],
            # mmHg and bpm have no unit converter, and blood pressure must
            # never be rescaled anyway - state the absence explicitly rather
            # than let the recorder warn about an unspecified unit class.
            unit_class=None,
            **_MEAN_KWARGS,
        )
        async_add_external_statistics(self.hass, metadata, statistics)
