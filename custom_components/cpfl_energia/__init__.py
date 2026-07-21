# -*- coding: utf-8 -*-
"""The CPFL Energia integration."""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_AUTH_TOKEN,
    CONF_INSTALLATIONS,
    CONF_UPDATED_AT,
    DOMAIN,
)
from .cpfl_client import CPFLClient, CPFLAuthExpired, NotLoggedIn

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CPFL Energia from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Validate session
    client = CPFLClient.load(
        {CONF_AUTH_TOKEN: entry.data[CONF_AUTH_TOKEN]}
    )
    if not await hass.async_add_executor_job(client.verify_login):
        raise ConfigEntryAuthFailed("Login expired")

    hass.data[DOMAIN][entry.entry_id] = {}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading entry: %s", entry.title)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.debug("Unload platforms for entry: %s, success: %s", entry.title, unload_ok)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a device (installation) from the config entry."""
    _LOGGER.info("Removing device %s", device_entry.name)
    installation_num = list(device_entry.identifiers)[0][1]

    # Remove entities
    entity_reg = entity_registry.async_get(hass)
    entities = {
        ent.unique_id: ent.entity_id
        for ent in entity_registry.async_entries_for_config_entry(
            entity_reg, config_entry.entry_id
        )
        if installation_num in ent.unique_id
    }
    for entity_id in entities.values():
        entity_reg.async_remove(entity_id)

    # Update config entry
    new_data = config_entry.data.copy()
    new_data[CONF_INSTALLATIONS].pop(installation_num, None)
    new_data[CONF_UPDATED_AT] = str(int(time.time() * 1000))
    hass.config_entries.async_update_entry(config_entry, data=new_data)
    _LOGGER.info(
        "Removed installation from config: %s", installation_num
    )
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    _LOGGER.info("Removing entry: document %s", entry.data.get("document", "unknown"))
