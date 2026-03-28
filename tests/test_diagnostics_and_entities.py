from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.const import CONF_FORECAST_NAME, CONF_POST_CODE
from custom_components.swissweather.coordinator import WarningSnapshot, WeatherData
from custom_components.swissweather.diagnostics import async_get_config_entry_diagnostics
from custom_components.swissweather.weather import SwissWeather


def test_diagnostics_redacts_entry_location_data():
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            weather_coordinator=SimpleNamespace(
                data=WeatherData(
                    current_weather=None,
                    forecast=None,
                    warning_snapshot=WarningSnapshot(
                        all_warnings=[],
                        active_warnings=[],
                        sorted_warnings=[],
                        primary=None,
                        secondary=None,
                        tertiary=None,
                        count=0,
                        highest_level=None,
                    ),
                )
            ),
            pollen_coordinator=SimpleNamespace(data=None),
        ),
        as_dict=lambda: {
            "title": "Bellinzona",
            "unique_id": "swissweather_bellinzona_6500",
            "data": {
                CONF_POST_CODE: "6500",
                CONF_FORECAST_NAME: "Bellinzona",
            },
        },
    )

    diagnostics = asyncio.run(
        async_get_config_entry_diagnostics(SimpleNamespace(), entry)
    )

    assert diagnostics["entry"]["title"] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_POST_CODE] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_FORECAST_NAME] == "**REDACTED**"
    assert diagnostics["weather"]["warning_snapshot"]["count"] == 0


def test_weather_entity_keeps_place_name_without_forecast_suffix():
    coordinator = SimpleNamespace(data=None)
    entity = SwissWeather(
        coordinator,
        "Sevelen",
        SimpleNamespace(
            entry_id="entry-1",
            data={CONF_POST_CODE: "9475"},
        ),
    )

    assert entity.name == "Sevelen"
