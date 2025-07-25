"""Platform for Tornado AC switch integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
    SwitchDeviceClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from .climate import AuxCloudDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tornado switch platform."""
    # Get the coordinator from the climate platform
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = entry_data.get("coordinator")
    
    if not coordinator:
        _LOGGER.error("No coordinator found for switch setup")
        return

    try:
        devices = await coordinator.api.get_devices()
        entities = []

        for device in devices:
            try:
                entities.append(
                    TornadoSleepModeSwitch(
                        coordinator,
                        device,
                    )
                )
            except Exception:
                _LOGGER.exception(
                    "Error setting up sleep mode switch for device %s", device.get("endpointId")
                )

        async_add_entities(entities)

    except Exception:
        _LOGGER.exception("Error setting up Tornado switch platform")


class TornadoSleepModeSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Tornado AC Sleep Mode switch."""

    def __init__(
        self,
        coordinator: AuxCloudDataUpdateCoordinator,
        device: dict,
    ) -> None:
        """Initialize the sleep mode switch."""
        super().__init__(coordinator)
        self._device_id = device["endpointId"]
        self._attr_unique_id = f"{device['endpointId']}_sleep_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device["endpointId"])},
            "name": f"Tornado AC {device.get('friendlyName')}",
            "manufacturer": "Tornado",
            "model": "AUX Cloud",
        }

        # Set up switch entity attributes
        self.entity_description = SwitchEntityDescription(
            key=self._attr_unique_id,
            name=f"Tornado AC {device.get('friendlyName')} Sleep Mode",
            translation_key=f"{DOMAIN}_sleep_mode",
            device_class=SwitchDeviceClass.SWITCH,
            icon="mdi:sleep",
        )

        self._attr_name = f"Tornado AC {device.get('friendlyName')} Sleep Mode"
        self._attr_is_on = False

        _LOGGER.info("Sleep mode switch initialized for device %s", self._device_id)

    @property
    def _device(self) -> dict | None:
        """Get current device data from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._device_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        _LOGGER.debug(
            "Handling coordinator update for sleep mode switch %s with data: %s",
            self._device_id,
            self._device,
        )

        if not self._device:
            self._attr_available = False
            self.async_write_ha_state()
            return

        try:
            device_params = self._device.get("params", {})
            
            # Update switch state based on sleep mode parameter
            self._attr_is_on = bool(device_params.get("ac_slp", 0))
            self._attr_available = True

            _LOGGER.debug(
                "Updated sleep mode switch state for %s: is_on=%s",
                self._device_id,
                self._attr_is_on,
            )

        except Exception:
            _LOGGER.exception("Error updating sleep mode switch state for %s", self._device_id)
            self._attr_available = False

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on sleep mode."""
        try:
            _LOGGER.info("Turning on sleep mode for device %s", self._device_id)
            await self.coordinator.api.set_device_params(
                self._device, {"ac_slp": 1}
            )
        except Exception:
            _LOGGER.exception(
                "Error turning on sleep mode for device %s",
                self._device_id,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off sleep mode."""
        try:
            _LOGGER.info("Turning off sleep mode for device %s", self._device_id)
            await self.coordinator.api.set_device_params(
                self._device, {"ac_slp": 0}
            )
        except Exception:
            _LOGGER.exception(
                "Error turning off sleep mode for device %s",
                self._device_id,
            )
