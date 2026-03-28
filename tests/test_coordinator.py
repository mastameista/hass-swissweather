from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.swissweather.const import CONF_POST_CODE, CONF_STATION_CODE
from custom_components.swissweather.coordinator import SwissWeatherDataCoordinator


class FakeHass:
    pass


def test_weather_coordinator_fails_when_forecast_missing(monkeypatch):
    from custom_components.swissweather import coordinator as coordinator_module

    class _FakeMeteoClient:
        def __init__(self, session):
            self.session = session

        async def async_get_current_weather_for_station(self, station_code):
            return None

        async def async_get_forecast(self, post_code, forecast_point_type):
            return None

    monkeypatch.setattr(
        coordinator_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(coordinator_module, "MeteoClient", _FakeMeteoClient)

    coordinator = SwissWeatherDataCoordinator(
        FakeHass(),
        SimpleNamespace(
            data={CONF_POST_CODE: "6500", CONF_STATION_CODE: "BAS"},
        ),
    )

    with pytest.raises(UpdateFailed, match="No forecast data returned"):
        asyncio.run(coordinator._async_update_data())


def test_weather_coordinator_uses_forecast_current_as_fallback(monkeypatch):
    from custom_components.swissweather import coordinator as coordinator_module

    forecast = SimpleNamespace(
        current=SimpleNamespace(currentTemperature=(12.3, "C")),
        warnings=[],
    )

    class _FakeMeteoClient:
        def __init__(self, session):
            self.session = session

        async def async_get_current_weather_for_station(self, station_code):
            raise RuntimeError("weather station offline")

        async def async_get_forecast(self, post_code, forecast_point_type):
            return forecast

    monkeypatch.setattr(
        coordinator_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(coordinator_module, "MeteoClient", _FakeMeteoClient)

    coordinator = SwissWeatherDataCoordinator(
        FakeHass(),
        SimpleNamespace(
            data={CONF_POST_CODE: "6500", CONF_STATION_CODE: "BAS"},
        ),
    )

    result = asyncio.run(coordinator._async_update_data())

    assert result.forecast is forecast
    assert result.current_weather is not None
    assert result.current_weather.airTemperature == (12.3, "C")
    assert result.warning_snapshot.count == 0
