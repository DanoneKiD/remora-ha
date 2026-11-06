"""Wrapper around pyremora that tolerates an unreachable or rebooting board.

The Remora board (ESP8266) reboots on its own and refuses connections for
about 30 s, then may answer with invalid values (for example "fp1": "\\0").
Every call here is bounded by a short timeout, retried once, and validated.
After MAX_FAILURES consecutive failed polls the device is reported as
unavailable, and the last good values are kept until then.
"""
import asyncio
import logging
from datetime import timedelta

from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES_REMORA_SENSOR = timedelta(seconds=5)
MIN_TIME_BETWEEN_UPDATES_REMORA_CLIMATE = timedelta(seconds=2)

REQUEST_TIMEOUT = 5
RETRY_DELAY = 1
MAX_FAILURES = 3


class RemoraDevice:
    """Stores the data retrieved from Remora.
    For each entity to use, acts as the single point responsible for fetching
    updates from the server.
    """

    def __init__(self, host):
        """Initialize the data object."""
        import remora

        self._host = host
        self._remora = remora.RemoraDevice(self._host)
        self._teleInfo = None
        self._filPiloteDic = None
        self._relais = None
        self._failures = 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def available(self) -> bool:
        """True once data was read and fewer than MAX_FAILURES polls failed in a row."""
        return self._filPiloteDic is not None and self._failures < MAX_FAILURES

    async def _call(self, func, *args, retry=True):
        """Run a pyremora coroutine with a timeout and one retry."""
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(func(*args), REQUEST_TIMEOUT)
            except Exception as err:  # pylint: disable=broad-except
                if attempt + 1 == attempts:
                    raise
                _LOGGER.debug("Remora %s: %s, new attempt", func.__name__, err)
                await asyncio.sleep(RETRY_DELAY)

    async def _poll(self, func, attr):
        """Refresh one cached value; keep the previous one on failure."""
        try:
            setattr(self, attr, await self._call(func))
        except Exception as err:  # pylint: disable=broad-except
            self._failures += 1
            log = _LOGGER.warning if self._failures == MAX_FAILURES else _LOGGER.debug
            log("Remora %s unreachable or invalid answer (%s failures): %s", self._host, self._failures, err)
            return False
        if self._failures >= MAX_FAILURES:
            _LOGGER.info("Remora %s is back", self._host)
        self._failures = 0
        return True

    async def async_reset(self) -> bool:
        """Reset remora."""
        return await self._remora.reset()

    async def async_check_HeartBeat(self) -> bool:
        """Get the status from Remora."""
        try:
            return await self._call(self._remora.getHeartBeat)
        except Exception:  # pylint: disable=broad-except
            return False

    @property
    def TeleInfo(self) -> dict:
        """Return TeleInfo."""
        """TeleInfo can be None (if the module is not enabled)"""
        return self._teleInfo

    async def async_get_TeleInfo(self) -> dict:
        """Get the status from Remora TeleInfo and return it as a dict."""
        return await self._call(self._remora.getTeleInfo)

    @Throttle(MIN_TIME_BETWEEN_UPDATES_REMORA_SENSOR)
    async def async_updateTeleInfo(self, **kwargs) -> None:
        """Fetch the latest status from TeleInfo"""
        try:
            self._teleInfo = await self.async_get_TeleInfo()
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("Remora TeleInfo unavailable: %s", err)

    @property
    def FilPiloteDic(self) -> dict:
        """Return AllFilPilote."""
        return self._filPiloteDic

    async def async_set_FilPilote(self, num, fpMode) -> bool:
        ok = await self._call(self._remora.setFilPilote, num, fpMode)
        # Read back what the board really applied
        await self.async_updateAllFilPilote(no_throttle=True)
        return ok

    async def async_get_AllFilPilote(self) -> dict:
        """Get the status from Remora FilPilote and
        return it as a dict. Invalid values raise ValueError in pyremora."""
        return await self._remora.getAllFilPilote()

    @Throttle(MIN_TIME_BETWEEN_UPDATES_REMORA_CLIMATE)
    async def async_updateAllFilPilote(self, **kwargs) -> None:
        """Fetch the latest status for FilPilote"""
        await self._poll(self.async_get_AllFilPilote, "_filPiloteDic")

    @property
    def RelaisDic(self) -> dict:
        """Get latest update if throttle allows.
        Return the current Mode Relais"""
        return self._relais

    async def async_set_ModeRelais(self, rMode) -> bool:
        ok = await self._call(self._remora.setFnctRelais, rMode)
        await self.async_updateRelais(no_throttle=True)
        return ok

    async def async_set_EtatRelais(self, rEtat) -> bool:
        ok = await self._call(self._remora.setRelais, rEtat)
        await self.async_updateRelais(no_throttle=True)
        return ok

    async def async_get_Relais(self) -> dict:
        """Get the status from Remora Relais"""
        return await self._remora.getRelais()

    @Throttle(MIN_TIME_BETWEEN_UPDATES_REMORA_CLIMATE)
    async def async_updateRelais(self, **kwargs) -> None:
        """Fetch the latest status for Relais"""
        try:
            self._relais = await self._call(self.async_get_Relais)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("Remora relais unavailable: %s", err)
