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


def test_async_get_forecast_ignores_invalid_warning_payload(monkeypatch):
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
    assert forecast.warnings == []


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
