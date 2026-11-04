"""Pollen readings when a station reports no data."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings import pollen
from custom_components.meteoswiss_forecast_warnings.pollen import PollenClient

MEASURED = {"value": "12", "date": 1793797200000, "summary": "Birch, measured on 4.11.2026"}
# What MeteoSwiss serves for a station without a current reading (seen for PBS).
NO_DATA = {"value": None, "date": None, "label": "Current value", "summary": "no data"}


def _read(stations: list, abbrev: str):
    async def fake_get_with_retry(session, url, **kwargs):
        return {"stations": stations}

    client = PollenClient(session=object(), language="en")
    with patch.object(pollen, "async_get_with_retry", fake_get_with_retry):
        return asyncio.run(client.async_get_current_pollen_for_station_type(abbrev, "birke"))


def test_station_without_current_reading_is_not_a_warning(caplog):
    """Regression: "no data" logged two warnings per plant on every refresh."""
    caplog.set_level(logging.DEBUG, logger=pollen.__name__)

    value, timestamp = _read([{"id": "PBS", "current": NO_DATA}], "PBS")

    assert (value, timestamp) == (None, None)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_unreadable_timestamp_is_still_a_warning(caplog):
    broken = {"value": "12", "date": "yesterday"}

    value, timestamp = _read([{"id": "PBS", "current": broken}], "PBS")

    assert (value, timestamp) == (None, None)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("timestamp" in m for m in messages)
    assert not any("Couldn't find" in m for m in messages)


def test_missing_station_is_reported_as_missing(caplog):
    value, timestamp = _read([{"id": "PZH", "current": MEASURED}], "PBS")

    assert (value, timestamp) == (None, None)
    assert any("Couldn't find" in r.getMessage() for r in caplog.records)


def test_measured_value_is_returned():
    value, timestamp = _read([{"id": "PZH", "current": MEASURED}], "PZH")

    assert value == 12.0
    assert timestamp is not None
