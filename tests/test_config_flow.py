from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather import config_flow as config_flow_module
from custom_components.swissweather.config_flow import ConfigFlow
from custom_components.swissweather.const import (
    CONF_FORECAST_NAME,
    CONF_POST_CODE,
)


class FakeHass:
    def __init__(self, *, executor_return=None) -> None:
        self.config = SimpleNamespace(latitude=47.0, longitude=8.0)
        self._executor_return = executor_return

    async def async_add_executor_job(self, func, *args):
        if isinstance(self._executor_return, Exception):
            raise self._executor_return
        if self._executor_return is not None:
            return self._executor_return
        return func(*args)


def test_handle_forecast_search_returns_not_found_when_metadata_unavailable():
    flow = ConfigFlow()
    flow.hass = FakeHass(executor_return=[])
    flow._show_forecast_search_form = AsyncMock(return_value={"type": "form"})

    result = asyncio.run(
        flow._handle_forecast_search(
            "user", {config_flow_module.CONF_FORECAST_QUERY: "Bellinzona"}
        )
    )

    assert result == {"type": "form"}
    flow._show_forecast_search_form.assert_awaited_once()
    assert flow._show_forecast_search_form.await_args.kwargs["errors"] == {
        config_flow_module.CONF_FORECAST_QUERY: "forecast_query_not_found"
    }


def test_handle_forecast_search_routes_to_pick_step():
    match = SimpleNamespace(
        point_id="6500",
        point_type_id="2",
        display_name="Bellinzona",
        postal_code="6500",
    )
    flow = ConfigFlow()
    flow.hass = FakeHass(executor_return=[match])
    flow.async_step_forecast_pick = AsyncMock(return_value={"type": "pick"})

    result = asyncio.run(
        flow._handle_forecast_search(
            "user", {config_flow_module.CONF_FORECAST_QUERY: "6500"}
        )
    )

    assert result == {"type": "pick"}
    assert flow._pending_forecast_matches == [match]
    assert flow._selected_forecast_point_id is None
    flow.async_step_forecast_pick.assert_awaited_once()


def test_ensure_entry_names_keeps_setup_alive_when_metadata_unavailable():
    entry = SimpleNamespace(
        data={CONF_POST_CODE: "6500"},
        title="MeteoSwiss",
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=Mock()),
        async_add_executor_job=AsyncMock(side_effect=[[], [], []]),
    )

    from custom_components.swissweather.__init__ import _async_ensure_entry_names

    result = asyncio.run(_async_ensure_entry_names(hass, entry))

    assert result is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            CONF_POST_CODE: "6500",
            CONF_FORECAST_NAME: "6500",
            "warningsEnabled": True,
        },
        title="MeteoSwiss 6500",
    )


@pytest.mark.parametrize(
    ("loader_name", "expected"),
    [
        ("load_forecast_point_list", []),
        ("load_weather_station_list", []),
        ("load_pollen_station_list", []),
    ],
)
def test_metadata_loaders_return_empty_on_failure(loader_name, expected, monkeypatch):
    module = {
        "load_forecast_point_list": __import__(
            "custom_components.swissweather.forecast_points", fromlist=["dummy"]
        ),
        "load_weather_station_list": __import__(
            "custom_components.swissweather.station_lookup", fromlist=["dummy"]
        ),
        "load_pollen_station_list": __import__(
            "custom_components.swissweather.station_lookup", fromlist=["dummy"]
        ),
    }[loader_name]

    if loader_name == "load_pollen_station_list":
        monkeypatch.setattr(
            module, "PollenClient", lambda: SimpleNamespace(get_pollen_station_list=Mock(side_effect=RuntimeError("boom")))
        )
    else:
        class _BrokenResponse:
            def __enter__(self):
                raise module.requests.exceptions.Timeout("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _BrokenResponse())

    assert getattr(module, loader_name)() == expected


def test_meteo_client_returns_none_when_station_csv_unavailable(monkeypatch):
    from custom_components.swissweather import meteo

    class _BrokenResponse:
        def __enter__(self):
            raise meteo.requests.exceptions.Timeout("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(meteo.requests, "get", lambda *args, **kwargs: _BrokenResponse())

    assert meteo.MeteoClient().get_current_weather_for_all_stations() == []


def test_pollen_client_returns_none_on_json_failure(monkeypatch):
    from custom_components.swissweather import pollen

    class _BrokenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(pollen.requests, "get", lambda *args, **kwargs: _BrokenResponse())

    value, timestamp = pollen.PollenClient().get_current_pollen_for_station_type(
        "BAS", "birke"
    )
    assert value is None
    assert timestamp is None
