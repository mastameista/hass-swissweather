"""Entities before the first successful refresh, and small parser edge cases."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings.binary_sensor import (
    SwissWeatherHasActiveWarningsBinarySensor,
    SwissWeatherHasWarningsBinarySensor,
)
from custom_components.meteoswiss_forecast_warnings.meteo import (
    MeteoClient,
    MeteoSwissDataError,
    WarningLevel,
    WarningType,
    parse_warning_level,
    parse_warning_type,
)
from custom_components.meteoswiss_forecast_warnings.sensor import (
    POLLEN_SENSORS,
    SENSORS,
    SwissPollenLevelSensor,
    SwissPollenSensor,
    SwissWeatherHighestWarningLevelSensor,
    SwissWeatherSensor,
    SwissWeatherWarningCountSensor,
    SwissWeatherWarningSlotSensor,
    first_or_none,
)

DEVICE = {"identifiers": {("meteoswiss_forecast_warnings", "entry-1-forecast")}, "name": "Zürich"}
NO_DATA = SimpleNamespace(data=None)


def test_every_entity_reports_nothing_before_the_first_refresh():
    level_entry = next(e for e in POLLEN_SENSORS if e.device_class is None)
    entities = [
        SwissWeatherSensor("800100", "SMA", DEVICE, SENSORS[1], NO_DATA),
        SwissWeatherWarningCountSensor("800100", "Zürich", DEVICE, NO_DATA),
        SwissWeatherHighestWarningLevelSensor("800100", "Zürich", DEVICE, NO_DATA),
        SwissWeatherWarningSlotSensor("800100", "Zürich", 0, DEVICE, NO_DATA),
        SwissPollenSensor("800100", "PZH", DEVICE, level_entry, NO_DATA),
        SwissPollenLevelSensor("800100", "PZH", DEVICE, level_entry, NO_DATA),
    ]

    for entity in entities:
        assert entity.native_value in (None, "none"), type(entity).__name__
    for entity in entities[1:3] + entities[5:]:
        assert entity.extra_state_attributes is None, type(entity).__name__
    for entity in (
        SwissWeatherHasWarningsBinarySensor("800100", "Zürich", DEVICE, NO_DATA),
        SwissWeatherHasActiveWarningsBinarySensor("800100", "Zürich", DEVICE, NO_DATA),
    ):
        assert entity.is_on is None


def test_station_sensor_without_station_data():
    coordinator = SimpleNamespace(data=SimpleNamespace(current_weather=None))

    assert SwissWeatherSensor("800100", "SMA", DEVICE, SENSORS[1], coordinator).native_value is None


def test_first_or_none():
    assert first_or_none(None) is None
    assert first_or_none((3.5, "°C")) == 3.5


def test_unknown_warning_codes():
    assert parse_warning_type(None) is WarningType.UNKNOWN
    assert parse_warning_level(None) is WarningLevel.UNKNOWN


@pytest.mark.parametrize(
    ("value", "point_type", "query"),
    [("8620", "2", "862000"), ("862000", "2", "862000"), ("711", "3", "711"),
     ("8620", None, "862000"), ("711", None, "711")],
)
def test_forecast_query_value(value, point_type, query):
    assert MeteoClient(session=object())._build_forecast_query_value(value, point_type) == query


def test_undecodable_station_csv_is_a_data_error(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import meteo

    response = MagicMock()
    response.text = AsyncMock(side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"))

    async def fake_get_with_retry(session, url, **kwargs):
        return await kwargs["response_handler"](response)

    monkeypatch.setattr(meteo, "async_get_with_retry", fake_get_with_retry)

    with pytest.raises(MeteoSwissDataError):
        asyncio.run(MeteoClient(session=object())._async_get_csv_dictionary_for_url("http://x"))
