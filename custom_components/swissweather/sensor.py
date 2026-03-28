from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Callable

from propcache.api import cached_property

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_CUBIC_METER,
    DEGREE,
    MATCH_ALL,
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SwissPollenDataCoordinator, SwissWeatherDataCoordinator
from .const import (
    CONF_FORECAST_NAME,
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
    DOMAIN,
)
from .meteo import CurrentWeather, Warning, WarningLevel, WarningType
from .naming import german_slug
from .pollen import CurrentPollen, PollenLevel

_LOGGER = logging.getLogger(__name__)
WIND_DIRECTION_DEVICE_CLASS = getattr(SensorDeviceClass, "WIND_DIRECTION", None)
WIND_DIRECTION_STATE_CLASS = getattr(
    SensorStateClass, "MEASUREMENT_ANGLE", SensorStateClass.MEASUREMENT
)


@dataclass
class SwissWeatherSensorEntry:
    key: str
    translation_key: str
    data_function: Callable[[CurrentWeather], StateType | Decimal]
    native_unit: str
    device_class: SensorDeviceClass
    state_class: SensorStateClass


@dataclass
class SwissPollenSensorEntry:
    key: str
    translation_key: str
    data_function: Callable[[CurrentPollen], StateType | Decimal]
    device_class: SensorDeviceClass | None


def first_or_none(value):
    if value is None or len(value) < 1:
        return None
    return value[0]


