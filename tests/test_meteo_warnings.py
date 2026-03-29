from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.meteo import MeteoClient, MeteoSwissDataError


def test_warning_parser_raises_when_all_warning_entries_are_invalid():
    client = MeteoClient(session=object())

    with pytest.raises(MeteoSwissDataError, match="warnings payload"):
        client._get_weather_warnings({"warnings": [None, None]})


def test_warning_parser_keeps_valid_entries_when_only_some_are_invalid():
    client = MeteoClient(session=object())

    warnings = client._get_weather_warnings(
        {
            "warnings": [
                None,
                {
                    "warnType": 10,
                    "warnLevel": 3,
                    "text": "Forest fire warning",
                    "htmlText": "Forest fire warning",
                    "outlook": False,
                    "validFrom": None,
                    "validTo": None,
                    "links": [],
                    "ordering": "a",
                },
            ]
        }
    )

    assert len(warnings) == 1
    assert warnings[0].type_state == "forest_fires"
