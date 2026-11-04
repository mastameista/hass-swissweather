"""Coordinates updates for weather data."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
import logging
from datetime import UTC, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
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
    WeatherForecast,
)
from .pollen import (
    CurrentPollen,
    PollenClient,
    PollenConnectionError,
    PollenDataError,
)

_LOGGER = logging.getLogger(__name__)

# A warning still counts as active at exactly validTo, so its end is
# evaluated a moment later.
_WARNING_END_GRACE = timedelta(seconds=1)


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
    upcoming_warnings: list[Warning] = field(default_factory=list)
    next_warning_start: datetime.datetime | None = None
    # False when the warnings could not be read; entities then report
    # unavailable instead of "no warnings".
    available: bool = True


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
    upcoming_warnings = [
        warning for warning in display_warnings if not warning.is_active(now)
    ]

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
        upcoming_warnings=upcoming_warnings,
        available=warnings is not None,
        next_warning_start=min(
            (warning.validFrom for warning in upcoming_warnings if warning.validFrom),
            default=None,
        ),
    )


def next_warning_boundary(
    warnings: list[Warning], now: datetime.datetime
) -> datetime.datetime | None:
    """Return the next moment at which a warning starts or ends, if any."""
    boundaries = []
    for warning in warnings:
        if warning.validFrom is not None and warning.validFrom > now:
            boundaries.append(warning.validFrom)
        if warning.validTo is not None and warning.validTo >= now:
            boundaries.append(warning.validTo + _WARNING_END_GRACE)
    return min(boundaries, default=None)


class WarningAvailabilityMixin:
    """Mark warning entities unavailable while the warnings cannot be read.

    Mix in before CoordinatorEntity. Weather and forecast entities stay
    available, since only the warnings part of the payload failed.
    """

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.warning_snapshot.available
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
            async_get_clientsession(hass), hass.config.language
        )
        update_interval = timedelta(minutes=10)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            always_update=False,
            config_entry=config_entry,
        )
        self._unsub_warning_boundary: CALLBACK_TYPE | None = None

    @callback
    def async_update_listeners(self) -> None:
        """Notify entities, then wait for the next warning start or end."""
        super().async_update_listeners()
        self._schedule_warning_boundary()

    async def async_shutdown(self) -> None:
        """Cancel the warning boundary timer on unload."""
        self._cancel_warning_boundary()
        await super().async_shutdown()

    @callback
    def _cancel_warning_boundary(self) -> None:
        if self._unsub_warning_boundary is not None:
            self._unsub_warning_boundary()
            self._unsub_warning_boundary = None

    @callback
    def _schedule_warning_boundary(self, now: datetime.datetime | None = None) -> None:
        """Re-evaluate warnings when one starts or ends between two polls.

        Polling every 10 minutes alone would switch "active" up to 10 minutes
        late, and could miss a short warning entirely. After a boundary fires,
        its time is passed in so the same boundary is never scheduled again.
        """
        self._cancel_warning_boundary()
        if self.data is None or not self.data.warning_snapshot.available:
            return
        boundary = next_warning_boundary(
            self.data.warning_snapshot.all_warnings,
            now or datetime.datetime.now(UTC),
        )
        if boundary is not None:
            self._unsub_warning_boundary = async_track_point_in_utc_time(
                self.hass, self._handle_warning_boundary, boundary
            )

    @callback
    def _handle_warning_boundary(self, now: datetime.datetime) -> None:
        """Rebuild the warning snapshot for the current time, without a fetch."""
        self._unsub_warning_boundary = None
        if self.data is None:
            return
        self.data = replace(
            self.data,
            warning_snapshot=build_warning_snapshot(
                self.data.warning_snapshot.all_warnings, now
            ),
        )
        super().async_update_listeners()
        self._schedule_warning_boundary(now)

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
                    translation_domain=DOMAIN,
                    translation_key="forecast_missing",
                    translation_placeholders={"forecast_point": self._post_code},
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
                translation_domain=DOMAIN,
                translation_key="forecast_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        except MeteoSwissDataError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="forecast_invalid",
                translation_placeholders={"error": str(err)},
            ) from err
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

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
        self._client = PollenClient(
            async_get_clientsession(hass), hass.config.language
        )
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
            _LOGGER.debug("Loading current pollen state for %s", self._pollen_station_code)
            try:
                current_state = await self._client.async_get_current_pollen_for_station(
                    self._pollen_station_code,
                )
                _LOGGER.debug("Current pollen: %s", current_state)
            except PollenConnectionError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="pollen_unreachable",
                    translation_placeholders={"error": str(err)},
                ) from err
            except PollenDataError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="pollen_invalid",
                    translation_placeholders={"error": str(err)},
                ) from err
            except Exception as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="update_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
        return current_state
