"""Coordinates updates for weather data."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from datetime import UTC, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FORECAST_POINT_TYPE,
    CONF_POLLEN_STATION_CODE,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    DOMAIN,
)
from .meteo import CurrentWeather, MeteoClient, Warning, WarningLevel, WeatherForecast
from .pollen import CurrentPollen, PollenClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class WarningSnapshot:
    """Prepared warning view for all warning-related entities."""

    all_warnings: list[Warning]
    active_warnings: list[Warning]
    sorted_warnings: list[Warning]
    primary: Warning | None
    secondary: Warning | None
    tertiary: Warning | None
    count: int
    highest_level: int | None


@dataclass
class WeatherData:
    """Combined weather data shared by sensor and weather entities."""

    current_weather: CurrentWeather | None
    forecast: WeatherForecast | None
    warning_snapshot: WarningSnapshot


def build_warning_snapshot(
    warnings: list[Warning] | None,
    now: datetime.datetime | None = None,
) -> WarningSnapshot:
    """Build a stable presentation snapshot from MeteoSwiss warnings."""
    now = now or datetime.datetime.now(UTC)
    all_warnings = list(warnings or [])
    active_warnings = [warning for warning in all_warnings if warning.is_active(now)]
    display_warnings = [warning for warning in all_warnings if not warning.is_expired(now)]

    sorted_warnings = sorted(
        display_warnings,
        key=lambda warning: (
            -warning.effective_level,
            0 if warning.is_active(now) else 1,
            0 if not warning.outlook else 1,
            warning.validFrom or datetime.datetime.max.replace(tzinfo=UTC),
            warning.ordering or "",
            warning.fingerprint,
        ),
    )

    highest_level = (
        max((warning.effective_level for warning in sorted_warnings), default=None)
        if sorted_warnings
        else None
    )
    return WarningSnapshot(
        all_warnings=all_warnings,
        active_warnings=active_warnings,
        sorted_warnings=sorted_warnings,
        primary=sorted_warnings[0] if len(sorted_warnings) > 0 else None,
        secondary=sorted_warnings[1] if len(sorted_warnings) > 1 else None,
        tertiary=sorted_warnings[2] if len(sorted_warnings) > 2 else None,
        count=len(sorted_warnings),
        highest_level=highest_level,
    )


class SwissWeatherDataCoordinator(DataUpdateCoordinator[WeatherData]):
    """Coordinates data loads for all weather entities."""

    _client: MeteoClient

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._station_code = config_entry.data.get(CONF_STATION_CODE)
        self._post_code = config_entry.data[CONF_POST_CODE]
        self._forecast_point_type = config_entry.data.get(CONF_FORECAST_POINT_TYPE)
        self._client = MeteoClient()
        update_interval = timedelta(minutes=10)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> WeatherData:
        current_state: CurrentWeather | None = None
        if self._station_code is None:
            _LOGGER.warning("Station code not set, not loading current state.")
        else:
            _LOGGER.info("Loading current weather state for %s", self._station_code)
            try:
                current_state = await self.hass.async_add_executor_job(
                    self._client.get_current_weather_for_station, self._station_code
                )
                _LOGGER.debug("Current state: %s", current_state)
            except Exception as err:
                _LOGGER.exception(err)
                current_state = None

        try:
            _LOGGER.info("Loading current forecast for %s", self._post_code)
            current_forecast = await self.hass.async_add_executor_job(
                self._client.get_forecast,
                self._post_code,
                self._forecast_point_type,
            )
            _LOGGER.debug("Current forecast: %s", current_forecast)
            if current_state is None and current_forecast is not None:
                current = current_forecast.current
                if current is not None:
                    current_state = CurrentWeather(
                        None,
                        datetime.datetime.now(tz=datetime.UTC),
                        current.currentTemperature,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
            snapshot = build_warning_snapshot(
                None if current_forecast is None else current_forecast.warnings
            )
        except Exception as err:
            _LOGGER.exception(err)
            raise UpdateFailed(f"Update failed: {err}") from err

        return WeatherData(
            current_weather=current_state,
            forecast=current_forecast,
            warning_snapshot=snapshot,
        )


class SwissPollenDataCoordinator(DataUpdateCoordinator[CurrentPollen | None]):
    """Coordinates loading of pollen data."""

    _client: PollenClient

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._pollen_station_code = config_entry.data.get(CONF_POLLEN_STATION_CODE)
        self._client = PollenClient()
        update_interval = timedelta(minutes=60)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> CurrentPollen | None:
        current_state = None
        if self._pollen_station_code is None:
            _LOGGER.debug("Pollen code not set, not loading current state.")
        else:
            _LOGGER.info("Loading current pollen state for %s", self._pollen_station_code)
            try:
                current_state = await self.hass.async_add_executor_job(
                    self._client.get_current_pollen_for_station,
                    self._pollen_station_code,
                )
                _LOGGER.debug("Current pollen: %s", current_state)
            except Exception as err:
                _LOGGER.exception(err)
                raise UpdateFailed(f"Update failed: {err}") from err
        return current_state
