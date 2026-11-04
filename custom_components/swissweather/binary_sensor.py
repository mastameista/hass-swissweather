from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SwissWeatherDataCoordinator
from .coordinator import WarningAvailabilityMixin
from .entity import DEVICE_FORECAST, SwissWeatherEntity, build_device_info
from .const import CONF_FORECAST_NAME, CONF_POST_CODE, CONF_WARNINGS_ENABLED

# Entities only read coordinator data; the coordinators batch all fetches.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up warning binary sensors."""
    if not config_entry.data.get(CONF_WARNINGS_ENABLED, True):
        return

    coordinator: SwissWeatherDataCoordinator = config_entry.runtime_data.weather_coordinator
    post_code: str = config_entry.data[CONF_POST_CODE]
    forecast_name: str = config_entry.data.get(CONF_FORECAST_NAME, post_code)
    forecast_device = build_device_info(
        config_entry.entry_id, DEVICE_FORECAST, forecast_name
    )
    async_add_entities(
        [
            SwissWeatherHasWarningsBinarySensor(
                post_code, forecast_name, forecast_device, coordinator
            ),
            SwissWeatherHasActiveWarningsBinarySensor(
                post_code, forecast_name, forecast_device, coordinator
            ),
        ]
    )


class SwissWeatherHasWarningsBinarySensor(
    WarningAvailabilityMixin,
    SwissWeatherEntity,
    BinarySensorEntity,
):
    """Expose whether the selected forecast place currently has warnings."""


    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator, device_info)
        self._attr_translation_key = "has_warnings"
        self._attr_unique_id = f"{post_code}.has_warnings"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.warning_snapshot.count > 0


class SwissWeatherHasActiveWarningsBinarySensor(
    WarningAvailabilityMixin,
    SwissWeatherEntity,
    BinarySensorEntity,
):
    """Expose whether a warning is in force right now, ignoring announced ones."""


    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator, device_info)
        self._attr_translation_key = "has_active_warnings"
        self._attr_unique_id = f"{post_code}.has_active_warnings"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return len(self.coordinator.data.warning_snapshot.active_warnings) > 0
