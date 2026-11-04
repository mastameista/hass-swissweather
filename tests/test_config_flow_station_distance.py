"""Station dropdown: distance labels and ordering when coordinates are missing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.config_flow import ConfigFlow
from custom_components.swissweather.station_lookup import WeatherStation

NEAR = WeatherStation("Pfäffikon, ZH", "PFA", 537, 47.38, 8.79, "ZH")
FAR = WeatherStation("Lugano", "LUG", 273, 46.0, 8.96, "TI")
# Pollen metadata can lack coordinates; the dataclass does not enforce floats.
NO_COORDS = WeatherStation("Unbekannt", "UNK", None, None, None, "ZH")


def _flow(latitude, longitude) -> ConfigFlow:
    flow = ConfigFlow()
    flow.hass = SimpleNamespace(
        config=SimpleNamespace(latitude=latitude, longitude=longitude)
    )
    return flow


def test_station_without_coordinates_is_listed_last_without_distance():
    """Regression: a pollen station without coordinates crashed the dropdown."""
    flow = _flow(47.33, 8.79)
    flow._async_get_pollen_stations = AsyncMock(return_value=[NO_COORDS, FAR, NEAR])

    options = asyncio.run(flow._get_pollen_station_options())

    codes = [option["value"] for option in options[1:]]
    assert codes == ["PFA", "LUG", "UNK"]
    assert options[-1]["label"] == "Unbekannt (ZH)"
    assert options[1]["label"].endswith("km away")


def test_unknown_home_location_shows_no_distance():
    """Regression: an unknown HA location showed every station as "999 km away"."""
    flow = _flow(None, None)

    assert flow.format_station_name_for_dropdown(NEAR) == "Pfäffikon, ZH (ZH)"
