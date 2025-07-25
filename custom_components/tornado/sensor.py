"""Platform for Tornado AC sensor integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.event import async_track_time_interval

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
    """Set up Tornado sensor platform."""
    # Get the coordinator from the climate platform
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = entry_data.get("coordinator")
    
    if not coordinator:
        _LOGGER.error("No coordinator found for sensor setup")
        return

    try:
        devices = await coordinator.api.get_devices()
        entities = []

        for device in devices:
            try:
                entities.append(
                    TornadoTimerSensor(
                        coordinator,
                        device,
                    )
                )
            except Exception:
                _LOGGER.exception(
                    "Error setting up timer sensor for device %s", device.get("endpointId")
                )

        async_add_entities(entities)

    except Exception:
        _LOGGER.exception("Error setting up Tornado sensor platform")


class TornadoTimerSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tornado AC Timer sensor."""

    def __init__(
        self,
        coordinator: AuxCloudDataUpdateCoordinator,
        device: dict,
    ) -> None:
        """Initialize the timer sensor."""
        super().__init__(coordinator)
        self._device_id = device["endpointId"]
        self._attr_unique_id = f"{device['endpointId']}_timer"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device["endpointId"])},
            "name": f"Tornado AC {device.get('friendlyName')}",
            "manufacturer": "Tornado",
            "model": "AUX Cloud",
        }

        # Set up sensor attributes
        self.entity_description = SensorEntityDescription(
            key=self._attr_unique_id,
            name=f"Tornado AC {device.get('friendlyName')} Timer",
            translation_key=f"{DOMAIN}_timer",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-outline",
        )

        self._attr_name = f"Tornado AC {device.get('friendlyName')} Timer"
        self._timer_start_time = None
        self._timer_duration = None
        self._timer_end_time = None
        self._target_action = "turn_off"  # Default action when timer expires
        self._update_timer_handle = None
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {
            "timer_active": False,
            "timer_duration": None,
            "timer_start_time": None,
            "timer_end_time": None,
            "target_action": "turn_off",  # What to do when timer expires
            "sleep_mode_active": False,
        }

        _LOGGER.info("Timer sensor initialized for device %s", self._device_id)

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
            "Handling coordinator update for timer sensor %s with data: %s",
            self._device_id,
            self._device,
        )

        if not self._device:
            self._attr_available = False
            self.async_write_ha_state()
            return

        try:
            device_params = self._device.get("params", {})
            
            # Check if sleep mode is active (this is separate from timer)
            sleep_mode_active = bool(device_params.get("ac_slp", 0))
            
            # Update sleep mode attribute (independent of timer)
            self._attr_extra_state_attributes.update({
                "sleep_mode_active": sleep_mode_active,
            })

            # Update timer state
            self._update_timer_state()

            self._attr_available = True

            _LOGGER.debug(
                "Updated timer sensor state for %s: value=%s, sleep_active=%s",
                self._device_id,
                self._attr_native_value,
                sleep_mode_active,
            )

        except Exception:
            _LOGGER.exception("Error updating timer sensor state for %s", self._device_id)
            self._attr_available = False

        self.async_write_ha_state()

    @callback
    def _update_timer_state(self) -> None:
        """Update the timer state and check if it has expired."""
        if self._timer_end_time is None:
            # No active timer
            self._attr_native_value = 0
            self._attr_extra_state_attributes.update({
                "timer_active": False,
                "timer_duration": None,
                "timer_start_time": None,
                "timer_end_time": None,
            })
            return

        now = datetime.now()
        if now >= self._timer_end_time:
            # Timer has expired
            _LOGGER.info("Timer expired for device %s, executing action: %s", 
                        self._device_id, self._target_action)
            
            # Execute the target action
            self.hass.async_create_task(self._execute_timer_action())
            
            # Clear timer
            self._timer_start_time = None
            self._timer_duration = None
            self._timer_end_time = None
            self._attr_native_value = 0
            self._attr_extra_state_attributes.update({
                "timer_active": False,
                "timer_duration": None,
                "timer_start_time": None,
                "timer_end_time": None,
            })
            
            # Cancel the update timer
            if self._update_timer_handle:
                self._update_timer_handle()
                self._update_timer_handle = None
        else:
            # Timer is still active, calculate remaining time
            remaining = (self._timer_end_time - now).total_seconds() / 60
            self._attr_native_value = max(0, int(remaining))
            self._attr_extra_state_attributes.update({
                "timer_active": True,
                "timer_duration": self._timer_duration,
                "timer_start_time": self._timer_start_time.isoformat() if self._timer_start_time else None,
                "timer_end_time": self._timer_end_time.isoformat(),
            })

    async def _execute_timer_action(self) -> None:
        """Execute the action when timer expires."""
        try:
            if self._target_action == "turn_off":
                # Turn off the AC
                await self.coordinator.api.set_device_params(
                    self._device, {"pwr": 0}
                )
                _LOGGER.info("Timer expired: turned off AC %s", self._device_id)
            elif self._target_action == "sleep_mode":
                # Enable sleep mode
                await self.coordinator.api.set_device_params(
                    self._device, {"ac_slp": 1}
                )
                _LOGGER.info("Timer expired: enabled sleep mode for AC %s", self._device_id)
            # Add more actions as needed
            
        except Exception:
            _LOGGER.exception("Error executing timer action for device %s", self._device_id)

    async def async_set_timer(self, duration_minutes: int, action: str = "turn_off") -> None:
        """Set a timer for the specified duration with specified action."""
        try:
            _LOGGER.info(
                "Setting timer for %d minutes on device %s with action: %s",
                duration_minutes,
                self._device_id,
                action,
            )
            
            # Cancel existing timer
            await self.async_cancel_timer()
            
            if duration_minutes <= 0:
                # Just cancel the timer (already done above)
                return
            
            # Set new timer
            self._timer_start_time = datetime.now()
            self._timer_duration = duration_minutes
            self._timer_end_time = self._timer_start_time + timedelta(minutes=duration_minutes)
            self._target_action = action
            
            # Set up periodic updates every minute
            self._update_timer_handle = async_track_time_interval(
                self.hass, 
                self._periodic_timer_update,
                timedelta(minutes=1)
            )
            
            # Update state immediately
            self._update_timer_state()
            self.async_write_ha_state()
            
        except Exception:
            _LOGGER.exception(
                "Error setting timer for device %s",
                self._device_id,
            )

    @callback
    def _periodic_timer_update(self, now) -> None:
        """Periodic timer update callback."""
        self._update_timer_state()
        self.async_write_ha_state()

    async def async_cancel_timer(self) -> None:
        """Cancel the active timer."""
        try:
            _LOGGER.info("Cancelling timer for device %s", self._device_id)
            
            # Cancel the periodic update
            if self._update_timer_handle:
                self._update_timer_handle()
                self._update_timer_handle = None
            
            # Clear timer state
            self._timer_start_time = None
            self._timer_duration = None
            self._timer_end_time = None
            
            # Update state immediately
            self._update_timer_state()
            self.async_write_ha_state()
            
        except Exception:
            _LOGGER.exception(
                "Error cancelling timer for device %s",
                self._device_id,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._update_timer_handle:
            self._update_timer_handle()
            self._update_timer_handle = None
