"""Hourly forecast parsing when the precipitation series are short or missing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings.meteo import MeteoClient

FIXTURE = Path(__file__).parent / "fixtures" / "forecast_800100.json"


@pytest.fixture
def forecast_json() -> dict:
    with FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh)


def _hourly(payload: dict):
    return MeteoClient(session=object())._get_hourly_forecast(copy.deepcopy(payload))


def test_full_payload_merges_ten_minute_and_hourly_precipitation(forecast_json):
    forecast = _hourly(forecast_json)

    assert len(forecast) == 6
    assert all(entry.precipitation is not None for entry in forecast)


def test_empty_ten_minute_series_keeps_the_hourly_forecast(forecast_json):
    """Regression: an empty precipitation10m list used to drop every hour."""
    forecast_json["graph"]["precipitation10m"] = []

    forecast = _hourly(forecast_json)

    assert len(forecast) == 6
    # The fixture has 6 hours but only 4 hourly precipitation values; the two
    # leading hours were covered by the 10-minute series and are now unknown.
    assert [entry.precipitation for entry in forecast[:2]] == [None, None]
    hourly = forecast_json["graph"]["precipitation1h"]
    assert [entry.precipitation for entry in forecast[2:]] == [(v, "mm/h") for v in hourly]
    assert all(entry.temperatureMax is not None for entry in forecast)


def test_missing_precipitation_does_not_drop_temperatures(forecast_json):
    del forecast_json["graph"]["precipitation10m"]
    del forecast_json["graph"]["precipitation1h"]

    forecast = _hourly(forecast_json)

    assert len(forecast) == 6
    assert all(entry.precipitation is None for entry in forecast)
    assert all(entry.temperatureMean is not None for entry in forecast)
