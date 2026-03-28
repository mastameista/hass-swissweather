from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.swissweather.const import CONF_POST_CODE, CONF_STATION_CODE
from custom_components.swissweather.coordinator import SwissWeatherDataCoordinator


class FakeHass:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher

    async def async_add_executor_job(self, func, *args):
        return self._dispatcher(func, *args)


def test_weather_coordinator_fails_when_forecast_missing():
    def dispatcher(func, *args):
        if func.__name__ == "get_current_weather_for_station":
            return None
        if func.__name__ == "get_forecast":
            return None
        raise AssertionError(f"Unexpected call: {func.__name__}")

    coordinator = SwissWeatherDataCoordinator(
        FakeHass(dispatcher),
        SimpleNamespace(
            data={CONF_POST_CODE: "6500", CONF_STATION_CODE: "BAS"},
        ),
    )

    with pytest.raises(UpdateFailed, match="No forecast data returned"):
        asyncio.run(coordinator._async_update_data())


def test_weather_coordinator_uses_forecast_current_as_fallback():
    forecast = SimpleNamespace(
        current=SimpleNamespace(currentTemperature=(12.3, "C")),
        warnings=[],
    )

    def dispatcher(func, *args):
        if func.__name__ == "get_current_weather_for_station":
            raise RuntimeError("weather station offline")
        if func.__name__ == "get_forecast":
            return forecast
        raise AssertionError(f"Unexpected call: {func.__name__}")

    coordinator = SwissWeatherDataCoordinator(
        FakeHass(dispatcher),
        SimpleNamespace(
            data={CONF_POST_CODE: "6500", CONF_STATION_CODE: "BAS"},
        ),
    )

    result = asyncio.run(coordinator._async_update_data())

    assert result.forecast is forecast
    assert result.current_weather is not None
    assert result.current_weather.airTemperature == (12.3, "C")
    assert result.warning_snapshot.count == 0
