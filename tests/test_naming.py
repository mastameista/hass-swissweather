"""Display names, entry titles and unique IDs."""

from __future__ import annotations

import pytest

from custom_components.meteoswiss_forecast_warnings.naming import (
    build_entry_title,
    build_entry_unique_id,
    format_station_display_name,
)


@pytest.mark.parametrize(
    ("name", "canton", "include_canton", "expected"),
    [
        (None, "ZH", True, None),
        ("   ", "ZH", True, None),
        ("Zürich  /   Fluntern", None, False, "Zürich / Fluntern"),
        ("Zürich / Fluntern", "ZH", False, "Zürich / Fluntern"),
        ("Zürich / Fluntern", "ZH", True, "Zürich / Fluntern ZH"),
        # The canton is already part of the name and is not repeated.
        ("Buchs ZH", "ZH", True, "Buchs ZH"),
        ("Basel", " ", True, "Basel"),
        # MeteoSwiss writes "Pfäffikon, ZH" where two places share a name.
        ("Pfäffikon, ZH", None, False, "Pfäffikon ZH"),
        ("Pfäffikon,", "SZ", True, "Pfäffikon SZ"),
    ],
)
def test_format_station_display_name(name, canton, include_canton, expected):
    assert format_station_display_name(name, canton, include_canton=include_canton) == expected


def test_entry_title_lists_the_configured_places():
    assert build_entry_title("Buchs ZH", "Pfäffikon ZH", None) == (
        "MeteoSwiss Buchs ZH / Pfäffikon ZH"
    )
    assert build_entry_title(None, None, None) == "MeteoSwiss"


@pytest.mark.parametrize(
    ("post_code", "expected"),
    [("810700", "swissweather_810700"), (" 8107 ", "swissweather_8107"), ("  ", None), (None, None)],
)
def test_entry_unique_id(post_code, expected):
    assert build_entry_unique_id(post_code) == expected
