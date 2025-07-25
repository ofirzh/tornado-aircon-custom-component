"""Platform for Tornado AC number integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberDeviceClass,
    NumberMode,
)
from homeassistant.const import UnitOfTime
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
    """Set up Tornado number platform."""
    # Get the coordinator from the climate platform
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = entry_data.get("coordinator")
    
    if not coordinator:
        _LOGGER.error("No coordinator found for number setup")
        return

    try:
        devices = await coordinator.api.get_devices()
        entities = []

        for device in devices:
            try:
                entities.append(
                    TornadoTimerNumber(
                        coordinator,
                        device,
                    )
                )
            except Exception:
                _LOGGER.exception(
                    "Error setting up timer number for device %s", device.get("endpointId")
                )

        async_add_entities(entities)

    except Exception:
        _LOGGER.exception("Error setting up Tornado number platform")


class TornadoTimerNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Tornado AC Timer duration number entity."""

    def __init__(
        self,
        coordinator: AuxCloudDataUpdateCoordinator,
        device: dict,
    ) -> None:
        """Initialize the timer number entity."""
        super().__init__(coordinator)
        self._device_id = device["endpointId"]
        self._attr_unique_id = f"{device['endpointId']}_timer_duration"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device["endpointId"])},
            "name": f"Tornado AC {device.get('friendlyName')}",
            "manufacturer": "Tornado",
            "model": "AUX Cloud",
        }

        # Set up number entity attributes
        self.entity_description = NumberEntityDescription(
            key=self._attr_unique_id,
            name=f"Tornado AC {device.get('friendlyName')} Timer Duration",
            translation_key=f"{DOMAIN}_timer_duration",
            device_class=NumberDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-settings-outline",
            mode=NumberMode.BOX,
        )

        self._attr_name = f"Tornado AC {device.get('friendlyName')} Timer Duration"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 480  # 8 hours max
        self._attr_native_step = 1
        self._attr_native_value = 0

        _LOGGER.info("Timer number entity initialized for device %s", self._device_id)

    @property
    def _device(self) -> dict | None:
        """Get current device data from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._device_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if not self._device:
            self._attr_available = False
        else:
            self._attr_available = True
        
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the timer duration."""
        try:
            duration_minutes = int(value)
            _LOGGER.info(
                "Setting timer duration to %d minutes for device %s",
                duration_minutes,
                self._device_id,
            )

            # Call the service to set the timer with default "turn_off" action
            await self.hass.services.async_call(
                DOMAIN,
                "set_timer",
                {
                    "entity_id": f"sensor.tornado_{self._device_id}_timer",
                    "duration": duration_minutes,
                    "action": "turn_off"  # Default action
                }
            )

            self._attr_native_value = value
            self.async_write_ha_state()
            
        except Exception:
            _LOGGER.exception(
                "Error setting timer duration for device %s",
                self._device_id,
            )
