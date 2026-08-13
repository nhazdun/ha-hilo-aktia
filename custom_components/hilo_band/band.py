"""Read-only BLE client for the Hilo Band (Aktiia bracelet).

Safety contract
---------------
This client **never writes** to the band. In particular it never touches the
raw-data control point, because opcodes 0x01/0x07 make the band hand over and
then erase its stored measurement frames. Only Aktiia's cloud can turn those
frames into blood-pressure values, so erasing them from Home Assistant would
destroy the user's measurements permanently.

Everything here is a GATT read of a characteristic the official app also reads.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    AUTH_ERROR_STATUSES,
    CHAR_BATTERY_LEVEL,
    CHAR_CURRENT_TIME,
    CHAR_FIRMWARE_REVISION,
    CHAR_HARDWARE_REVISION,
    CHAR_MANUFACTURER_NAME,
    CHAR_MODEL_NUMBER,
    CHAR_NO_OF_FRAMES,
    CHAR_SERIAL_NUMBER,
    CHAR_STORAGE_LEVEL,
    HBS_SERVICE,
    RAW_DATA_SERVICE,
    SYNC_CONNECT_TIMEOUT_SECONDS,
    TOKEN_AUTHORIZATION_SERVICE,
)

_LOGGER = logging.getLogger(__name__)


class HiloBandAuthError(BleakError):
    """The band refused the read because it is bonded to another central.

    The band bonds with exactly one phone. When Home Assistant is not that
    phone, encrypted characteristics fail with an authentication/encryption
    ATT error instead of returning data.
    """


@dataclass
class HiloBandData:
    """Everything we know about the band right now."""

    address: str
    name: str | None = None

    # Passive (advertisement only)
    rssi: int | None = None
    last_seen: datetime | None = None

    # Active (GATT reads)
    battery_level: int | None = None
    frames_pending: int | None = None
    storage_level: int | None = None
    band_time: datetime | None = None

    # Device Information Service - static, cached after the first success
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    firmware_revision: str | None = None
    hardware_revision: str | None = None

    # Which proprietary services the band exposes
    services: set[str] = field(default_factory=set)

    last_active_read: datetime | None = None
    last_error: str | None = None

    def merge_static(self, other: HiloBandData) -> None:
        """Carry forward static device info across polls that failed."""
        for attr in (
            "manufacturer",
            "model",
            "serial_number",
            "firmware_revision",
            "hardware_revision",
        ):
            if getattr(self, attr) is None and (value := getattr(other, attr)):
                setattr(self, attr, value)


def _parse_uint_be(raw: bytes) -> int | None:
    """Parse an unsigned big-endian integer.

    Mirrors the app, which does ``Integer.parseInt(byteArrayToHex(bytes), 16)``
    on both the battery level and the frame count.
    """
    if not raw:
        return None
    return int.from_bytes(raw, byteorder="big", signed=False)


def _parse_current_time(raw: bytes) -> datetime | None:
    """Parse a BLE Current Time Service value.

    Layout, per ``PodTimestampPacketsKt.currentTimeBytes``:
    ``year(uint16 LE) month day hours minutes seconds day_of_week`` followed by
    ``fractions256`` and ``adjust_reason`` in the full CTS characteristic.
    """
    if len(raw) < 7:
        return None
    try:
        year = int.from_bytes(raw[0:2], byteorder="little", signed=False)
        month, day, hour, minute, second = raw[2], raw[3], raw[4], raw[5], raw[6]
        if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 2000):
            return None
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        _LOGGER.debug("Unparseable current-time payload: %s", raw.hex())
        return None


def _is_auth_error(err: BaseException) -> bool:
    """Detect the "bonded to another phone" family of ATT errors."""
    text = str(err).lower()
    if any(k in text for k in ("insufficient authentication", "insufficient encryption")):
        return True
    return any(f"error: {code}" in text or f"({code})" in text for code in AUTH_ERROR_STATUSES)


class HiloBandClient:
    """Connects to the band, reads what is safe to read, disconnects."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._lock = asyncio.Lock()

    async def async_read(
        self, device: BLEDevice, previous: HiloBandData | None = None
    ) -> HiloBandData:
        """Connect, read every readable value, then disconnect.

        Raises:
            HiloBandAuthError: the band is bonded to a different central.
            BleakError: any other connection or GATT failure.
        """
        data = HiloBandData(address=self._address, name=device.name)

        # One connection at a time - the band is a single-link peripheral.
        async with self._lock:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self._address,
                timeout=SYNC_CONNECT_TIMEOUT_SECONDS,
            )
            try:
                await self._read_into(client, data)
            finally:
                with contextlib.suppress(Exception):
                    await client.disconnect()

        if previous is not None:
            data.merge_static(previous)
        data.last_active_read = datetime.now(timezone.utc)
        return data

    async def _read_into(self, client, data: HiloBandData) -> None:
        """Populate *data* from the connected *client*."""
        try:
            services = client.services
        except (AttributeError, BleakError):  # pragma: no cover - backend dependent
            services = None
        if services is not None:
            available = {str(service.uuid).lower() for service in services}
            for uuid in (RAW_DATA_SERVICE, HBS_SERVICE, TOKEN_AUTHORIZATION_SERVICE):
                if uuid in available:
                    data.services.add(uuid)

        # Dynamic values first - they matter most and the link may drop early.
        data.battery_level = await self._read_int(client, CHAR_BATTERY_LEVEL, 0, 100)
        data.frames_pending = await self._read_int(client, CHAR_NO_OF_FRAMES)
        data.storage_level = await self._read_int(client, CHAR_STORAGE_LEVEL, 0, 100)

        if (raw := await self._read_raw(client, CHAR_CURRENT_TIME)) is not None:
            data.band_time = _parse_current_time(raw)

        # Static device information.
        data.manufacturer = await self._read_str(client, CHAR_MANUFACTURER_NAME)
        data.model = await self._read_str(client, CHAR_MODEL_NUMBER)
        data.serial_number = await self._read_str(client, CHAR_SERIAL_NUMBER)
        data.firmware_revision = await self._read_str(client, CHAR_FIRMWARE_REVISION)
        data.hardware_revision = await self._read_str(client, CHAR_HARDWARE_REVISION)

    async def _read_raw(self, client, uuid: str) -> bytes | None:
        """Read one characteristic, tolerating "not present" but not auth errors."""
        try:
            return bytes(await client.read_gatt_char(uuid))
        except BleakError as err:
            if _is_auth_error(err):
                raise HiloBandAuthError(
                    "Band rejected the read - it is bonded to another device "
                    "(normally your phone). Home Assistant can only read it "
                    "while it is not bonded elsewhere."
                ) from err
            _LOGGER.debug("Characteristic %s unavailable: %s", uuid, err)
            return None
        except Exception as err:  # noqa: BLE001 - backend errors vary widely
            _LOGGER.debug("Characteristic %s read failed: %s", uuid, err)
            return None

    async def _read_int(
        self, client, uuid: str, lo: int | None = None, hi: int | None = None
    ) -> int | None:
        raw = await self._read_raw(client, uuid)
        if raw is None:
            return None
        value = _parse_uint_be(raw)
        if value is None:
            return None
        if lo is not None and hi is not None and not lo <= value <= hi:
            _LOGGER.debug("Value %s from %s outside [%s, %s]", value, uuid, lo, hi)
            return None
        return value

    async def _read_str(self, client, uuid: str) -> str | None:
        raw = await self._read_raw(client, uuid)
        if raw is None:
            return None
        return raw.decode("utf-8", errors="replace").strip("\x00").strip() or None
