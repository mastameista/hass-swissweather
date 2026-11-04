"""Weather entity behaviour without data and without a weather station."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings.const import CONF_POST_CODE
from custom_components.meteoswiss_forecast_warnings.coordinator import WeatherData, build_warning_snapshot
from custom_components.meteoswiss_forecast_warnings.meteo import CurrentState, WeatherForecast
from custom_components.meteoswiss_forecast_warnings.weather import SwissWeather

ENTRY = SimpleNamespace(entry_id="entry-1", data={CONF_POST_CODE: "800100"})


def _entity(data) -> SwissWeather:
    return SwissWeather(SimpleNamespace(data=data), "Zürich", ENTRY)


def _forecast(**overrides) -> WeatherForecast:
    values = {
        "current": CurrentState((7.5, "°C"), 1, "sunny"),
        "dailyForecast": None,
        "hourlyForecast": None,
        "sunrises": None,
        "sunsets": None,
        "warnings": [],
    }
    values.update(overrides)
    return WeatherForecast(**values)


def _data(current_weather=None, forecast=None) -> WeatherData:
    return WeatherData(
        current_weather=current_weather,
        forecast=forecast,
        warning_snapshot=build_warning_snapshot([], now=datetime(2026, 11, 4, tzinfo=UTC)),
    )


def test_no_data_yet_reports_nothing():
    entity = _entity(None)

    assert entity.condition is None
    assert entity.native_temperature is None
    assert entity.native_wind_speed is None
    assert entity.humidity is None
    assert entity.wind_bearing is None
    assert entity.native_pressure is None
    assert asyncio.run(entity.async_forecast_daily()) is None
    assert asyncio.run(entity.async_forecast_hourly()) is None


def test_without_a_station_the_forecast_supplies_temperature_and_condition():
    entity = _entity(_data(forecast=_forecast()))

    assert entity.native_temperature == 7.5
    assert entity.condition == "sunny"
    # Station-only measurements stay empty instead of being guessed.
    assert entity.native_wind_speed is None
    assert entity.humidity is None


def test_missing_forecast_lists_return_none():
    entity = _entity(_data(forecast=_forecast(current=None)))

    assert entity.condition is None
    assert entity.native_temperature is None
    assert asyncio.run(entity.async_forecast_daily()) is None
    assert asyncio.run(entity.async_forecast_hourly()) is None