SENSORS: list[SwissWeatherSensorEntry] = [
    SwissWeatherSensorEntry("time", "time", lambda weather: weather.date, None, SensorDeviceClass.TIMESTAMP, None),
    SwissWeatherSensorEntry("temperature", "temperature", lambda weather: first_or_none(weather.airTemperature), UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("precipitation", "precipitation", lambda weather: first_or_none(weather.precipitation), UnitOfPrecipitationDepth.MILLIMETERS, SensorDeviceClass.PRECIPITATION, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("sunshine", "sunshine", lambda weather: first_or_none(weather.sunshine), UnitOfTime.MINUTES, SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("global_radiation", "global_radiation", lambda weather: first_or_none(weather.globalRadiation), UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorDeviceClass.IRRADIANCE, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("humidity", "humidity", lambda weather: first_or_none(weather.relativeHumidity), PERCENTAGE, SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("dew_point", "dew_point", lambda weather: first_or_none(weather.dewPoint), UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("wind_direction", "wind_direction", lambda weather: first_or_none(weather.windDirection), DEGREE, WIND_DIRECTION_DEVICE_CLASS, WIND_DIRECTION_STATE_CLASS),
    SwissWeatherSensorEntry("wind_speed", "wind_speed", lambda weather: first_or_none(weather.windSpeed), UnitOfSpeed.KILOMETERS_PER_HOUR, SensorDeviceClass.WIND_SPEED, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("gust_peak1s", "gust_peak1s", lambda weather: first_or_none(weather.gustPeak1s), UnitOfSpeed.KILOMETERS_PER_HOUR, SensorDeviceClass.WIND_SPEED, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("pressure", "pressure", lambda weather: first_or_none(weather.pressureStationLevel), UnitOfPressure.HPA, SensorDeviceClass.ATMOSPHERIC_PRESSURE, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("pressure_qff", "pressure_qff", lambda weather: first_or_none(weather.pressureSeaLevel), UnitOfPressure.HPA, SensorDeviceClass.ATMOSPHERIC_PRESSURE, SensorStateClass.MEASUREMENT),
    SwissWeatherSensorEntry("pressure_qnh", "pressure_qnh", lambda weather: first_or_none(weather.pressureSeaLevelAtStandardAtmosphere), UnitOfPressure.HPA, SensorDeviceClass.ATMOSPHERIC_PRESSURE, SensorStateClass.MEASUREMENT),
]

POLLEN_SENSORS: list[SwissPollenSensorEntry] = [
    SwissPollenSensorEntry("pollen-time", "pollen_time", lambda pollen: pollen.timestamp, SensorDeviceClass.TIMESTAMP),
    SwissPollenSensorEntry("birch", "birch", lambda pollen: first_or_none(pollen.birch), None),
    SwissPollenSensorEntry("grasses", "grasses", lambda pollen: first_or_none(pollen.grasses), None),
    SwissPollenSensorEntry("alder", "alder", lambda pollen: first_or_none(pollen.alder), None),
    SwissPollenSensorEntry("hazel", "hazel", lambda pollen: first_or_none(pollen.hazel), None),
    SwissPollenSensorEntry("beech", "beech", lambda pollen: first_or_none(pollen.beech), None),
    SwissPollenSensorEntry("ash", "ash", lambda pollen: first_or_none(pollen.ash), None),
    SwissPollenSensorEntry("oak", "oak", lambda pollen: first_or_none(pollen.oak), None),
]

WARNING_SLOT_LABELS = ("primary", "secondary", "tertiary")
EMPTY_WARNING_STATE = "none"
WARNING_TYPE_ICONS: dict[WarningType, str] = {
    WarningType.WIND: "mdi:weather-windy",
    WarningType.THUNDERSTORMS: "mdi:weather-lightning-rainy",
    WarningType.RAIN: "mdi:weather-pouring",
    WarningType.SNOW: "mdi:snowflake",
    WarningType.SLIPPERY_ROADS: "mdi:car-brake-alert",
    WarningType.FROST: "mdi:snowflake-thermometer",
    WarningType.THAW: "mdi:thermometer-high",
    WarningType.HEAT_WAVES: "mdi:thermometer-high",
    WarningType.AVALANCHES: "mdi:snowflake-alert",
    WarningType.EARTHQUAKES: "mdi:pulse",
    WarningType.FOREST_FIRES: "mdi:fire-alert",
    WarningType.FLOOD: "mdi:waves-arrow-up",
    WarningType.DROUGHT: "mdi:water-off",
    WarningType.UNKNOWN: "mdi:alert",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = config_entry.runtime_data
    coordinator: SwissWeatherDataCoordinator = runtime_data.weather_coordinator
    postCode: str = config_entry.data[CONF_POST_CODE]
    stationCode: str = config_entry.data.get(CONF_STATION_CODE)
    pollenStationCode: str = config_entry.data.get(CONF_POLLEN_STATION_CODE)
    warnings_enabled: bool = bool(config_entry.data.get(CONF_WARNINGS_ENABLED, True))
    forecast_name: str = config_entry.data.get(CONF_FORECAST_NAME, postCode)
    weather_station_name: str = config_entry.data.get(
        CONF_STATION_NAME, stationCode or postCode
    )
    pollen_station_name: str = config_entry.data.get(
        CONF_POLLEN_STATION_NAME, pollenStationCode
    )

    forecast_device = DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        name=forecast_name,
        identifiers={(DOMAIN, f"{config_entry.entry_id}-forecast")},
    )
    weather_device = DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        name=weather_station_name,
        identifiers={(DOMAIN, f"{config_entry.entry_id}-weather-station")},
    )
    entities: list[SensorEntity] = [
        SwissWeatherSensor(
            postCode, weather_station_name, weather_device, sensorEntry, coordinator
        )
        for sensorEntry in SENSORS
    ]

    if pollenStationCode is not None:
        pollenCoordinator = runtime_data.pollen_coordinator
        pollen_device = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            name=pollen_station_name,
            identifiers={(DOMAIN, f"{config_entry.entry_id}-pollen-station")},
        )
        entities += [
            SwissPollenSensor(
                postCode,
                pollen_station_name,
                pollen_device,
                sensorEntry,
                pollenCoordinator,
            )
            for sensorEntry in POLLEN_SENSORS
        ]
        entities += [
            SwissPollenLevelSensor(
                postCode,
                pollen_station_name,
                pollen_device,
                sensorEntry,
                pollenCoordinator,
            )
            for sensorEntry in POLLEN_SENSORS
            if sensorEntry.device_class is None
        ]

    if warnings_enabled:
        entities.extend(
            [
                SwissWeatherWarningCountSensor(
                    postCode, forecast_name, forecast_device, coordinator
                ),
                SwissWeatherHighestWarningLevelSensor(
                    postCode, forecast_name, forecast_device, coordinator
                ),
                *[
                    SwissWeatherWarningSlotSensor(
                        postCode,
                        forecast_name,
                        slot_index,
                        forecast_device,
                        coordinator,
                    )
                    for slot_index in range(len(WARNING_SLOT_LABELS))
                ],
            ]
        )

    async_add_entities(entities)


class SwissWeatherSensor(CoordinatorEntity[SwissWeatherDataCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        station_name: str,
        device_info: DeviceInfo,
        sensor_entry: SwissWeatherSensorEntry,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key=sensor_entry.key,
            translation_key=sensor_entry.translation_key,
            native_unit_of_measurement=sensor_entry.native_unit,
            device_class=sensor_entry.device_class,
            state_class=sensor_entry.state_class,
        )
        self._sensor_entry = sensor_entry
        self._attr_unique_id = f"{post_code}.{sensor_entry.key}"
        self._attr_suggested_object_id = (
            f"{german_slug(sensor_entry.key)}_{german_slug(station_name)}"
        )
        self._attr_device_info = device_info
        self._attr_attribution = "Source: MeteoSwiss"

    @property
    def native_value(self) -> StateType | Decimal:
        if self.coordinator.data is None or self.coordinator.data.current_weather is None:
            return None
        return self._sensor_entry.data_function(self.coordinator.data.current_weather)


def get_color_for_warning_level(level: int | None) -> str:
    """Return a MeteoSwiss-like icon color for the corresponding warning level."""
    if level is None or level <= 0:
        return "gray"
    if level == 1:
        return "green"
    if level == 2:
        return "yellow"
    if level == 3:
        return "orange"
    if level == 4:
        return "red"
    return "#B71C1C"


def get_icon_for_warning(warning: Warning | None) -> str:
    """Return the icon for a warning type."""
    if warning is None:
        return "mdi:alert-outline"
    return WARNING_TYPE_ICONS.get(warning.warningType, "mdi:alert")


class SwissWeatherWarningCountSensor(
    CoordinatorEntity[SwissWeatherDataCoordinator], SensorEntity
):
    """Show the number of displayable weather warnings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key="warning_count",
            translation_key="warning_count",
            state_class=SensorStateClass.MEASUREMENT,
        )
        self._attr_unique_id = f"{post_code}.warning_count"
        self._attr_suggested_object_id = (
            f"weather_warning_count_{german_slug(forecast_name)}"
        )
        self._attr_device_info = device_info
        self._attr_attribution = "Source: MeteoSwiss"
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> StateType | Decimal:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.warning_snapshot.count

    @cached_property
    def icon(self):
        return "mdi:alert-badge-outline"


class SwissWeatherHighestWarningLevelSensor(
    CoordinatorEntity[SwissWeatherDataCoordinator], SensorEntity
):
    """Show the highest weather warning level."""

    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key="highest_warning_level",
            translation_key="highest_warning_level",
        )
        self._attr_unique_id = f"{post_code}.highest_warning_level"
        self._attr_suggested_object_id = (
            f"highest_weather_warning_level_{german_slug(forecast_name)}"
        )
        self._attr_device_info = device_info
        self._attr_attribution = "Source: MeteoSwiss"
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> StateType | Decimal:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.warning_snapshot.highest_level

    @property
    def extra_state_attributes(self) -> dict[str, StateType] | None:
        if self.coordinator.data is None:
            return None
        highest_level = self.coordinator.data.warning_snapshot.highest_level
        if highest_level is None:
            return None
        level_name = (
            WarningLevel(highest_level).name.replace("_", " ").capitalize()
            if highest_level in set(item.value for item in WarningLevel)
            else f"Level {highest_level}"
        )
        return {
            "level_name": level_name,
            "icon_color": get_color_for_warning_level(highest_level),
        }

    @cached_property
    def icon(self):
        return "mdi:alert-octagram-outline"


class SwissWeatherWarningSlotSensor(
    CoordinatorEntity[SwissWeatherDataCoordinator], SensorEntity
):
    """Expose the prioritized primary/secondary/tertiary warnings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        forecast_name: str,
        slot_index: int,
        device_info: DeviceInfo,
        coordinator: SwissWeatherDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        slot_label = WARNING_SLOT_LABELS[slot_index]
        self._slot_index = slot_index
        self._slot_label = slot_label
        self.entity_description = SensorEntityDescription(
            key=f"{slot_label}_warning",
            translation_key=f"{slot_label}_warning",
        )
        self._attr_unique_id = f"{post_code}.{slot_label}_warning"
        self._attr_suggested_object_id = (
            f"{slot_label}_weather_warning_{german_slug(forecast_name)}"
        )
        self._attr_device_info = device_info
        self._attr_attribution = "Source: MeteoSwiss"
        self._entity_component_unrecorded_attributes = MATCH_ALL

    def _warning(self) -> Warning | None:
        if self.coordinator.data is None:
            return None
        return {
            0: self.coordinator.data.warning_snapshot.primary,
            1: self.coordinator.data.warning_snapshot.secondary,
            2: self.coordinator.data.warning_snapshot.tertiary,
        }[self._slot_index]

    @property
    def native_value(self) -> StateType | Decimal:
        warning = self._warning()
        if warning is None:
            return EMPTY_WARNING_STATE
        return warning.type_state

    @property
    def extra_state_attributes(self) -> dict[str, StateType] | None:
        warning = self._warning()
        if warning is None:
            attributes: dict[str, StateType] = {
                "rank": self._slot_index + 1,
                "warning_type": None,
                "warning_type_raw": None,
                "warning_level": None,
                "warning_level_raw": None,
                "level_name": None,
                "valid_from": None,
                "valid_to": None,
                "outlook": None,
                "text": None,
                "html_text": None,
                "links": [],
                "fingerprint": None,
                "icon_color": get_color_for_warning_level(None),
                "has_warning": False,
            }
            if self._slot_index == 0 and self.coordinator.data is not None:
                attributes["additional_warning_count"] = max(
                    self.coordinator.data.warning_snapshot.count - 1, 0
                )
            return attributes

        attributes: dict[str, StateType] = {
            "warning_type": warning.type_name,
            "warning_type_raw": warning.raw_type,
            "warning_level": warning.effective_level,
            "warning_level_raw": warning.raw_level,
            "level_name": warning.level_name,
            "valid_from": warning.validFrom,
            "valid_to": warning.validTo,
            "outlook": warning.outlook,
            "text": warning.text,
            "html_text": warning.htmlText,
            "links": [link.as_dict() for link in warning.links],
            "fingerprint": warning.fingerprint,
            "rank": self._slot_index + 1,
            "icon_color": get_color_for_warning_level(warning.effective_level),
            "has_warning": True,
        }
        if self._slot_index == 0 and self.coordinator.data is not None:
            attributes["additional_warning_count"] = max(
                self.coordinator.data.warning_snapshot.count - 1, 0
            )
        return attributes

    @property
    def icon(self):
        return get_icon_for_warning(self._warning())


class SwissPollenSensor(CoordinatorEntity[SwissPollenDataCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        station_name: str,
        device_info: DeviceInfo,
        sensor_entry: SwissPollenSensorEntry,
        coordinator: SwissPollenDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        state_class = SensorStateClass.MEASUREMENT
        unit = CONCENTRATION_PARTS_PER_CUBIC_METER
        if sensor_entry.device_class is SensorDeviceClass.TIMESTAMP:
            state_class = None
            unit = None
        self.entity_description = SensorEntityDescription(
            key=sensor_entry.key,
            translation_key=sensor_entry.translation_key,
            native_unit_of_measurement=unit,
            state_class=state_class,
        )
        self._sensor_entry = sensor_entry
        self._attr_unique_id = f"pollen-{post_code}.{sensor_entry.key}"
        self._attr_suggested_object_id = (
            f"{german_slug(sensor_entry.key)}_{german_slug(station_name)}"
        )
        self._attr_device_info = device_info
        self._attr_device_class = sensor_entry.device_class
        self._attr_suggested_display_precision = 0
        self._attr_attribution = "Source: MeteoSwiss"

    @property
    def native_value(self) -> StateType | Decimal:
        if self.coordinator.data is None:
            return None
        return self._sensor_entry.data_function(self.coordinator.data)

    @cached_property
    def icon(self):
        return "mdi:flower-pollen"


def get_color_for_pollen_level(level: int) -> str:
    """Return the icon color for the corresponding pollen level."""
    if level is not None:
        if level <= 10:
            return "gray"
        if level <= 70:
            return "amber"
        if level <= 250:
            return "red"
    return "gray"


class SwissPollenLevelSensor(CoordinatorEntity[SwissPollenDataCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        post_code: str,
        station_name: str,
        device_info: DeviceInfo,
        sensor_entry: SwissPollenSensorEntry,
        coordinator: SwissPollenDataCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(
            key=f"{sensor_entry.key}_level",
            translation_key=f"{sensor_entry.translation_key}_level",
            device_class=SensorDeviceClass.ENUM,
        )
        self._sensor_entry = sensor_entry
        self._attr_unique_id = f"pollen-level-{post_code}.{sensor_entry.key}"
        self._attr_suggested_object_id = (
            f"{german_slug(sensor_entry.key)}_level_{german_slug(station_name)}"
        )
        self._attr_device_info = device_info
        self._attr_options = [
            PollenLevel.NONE,
            PollenLevel.LOW,
            PollenLevel.MEDIUM,
            PollenLevel.STRONG,
            PollenLevel.VERY_STRONG,
        ]
        self._attr_attribution = "Source: MeteoSwiss"
        self._entity_component_unrecorded_attributes = MATCH_ALL

    @property
    def native_value(self) -> StateType | Decimal:
        if self.coordinator.data is None:
            return None
        value = self._sensor_entry.data_function(self.coordinator.data)
        if value is not None:
            if value == 0:
                return PollenLevel.NONE
            if value <= 10:
                return PollenLevel.LOW
            if value <= 70:
                return PollenLevel.MEDIUM
            if value <= 250:
                return PollenLevel.STRONG
            return PollenLevel.VERY_STRONG
        return None

    @property
    def extra_state_attributes(self) -> dict[str, any] | None:
        """Return additional state attributes."""
        if self.coordinator.data is None:
            return None
        value = self._sensor_entry.data_function(self.coordinator.data)
        return {"icon_color": get_color_for_pollen_level(value)}

    @cached_property
    def icon(self):
        return "mdi:flower-pollen-outline"
