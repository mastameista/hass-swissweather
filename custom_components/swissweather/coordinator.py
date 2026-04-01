"""Coordinates updates for weather data."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from datetime import UTC, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FORECAST_POINT_TYPE,
    CONF_POLLEN_STATION_CODE,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    DOMAIN,
)
from .meteo import (
    CurrentWeather,
    MeteoClient,
    MeteoSwissConnectionError,
    MeteoSwissDataError,
    Warning,
    WarningLevel,
    WeatherForecast,
)
from .pollen import (
    CurrentPollen,
    PollenClient,
    PollenConnectionError,
    PollenDataError,
)

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
        self._current_station_unavailable = False
        self._client = MeteoClient(
            async_get_clientsession(hass),
            getattr(getattr(hass, "config", None), "language", None),
        )
        update_interval = timedelta(minutes=10)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
        )

    def _handle_current_station_failure(self, details: str | None = None) -> None:
        """Log current station outages once and degrade to forecast fallback."""
        if self._station_code is None:
            return
        if not self._current_station_unavailable:
            if details:
                _LOGGER.warning(
                    "Current weather state for %s unavailable; using forecast fallback: %s",
                    self._station_code,
                    details,
                )
            else:
                _LOGGER.warning(
                    "Current weather state for %s unavailable; using forecast fallback",
                    self._station_code,
                )
            self._current_station_unavailable = True
            return
        _LOGGER.debug(
            "Current weather state for %s is still unavailable",
            self._station_code,
        )

    def _handle_current_station_recovery(self) -> None:
        """Log when the current station recovers after an outage."""
        if self._station_code is None or not self._current_station_unavailable:
            return
        _LOGGER.info("Current weather state for %s recovered", self._station_code)
        self._current_station_unavailable = False

    async def _async_update_data(self) -> WeatherData:
        current_state: CurrentWeather | None = None
        if self._station_code is None:
            _LOGGER.debug("Station code not set, not loading current state.")
        else:
            _LOGGER.debug("Loading current weather state for %s", self._station_code)
            try:
                current_state = await self._client.async_get_current_weather_for_station(
                    self._station_code
                )
                _LOGGER.debug("Current state: %s", current_state)
                if current_state is None:
                    self._handle_current_station_failure("no station data returned")
                else:
                    self._handle_current_station_recovery()
            except (MeteoSwissConnectionError, MeteoSwissDataError) as err:
                self._handle_current_station_failure(str(err))
                current_state = None
            except Exception as err:
                self._handle_current_station_failure(type(err).__name__)
                current_state = None

        try:
            _LOGGER.debug("Loading current forecast for %s", self._post_code)
            current_forecast = await self._client.async_get_forecast(
                self._post_code,
                self._forecast_point_type,
            )
            if current_forecast is None:
                raise UpdateFailed(
                    f"No forecast data returned for forecast point {self._post_code}"
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
        except MeteoSwissConnectionError as err:
            raise UpdateFailed(
                f"Could not reach MeteoSwiss forecast endpoint: {err}"
            ) from err
        except MeteoSwissDataError as err:
            raise UpdateFailed(
                f"MeteoSwiss returned an invalid forecast payload: {err}"
            ) from err
        except UpdateFailed:
            raise
        except Exception as err:
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
        self._client = PollenClient(async_get_clientsession(hass))
        update_interval = timedelta(minutes=60)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
        )

    async def _async_update_data(self) -> CurrentPollen | None:
        current_state = None
        if self._pollen_station_code is None:
            _LOGGER.debug("Pollen code not set, not loading current state.")
        else:
            _LOGGER.debug("Loading current pollen state for %s", self._pollen_station_code)
            try:
                current_state = await self._client.async_get_current_pollen_for_station(
                    self._pollen_station_code,
                )
                _LOGGER.debug("Current pollen: %s", current_state)
            except PollenConnectionError as err:
                raise UpdateFailed(
                    f"Could not reach MeteoSwiss pollen endpoint: {err}"
                ) from err
            except PollenDataError as err:
                raise UpdateFailed(
                    f"MeteoSwiss returned an invalid pollen payload: {err}"
                ) from err
            except Exception as err:
                raise UpdateFailed(f"Update failed: {err}") from err
        return current_state
