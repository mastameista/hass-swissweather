"""Weather station list parsing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings import station_lookup

HEADER = "Station;Abbr.;Station height m a. sea level;Latitude;Longitude;Canton;Measurements"
GOOD = "Pfäffikon ZH;PFA;537;47.38;8.79;ZH;Temperature, Precipitation"
NO_COORDINATES = "Neue Station;NEU;;;;BE;Temperature"
NO_NAME = ";XXX;500;46.0;7.0;VS;Temperature"


def _load(csv_text: str):
    response = MagicMock()
    response.text = AsyncMock(return_value=csv_text)

    async def fake_get_with_retry(session, url, *, logger, response_handler, timeout):
        return await response_handler(response)

    with patch.object(station_lookup, "async_get_with_retry", fake_get_with_retry):
        return asyncio.run(
            station_lookup.async_load_weather_station_list(object(), raise_on_error=True)
        )


def test_station_with_empty_fields_does_not_drop_the_whole_list():
    """Regression: one row with an empty latitude raised ValueError for all rows."""
    stations = _load("\n".join([HEADER, GOOD, NO_COORDINATES]))

    assert [station.code for station in stations] == ["PFA", "NEU"]
    unknown = stations[1]
    assert (unknown.altitude, unknown.lat, unknown.lng) == (None, None, None)
    assert stations[0].lat == 47.38


def test_station_without_name_is_skipped():
    stations = _load("\n".join([HEADER, GOOD, NO_NAME]))

    assert [station.code for station in stations] == ["PFA"]
