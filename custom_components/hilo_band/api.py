"""Async client for the Aktiia / Hilo cloud API.

Reverse-engineered from the official Android app ``com.aktiia.android.production``
v2.12.1, specifically ``com.aktiia.data.net.AktiiaApi``,
``AktiiaServerResolverApi``, ``ApiConstantKt`` and
``com.aktiia.interceptor.HttpAktiiaInterceptor``.

Flow
----
1. ``POST {RESOLVER}/server-resolver/login`` with an OAuth2 password grant and
   the app's Basic client credentials. The response carries ``accessToken``,
   ``refreshToken`` and — importantly — ``serverUrl``, the regional API host
   this account actually lives on.
2. Every later call goes to ``serverUrl`` with the access token in the
   ``Authorization`` header.
3. On 401, refresh via ``POST {serverUrl}/oauth/api/v1/token`` with the
   refresh-token grant (that one endpoint uses Basic auth, not the token).

This is read-only: the client only issues GETs after logging in.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp
from aiohttp import ClientResponseError, ClientSession

from .const import (
    API_BASIC_AUTHORIZATION,
    API_PLATFORM,
    API_PRODUCT_STANDARD,
    API_VERSION_CODE,
    CLOUD_RESOLVER_URL,
    EP_DAILY,
    EP_DAILY_TTR,
    EP_DEVICES,
    EP_LATEST_INITIALIZATION,
    EP_LATEST_MEASUREMENT,
    EP_LOGIN,
    EP_SLEEP_SUMMARY,
    EP_STEPS,
    EP_TOKEN,
    EP_USER,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=45)


class AktiiaError(Exception):
    """Base error for the Aktiia cloud client."""


class AktiiaAuthError(AktiiaError):
    """Credentials were rejected, or the refresh token is no longer valid."""


class AktiiaUpgradeRequired(AktiiaError):
    """Server returned 426 - this client version is too old for the API."""


class AktiiaBraceletBlocked(AktiiaError):
    """Server returned 406 - the bracelet is blocked on this account."""


@dataclass
class Measurement:
    """A single blood-pressure measurement."""

    systolic: int | None = None
    diastolic: int | None = None
    heart_rate: int | None = None
    taken_at: datetime | None = None
    measurement_type: str | None = None
    algo_version: str | None = None


@dataclass
class DailyStats:
    """Aggregates for one calendar day."""

    avg_systolic: float | None = None
    avg_diastolic: float | None = None
    avg_heart_rate: float | None = None
    measurement_count: int | None = None
    normal_bp_percentage: float | None = None


@dataclass
class TimeInRange:
    """Time-in-target-range breakdown, in percent."""

    excellent: float | None = None
    adequate: float | None = None
    inadequate: float | None = None
    poor: float | None = None
    without_measurements: float | None = None


@dataclass
class SleepSummary:
    """Last night's sleep."""

    duration_seconds: int | None = None
    time_asleep_seconds: int | None = None
    start: datetime | None = None
    end: datetime | None = None


@dataclass
class DeviceInfo:
    """A paired Hilo device as the cloud knows it."""

    advertising_name: str | None = None
    mac_address: str | None = None
    serial_number: str | None = None
    firmware_revision: str | None = None
    manufacturer_name: str | None = None


@dataclass
class AktiiaData:
    """Everything one poll collects."""

    latest: Measurement = field(default_factory=Measurement)
    today: DailyStats = field(default_factory=DailyStats)
    ttr: TimeInRange = field(default_factory=TimeInRange)
    sleep: SleepSummary = field(default_factory=SleepSummary)
    steps_average: float | None = None
    steps_today: float | None = None
    last_calibration: datetime | None = None
    calibration_partial: bool | None = None
    pod: DeviceInfo | None = None
    cuff: DeviceInfo | None = None


def _parse_epoch(value: Any) -> datetime | None:
    """Parse an epoch timestamp that may be in seconds or milliseconds."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    # The app stores these as epoch millis; tolerate seconds too.
    seconds = value / 1000 if value > 1e11 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_int(value: Any) -> int | None:
    """Coerce to int, treating the app's -1 "not defined" sentinel as missing."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = int(value)
    return None if result < 0 else result


def _as_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    return None if result < 0 else result


