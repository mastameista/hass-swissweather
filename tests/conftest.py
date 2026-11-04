"""Shared test configuration."""

from __future__ import annotations

from http import HTTPStatus
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
POLLEN_KEYS = ("birke", "graeser", "erle", "hasel", "buche", "esche", "eiche")

# pytest-homeassistant-custom-component needs Linux (Home Assistant imports
# fcntl), so a plain Windows checkout runs the unit tests without it.
if importlib.util.find_spec("pytest_homeassistant_custom_component") is not None:

    class MeteoSwissApi:
        """Answer every MeteoSwiss endpoint from recorded fixtures.

        The integration runs unchanged, including parsing; only the network
        is replaced. aioclient_mock answers with the first matching
        registration, so a failure is simulated by registering everything
        again with that one URL overridden.
        """

        def __init__(self, aioclient_mock: Any) -> None:
            self.mock = aioclient_mock
            self._register({})

        def fail(self, url: str, status: HTTPStatus = HTTPStatus.SERVICE_UNAVAILABLE) -> None:
            """Let one endpoint answer with an HTTP error from now on."""
            self.override(url, status=status)

        def override(self, url: str, **response: Any) -> None:
            """Let one endpoint answer differently from now on."""
            self.mock.clear_requests()
            self._register({url: response})

        def _register(self, overrides: dict[str, dict[str, Any]]) -> None:
            from custom_components.meteoswiss_forecast_warnings.forecast_points import (
                FORECAST_POINT_LIST_URL,
            )
            from custom_components.meteoswiss_forecast_warnings.meteo import (
                CURRENT_CONDITION_URL,
                FORECAST_URL,
            )
            from custom_components.meteoswiss_forecast_warnings.pollen import (
                POLLEN_DATA_URL,
                POLLEN_STATIONS_URL,
            )
            from custom_components.meteoswiss_forecast_warnings.station_lookup import STATION_LIST_URL

            forecast = json.loads((FIXTURES / "forecast_800100.json").read_text("utf-8"))
            pollen = json.loads((FIXTURES / "pollen_data.json").read_text("utf-8"))
            responses: dict[str, dict[str, Any]] = {
                FORECAST_POINT_LIST_URL: {
                    "content": (FIXTURES / "forecast_points.csv").read_bytes()
                },
                STATION_LIST_URL: {
                    "content": (FIXTURES / "weather_stations.csv").read_bytes()
                },
                POLLEN_STATIONS_URL: {
                    # Excerpt of the live file, which is latin-1 encoded.
                    "content": (FIXTURES / "pollen_stations_live.csv").read_bytes()
                },
                CURRENT_CONDITION_URL: {
                    "content": (FIXTURES / "vqha80_sample.csv").read_bytes()
                },
            }
            for point_id in ("800100", "862000"):
                responses[FORECAST_URL.format(point_id)] = {"json": forecast}
            for key in POLLEN_KEYS:
                responses[POLLEN_DATA_URL.format(key=key, language="en")] = {
                    "json": pollen.get(key, {"stations": []})
                }
            for url, response in responses.items():
                self.mock.get(url, **overrides.get(url, response))

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Let Home Assistant load custom_components/meteoswiss_forecast_warnings in `hass` tests."""
        return

    @pytest.fixture
    def meteoswiss_api(aioclient_mock, monkeypatch) -> MeteoSwissApi:
        """Serve all MeteoSwiss endpoints; see MeteoSwissApi."""
        from custom_components.meteoswiss_forecast_warnings import request

        # Failures are retried; skip the back-off in tests.
        monkeypatch.setattr(request, "_RETRY_DELAYS", (0, 0))
        return MeteoSwissApi(aioclient_mock)
