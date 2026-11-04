"""Base entities and device info shared by the SwissWeather platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SwissPollenDataCoordinator, SwissWeatherDataCoordinator

ATTRIBUTION = "Source: MeteoSwiss"

# Each config entry has up to three service devices; their identifiers are
# "<entry_id>-<kind>" and must stay stable, as the registry keys on them.
DEVICE_FORECAST = "forecast"
DEVICE_WEATHER_STATION = "weather-station"
DEVICE_POLLEN_STATION = "pollen-station"


def device_identifier(entry_id: str, kind: str) -> tuple[str, str]:
    """Return the registry identifier of one of an entry's devices."""
    return (DOMAIN, f"{entry_id}-{kind}")


def build_device_info(entry_id: str, kind: str, name: str | None) -> DeviceInfo:
    """Describe one of an entry's service devices."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        name=name,
        identifiers={device_identifier(entry_id, kind)},
    )


class SwissWeatherEntity(CoordinatorEntity[SwissWeatherDataCoordinator]):
    """Base for entities fed by the forecast and weather station coordinator."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self, coordinator: SwissWeatherDataCoordinator, device_info: DeviceInfo
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info


class SwissWeatherWarningEntity(SwissWeatherEntity):
    """Base for warning entities.

    They report unavailable while the warnings cannot be read, while weather
    and forecast entities stay available: only the warnings part of the
    payload failed, and a failed warning source is not an all-clear.
    """

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.warning_snapshot.available
        )


class SwissPollenEntity(CoordinatorEntity[SwissPollenDataCoordinator]):
    """Base for entities fed by the pollen coordinator."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self, coordinator: SwissPollenDataCoordinator, device_info: DeviceInfo
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
