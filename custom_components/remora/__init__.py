"""Support for the Remora devices."""
import logging
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_HOST

from .const import DOMAIN, SERVICE_RESET
from .remora import RemoraDevice

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_HOST): cv.string})}, extra=vol.ALLOW_EXTRA
)

RESET_SCHEMA = vol.Schema({})


async def async_setup(hass, config) -> bool:
    """Set up the Remora devices."""
    if DOMAIN not in config:
        _LOGGER.error("Unable to find " + DOMAIN + " in configuration")
        return False

    conf = config[DOMAIN]

    host = conf[CONF_HOST]
    remora = RemoraDevice(host)
    hass.data[DOMAIN] = remora
    # The board reboots on its own every few hours and refuses connections for
    # about 30 s: never fail the setup because of it, the entities start as
    # unavailable and recover at the next successful poll.
    if not await remora.async_check_HeartBeat():
        _LOGGER.warning("Remora %s not reachable at startup, entities stay unavailable until it answers", host)
    await remora.async_updateAllFilPilote()
    await remora.async_updateRelais()
    # Optional elements (ie TeleInfo)
    await remora.async_updateTeleInfo()

    async def async_reset(service):
        await hass.data[DOMAIN].async_reset()

    hass.services.async_register(DOMAIN, SERVICE_RESET, async_reset, RESET_SCHEMA)

    return True