class AktiiaClient:
    """Talks to the Aktiia cloud on behalf of one account."""

    def __init__(
        self,
        session: ClientSession,
        *,
        device_id: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        server_url: str | None = None,
    ) -> None:
        self._session = session
        self._device_id = device_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._server_url = (server_url or CLOUD_RESOLVER_URL).rstrip("/")
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Session state - persisted in the config entry so we can skip login
    # ------------------------------------------------------------------

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    @property
    def server_url(self) -> str:
        return self._server_url

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _headers(self, authorization: str) -> dict[str, str]:
        """Build the header set the app sends on every request."""
        return {
            "Authorization": authorization,
            "Time-Zone": datetime.now().astimezone().tzname() or "UTC",
            "Accept-Language": "en",
            "Version-Code": API_VERSION_CODE,
            "Platform": API_PLATFORM,
            "X-Device-ID": self._device_id,
            "X-Device-Model": "HomeAssistant",
            "X-Device-OS": "15",
            "X-Correlation-Id": str(uuid.uuid4()),
            "X-Product": API_PRODUCT_STANDARD,
        }

    def _auth_value(self) -> str:
        """The Authorization value for data requests.

        The app passes the stored token straight through, which means the
        server hands back a value that already includes its scheme. Older
        deployments return a bare JWT, so add the scheme when it is absent.
        """
        token = self._access_token or ""
        if not token:
            return API_BASIC_AUTHORIZATION
        lowered = token.lower()
        if lowered.startswith(("bearer ", "basic ")):
            return token
        return f"Bearer {token}"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def async_login(self, username: str, password: str) -> None:
        """Exchange credentials for tokens and discover the regional server."""
        payload = {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
        headers = self._headers(API_BASIC_AUTHORIZATION)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        url = f"{CLOUD_RESOLVER_URL.rstrip('/')}/{EP_LOGIN}"
        try:
            async with self._session.post(
                url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (400, 401, 403):
                    raise AktiiaAuthError("Aktiia rejected the email or password")
                self._raise_for_special_status(response.status)
                response.raise_for_status()
                data = await response.json(content_type=None)
        except ClientResponseError as err:
            raise AktiiaError(f"Login failed: HTTP {err.status}") from err
        except aiohttp.ClientError as err:
            raise AktiiaError(f"Login failed: {err}") from err

        self._apply_login(data)

    def _apply_login(self, data: dict[str, Any]) -> None:
        """Store tokens and the regional server URL from a login/refresh body."""
        if not isinstance(data, dict):
            raise AktiiaError("Unexpected login response")
        access = data.get("accessToken") or data.get("access_token")
        if not access:
            raise AktiiaAuthError("Login response contained no access token")
        self._access_token = access
        if refresh := (data.get("refreshToken") or data.get("refresh_token")):
            self._refresh_token = refresh
        if server := data.get("serverUrl"):
            self._server_url = str(server).rstrip("/")
            _LOGGER.debug("Aktiia account lives on %s", self._server_url)

    async def async_refresh_token(self) -> None:
        """Swap the refresh token for a fresh access token."""
        if not self._refresh_token:
            raise AktiiaAuthError("No refresh token available")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        # This endpoint authenticates with the client credentials, not the
        # (expired) access token - see HttpAktiiaInterceptor.
        headers = self._headers(API_BASIC_AUTHORIZATION)
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        url = f"{self._server_url}/{EP_TOKEN}"
        try:
            async with self._session.post(
                url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (400, 401, 403):
                    raise AktiiaAuthError("Refresh token was rejected")
                self._raise_for_special_status(response.status)
                response.raise_for_status()
                data = await response.json(content_type=None)
        except ClientResponseError as err:
            raise AktiiaError(f"Token refresh failed: HTTP {err.status}") from err
        except aiohttp.ClientError as err:
            raise AktiiaError(f"Token refresh failed: {err}") from err

        self._apply_login(data)

    @staticmethod
    def _raise_for_special_status(status: int) -> None:
        """Translate the two status codes the app treats specially."""
        if status == 406:
            raise AktiiaBraceletBlocked("Bracelet is blocked on this account")
        if status == 426:
            raise AktiiaUpgradeRequired(
                "Aktiia requires a newer client version than this integration "
                "reports; the API contract may have changed"
            )

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, *, retry: bool = True
    ) -> Any:
        """GET a JSON endpoint, refreshing the token once on 401."""
        url = f"{self._server_url}/{path.lstrip('/')}"
        try:
            async with self._session.get(
                url,
                params=params,
                headers=self._headers(self._auth_value()),
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status == 401 and retry:
                    async with self._refresh_lock:
                        await self.async_refresh_token()
                    return await self._get(path, params, retry=False)
                if response.status == 401:
                    raise AktiiaAuthError("Aktiia rejected the access token")
                if response.status == 404:
                    # Plenty of these endpoints 404 when there is simply no
                    # data yet (no sleep recorded, never calibrated, ...).
                    return None
                self._raise_for_special_status(response.status)
                response.raise_for_status()
                if response.content_length == 0:
                    return None
                return await response.json(content_type=None)
        except ClientResponseError as err:
            raise AktiiaError(f"GET {path} failed: HTTP {err.status}") from err
        except aiohttp.ClientError as err:
            raise AktiiaError(f"GET {path} failed: {err}") from err

    # ------------------------------------------------------------------
    # Typed endpoints
    # ------------------------------------------------------------------

    async def async_get_latest_measurement(self) -> Measurement:
        """Most recent blood-pressure measurement."""
        data = await self._get(EP_LATEST_MEASUREMENT)
        if not isinstance(data, dict):
            return Measurement()
        return Measurement(
            systolic=_as_int(data.get("sys")),
            diastolic=_as_int(data.get("dia")),
            heart_rate=_as_int(data.get("hr")),
            taken_at=_parse_epoch(data.get("dateTime")),
            measurement_type=data.get("measurementType"),
            algo_version=data.get("algoVersion"),
        )

    async def async_get_daily(self, day: date) -> DailyStats:
        """Averages and counts for one day."""
        data = await self._get(EP_DAILY, {"date": day.isoformat()})
        if not isinstance(data, dict):
            return DailyStats()
        average = data.get("avg") or {}
        summary = data.get("summary") or {}
        return DailyStats(
            avg_systolic=_as_float(average.get("sys")),
            avg_diastolic=_as_float(average.get("dia")),
            avg_heart_rate=_as_float(average.get("hr")),
            measurement_count=_as_int(summary.get("count")),
            normal_bp_percentage=_as_float(data.get("normalBPPercentage")),
        )

    async def async_get_daily_ttr(self, day: date) -> TimeInRange:
        """Time-in-target-range for one day."""
        data = await self._get(EP_DAILY_TTR, {"date": day.isoformat()})
        if not isinstance(data, dict):
            return TimeInRange()
        return TimeInRange(
            excellent=_as_float(data.get("timeInExcellentRange")),
            adequate=_as_float(data.get("timeInAdequateRange")),
            inadequate=_as_float(data.get("timeInInadequateRange")),
            poor=_as_float(data.get("timeInPoorRange")),
            without_measurements=_as_float(data.get("timeWithoutMeasurements")),
        )

    async def async_get_sleep(self, day: date) -> SleepSummary:
        """Sleep summary for one day."""
        data = await self._get(EP_SLEEP_SUMMARY, {"date": day.isoformat()})
        if not isinstance(data, dict):
            return SleepSummary()
        return SleepSummary(
            duration_seconds=_as_int(data.get("durationSeconds")),
            time_asleep_seconds=_as_int(data.get("timeAsleepSeconds")),
            start=_parse_iso(data.get("start")),
            end=_parse_iso(data.get("end")),
        )

    async def async_get_steps(self, day: date) -> tuple[float | None, float | None]:
        """Return ``(average, today)`` step counts over the trailing week."""
        params = {
            "from": (day - timedelta(days=7)).isoformat(),
            "to": day.isoformat(),
        }
        data = await self._get(EP_STEPS, params)
        if not isinstance(data, dict):
            return None, None
        summary = data.get("summary") or {}
        average = _as_float(summary.get("average"))

        today = None
        series = data.get("series")
        if isinstance(series, dict):
            entry = series.get(day.isoformat())
            if isinstance(entry, dict):
                today = _as_float(entry.get("value"))
        return average, today

    async def async_get_latest_initialization(self) -> tuple[datetime | None, bool | None]:
        """Return ``(calibrated_at, is_partial)``."""
        data = await self._get(EP_LATEST_INITIALIZATION)
        if not isinstance(data, dict):
            return None, None
        partial = data.get("isPartial")
        return _parse_epoch(data.get("time")), (
            partial if isinstance(partial, bool) else None
        )

    async def async_get_devices(self) -> tuple[DeviceInfo | None, DeviceInfo | None]:
        """Return ``(pod, cuff)`` as the cloud has them registered."""
        data = await self._get(EP_DEVICES)
        if not isinstance(data, dict):
            return None, None

        def _device(raw: Any) -> DeviceInfo | None:
            if not isinstance(raw, dict):
                return None
            return DeviceInfo(
                advertising_name=raw.get("advertisingName"),
                mac_address=raw.get("macAddress"),
                serial_number=raw.get("serialNumber"),
                firmware_revision=raw.get("firmwareRevision"),
                manufacturer_name=raw.get("manufacturerName"),
            )

        return _device(data.get("pod")), _device(data.get("cuff"))

    async def async_get_account(self) -> dict[str, Any]:
        """Account details, used to label the config entry."""
        data = await self._get(EP_USER)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Aggregate poll
    # ------------------------------------------------------------------

    async def async_fetch_all(self, today: date) -> AktiiaData:
        """Fetch everything the integration exposes, concurrently.

        Individual endpoints are allowed to fail without sinking the poll:
        a missing sleep record should not blank out blood pressure.
        """
        results = await asyncio.gather(
            self.async_get_latest_measurement(),
            self.async_get_daily(today),
            self.async_get_daily_ttr(today),
            self.async_get_sleep(today),
            self.async_get_steps(today),
            self.async_get_latest_initialization(),
            self.async_get_devices(),
            return_exceptions=True,
        )

        # An auth failure on any call is fatal for the whole poll.
        for result in results:
            if isinstance(result, AktiiaAuthError):
                raise result

        data = AktiiaData()
        latest, daily, ttr, sleep, steps, calibration, devices = results

        if isinstance(latest, Measurement):
            data.latest = latest
        if isinstance(daily, DailyStats):
            data.today = daily
        if isinstance(ttr, TimeInRange):
            data.ttr = ttr
        if isinstance(sleep, SleepSummary):
            data.sleep = sleep
        if isinstance(steps, tuple):
            data.steps_average, data.steps_today = steps
        if isinstance(calibration, tuple):
            data.last_calibration, data.calibration_partial = calibration
        if isinstance(devices, tuple):
            data.pod, data.cuff = devices

        for result in results:
            if isinstance(result, Exception):
                _LOGGER.debug("Aktiia sub-request failed: %s", result)

        return data
