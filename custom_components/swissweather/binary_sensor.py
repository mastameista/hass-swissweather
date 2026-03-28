from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SwissWeatherDataCoordinator
from .const import CONF_FORECAST_NAME, CONF_POST_CODE, CONF_WARNINGS_ENABLED, DOMAIN
from .naming import german_slug


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
    forecast_device = DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        name=forecast_name,
        identifiers={(DOMAIN, f"{config_entry.entry_id}-forecast")},
    )
    async_add_entities(
        [
            SwissWeatherHasWarningsBinarySensor(
                post_code, forecast_name, forecast_device, coordinator
            )
        ]
    )


class SwissWeatherHasWarningsBinarySensor(
    CoordinatorEntity[SwissWeatherDataCoordinator], BinarySensorEntity
):
    """Expose whether the selected forecast place currently has warnings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = "has_warnings"
        self._attr_unique_id = f"{post_code}.has_warnings"
        self._attr_suggested_object_id = (
            f"has_weather_warnings_{german_slug(forecast_name)}"
        )
        self._attr_device_info = device_info
        self._attr_attribution = "Source: MeteoSwiss"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.warning_snapshot.count > 0

    @property
    def icon(self) -> str:
        return "mdi:alert-outline"
