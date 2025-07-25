# __init__.py
"""The AUX AC integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp  # Add this import
from homeassistant.const import Platform

# Updated import name
from .aux_cloud import AuxCloudAPI
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_REGION, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.NUMBER, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AUX AC from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    # Create a shared session for the entry
    session = aiohttp.ClientSession()
    hass.data[DOMAIN][entry.entry_id]["session"] = session

    client = AuxCloudAPI(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        region=entry.data[CONF_REGION],
        session=session,
    )

    try:
        await client.login()
        await client.initialize_websocket()
        await client.refresh()
    except Exception:
        await client.cleanup()
        await session.close()
        _LOGGER.exception("Failed to connect to AUX AC")
        return False

    hass.data[DOMAIN][entry.entry_id]["client"] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    async def handle_set_timer(call):
        """Handle set timer service call."""
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration", 0)
        action = call.data.get("action", "turn_off")
        
        # Find the timer sensor entity
        entity_registry = hass.helpers.entity_registry.async_get(hass)
        entity_entry = entity_registry.async_get(entity_id)
        
        if entity_entry and entity_entry.platform == DOMAIN:
            entity = hass.data.get("entity_components", {}).get("sensor", {}).get(entity_id)
            if hasattr(entity, 'async_set_timer'):
                await entity.async_set_timer(duration, action)
    
    async def handle_cancel_timer(call):
        """Handle cancel timer service call."""
        entity_id = call.data.get("entity_id")
        
        # Find the timer sensor entity
        entity_registry = hass.helpers.entity_registry.async_get(hass)
        entity_entry = entity_registry.async_get(entity_id)
        
        if entity_entry and entity_entry.platform == DOMAIN:
            entity = hass.data.get("entity_components", {}).get("sensor", {}).get(entity_id)
            if hasattr(entity, 'async_cancel_timer'):
                await entity.async_cancel_timer()
    
    hass.services.async_register(DOMAIN, "set_timer", handle_set_timer)
    hass.services.async_register(DOMAIN, "cancel_timer", handle_cancel_timer)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
        client = entry_data.get("client")
        session = entry_data.get("session")

        if client:
            await client.cleanup()
        if session and not session.closed:
            await session.close()

        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
