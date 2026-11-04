from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from datetime import UTC, datetime

from custom_components.swissweather.meteo import (
    FORECAST_URL,
    MeteoClient,
    MeteoSwissDataError,
    WarningLevel,
    WarningType,
)


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


def test_async_get_forecast_marks_unreadable_warnings_as_unknown(monkeypatch):
    """Unreadable warnings keep the forecast but must not read as "no warnings"."""
    client = MeteoClient(session=object())

    monkeypatch.setattr(client, "_async_get_forecast_json", AsyncMock(return_value={}))
    monkeypatch.setattr(client, "_get_current_state", lambda forecast_json: None)
    monkeypatch.setattr(client, "_get_daily_forecast", lambda forecast_json: [])
    monkeypatch.setattr(client, "_get_hourly_forecast", lambda forecast_json: [])
    monkeypatch.setattr(
        client,
        "_get_weather_warnings",
        Mock(side_effect=MeteoSwissDataError("Failed to parse MeteoSwiss warnings payload")),
    )

    forecast = asyncio.run(client.async_get_forecast("6500"))

    assert forecast is not None
    assert forecast.dailyForecast == []
    assert forecast.hourlyForecast == []
    assert forecast.warnings is None


@pytest.mark.parametrize("payload", [{"type": 1}, "none", 3])
def test_warnings_block_that_is_not_a_list_is_a_data_error(payload):
    client = MeteoClient(session=object())

    with pytest.raises(MeteoSwissDataError):
        client._get_weather_warnings({"warnings": payload})


def test_missing_warnings_block_means_no_warnings():
    client = MeteoClient(session=object())

    assert client._get_weather_warnings({}) == []


def test_forecast_url_uses_v3_endpoint():
    """Regression: v2/plzDetail drops drought warnings, v3 delivers them."""
    assert "/v3/plzDetail" in FORECAST_URL


def test_drought_warning_without_end_is_parsed_and_active():
    """Drought warnings arrive open-ended (no validTo) and carry a regionId."""
    client = MeteoClient(session=object())

    # Shape taken from a live v3 response for 8620 Wetzikon (2026-11-03).
    warnings = client._get_weather_warnings(
        {
            "warnings": [
                {
                    "warnType": 12,
                    "warnLevel": 4,
                    "text": "- Auswirkungen: ...",
                    "htmlText": "<b>- Auswirkungen: </b>...",
                    "outlook": False,
                    "validFrom": 1782338400000,
                    "links": [],
                    "ordering": "a2n1782338400000",
                    "regionId": 43,
                }
            ]
        }
    )

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.warningType == WarningType.DROUGHT
    assert warning.warningLevel == WarningLevel(4)
    assert warning.validFrom == datetime(2026, 6, 24, 22, 0, tzinfo=UTC)
    assert warning.validTo is None
    assert warning.is_active(datetime(2026, 11, 3, tzinfo=UTC))
    assert not warning.is_expired(datetime(2030, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("validTo", 999999999999999),  # beyond datetime's range
        ("validTo", "soon"),
        ("validFrom", "yesterday"),
    ],
)
def test_unreadable_timestamp_rejects_the_warning(field, value):
    """Regression: an unreadable bound used to turn into "valid forever"."""
    client = MeteoClient(session=object())
    payload = {
        "warnType": 1,
        "warnLevel": 3,
        "text": "Thunderstorms",
        "validFrom": 1782338400000,
        "validTo": 1782424800000,
        "links": [],
    }
    payload[field] = value

    warnings = client._get_weather_warnings({"warnings": [payload, {**payload, field: None}]})

    # The broken entry is dropped; the same warning without that bound is kept.
    assert len(warnings) == 1
    assert warnings[0].raw_type == 1


def test_warning_without_links_gets_an_empty_link_list():
    client = MeteoClient(session=object())

    warnings = client._get_weather_warnings(
        {"warnings": [{"warnType": 1, "warnLevel": 2, "links": None}]}
    )

    assert warnings[0].links == []
