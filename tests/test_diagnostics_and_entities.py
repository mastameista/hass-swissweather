from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.const import (
    CONF_FORECAST_NAME,
    CONF_POLLEN_STATION_CODE,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
)
from custom_components.swissweather.coordinator import WarningSnapshot, WeatherData
from custom_components.swissweather.diagnostics import async_get_config_entry_diagnostics
from custom_components.swissweather.sensor import async_setup_entry as async_setup_sensor_entry
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


def test_weather_entity_uses_device_name_as_main_feature():
    coordinator = SimpleNamespace(data=None)
    entity = SwissWeather(
        coordinator,
        "Sevelen",
        SimpleNamespace(
            entry_id="entry-1",
            data={CONF_POST_CODE: "9475"},
        ),
    )

    assert entity.name is None
    assert entity.device_info["name"] == "Sevelen"


def test_weather_entity_exposes_forecast_and_current_sources():
    coordinator = SimpleNamespace(data=None)
    entity = SwissWeather(
        coordinator,
        "Sevelen",
        SimpleNamespace(
            entry_id="entry-1",
            data={CONF_POST_CODE: "9475", CONF_STATION_NAME: "Vaduz FL"},
        ),
    )

    assert entity.extra_state_attributes == {
        "forecast_source": "Sevelen",
        "current_weather_source": "Vaduz FL",
    }
    assert entity.attribution == "MeteoSwiss. Forecast: Sevelen. Current weather: Vaduz FL."


def test_sensor_setup_skips_current_weather_sensors_without_station():
    added_entities = []
    config_entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_POST_CODE: "9475",
            CONF_FORECAST_NAME: "Sevelen",
            CONF_STATION_CODE: None,
            CONF_POLLEN_STATION_CODE: None,
            CONF_WARNINGS_ENABLED: True,
        },
        runtime_data=SimpleNamespace(
            weather_coordinator=SimpleNamespace(data=None),
            pollen_coordinator=SimpleNamespace(data=None),
        ),
    )

    def _add_entities(entities):
        added_entities.extend(entities)

    asyncio.run(
        async_setup_sensor_entry(
            SimpleNamespace(),
            config_entry,
            _add_entities,
        )
    )

    assert [entity.unique_id for entity in added_entities] == [
        "9475.warning_count",
        "9475.highest_warning_level",
        "9475.primary_warning",
        "9475.secondary_warning",
        "9475.tertiary_warning",
    ]
