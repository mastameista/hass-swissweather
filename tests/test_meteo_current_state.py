from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.meteo import MISSING_VALUE_SENTINEL, MeteoClient


def test_current_state_reads_icon_v2():
    client = MeteoClient(session=object())

    state = client._get_current_state(
        {"currentWeather": {"iconV2": 102, "temperature": 21.5}}
    )

    assert state.currentIcon == 102
    assert state.currentCondition == "partlycloudy"
    assert state.currentTemperature == (21.5, "°C")


def test_current_state_treats_sentinel_as_missing():
    client = MeteoClient(session=object())

    state = client._get_current_state(
        {
            "currentWeather": {
                "icon": MISSING_VALUE_SENTINEL,
                "iconV2": MISSING_VALUE_SENTINEL,
                "temperature": float(MISSING_VALUE_SENTINEL),
            }
        }
    )

    assert state.currentIcon is None
    assert state.currentCondition is None
    assert state.currentTemperature == (None, "°C")


def test_current_state_ignores_deprecated_icon_field():
    client = MeteoClient(session=object())

    state = client._get_current_state(
        {"currentWeather": {"icon": 1, "iconV2": 102, "temperature": 3.0}}
    )

    assert state.currentIcon == 102
    assert state.currentCondition == "partlycloudy"


def test_current_state_returns_none_without_current_weather():
    client = MeteoClient(session=object())

    assert client._get_current_state({}) is None
