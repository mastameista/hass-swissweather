from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather import config_flow as config_flow_module
from custom_components.swissweather.config_flow import ConfigFlow
from custom_components.swissweather.const import CONF_FORECAST_NAME, CONF_POST_CODE


class FakeHass:
    def __init__(self) -> None:
        self.config = SimpleNamespace(latitude=47.0, longitude=8.0)


def test_handle_forecast_search_returns_not_found_when_metadata_unavailable(
    monkeypatch,
):
    flow = ConfigFlow()
    flow.hass = FakeHass()
    flow._show_forecast_search_form = AsyncMock(return_value={"type": "form"})

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[]),
    )

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


def test_handle_forecast_search_routes_to_pick_step(monkeypatch):
    match = SimpleNamespace(
        point_id="6500",
        point_type_id="2",
        display_name="Bellinzona",
        postal_code="6500",
    )
    flow = ConfigFlow()
    flow.hass = FakeHass()
    flow.async_step_forecast_pick = AsyncMock(return_value={"type": "pick"})

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[match]),
    )

    result = asyncio.run(
        flow._handle_forecast_search(
            "user", {config_flow_module.CONF_FORECAST_QUERY: "6500"}
        )
    )

    assert result == {"type": "pick"}
    assert flow._pending_forecast_matches == [match]
    assert flow._selected_forecast_point_id is None
    flow.async_step_forecast_pick.assert_awaited_once()


def test_ensure_entry_names_keeps_setup_alive_when_metadata_unavailable(monkeypatch):
    entry = SimpleNamespace(
        data={CONF_POST_CODE: "6500"},
        title="MeteoSwiss",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))

    from custom_components.swissweather import __init__ as init_module

    monkeypatch.setattr(init_module, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(
        init_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        init_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        init_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[]),
    )

    result = asyncio.run(init_module._async_ensure_entry_names(hass, entry))

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
        ("async_load_forecast_point_list", []),
        ("async_load_weather_station_list", []),
        ("async_load_pollen_station_list", []),
    ],
)
def test_metadata_loaders_return_empty_on_failure(loader_name, expected):
    if loader_name == "async_load_forecast_point_list":
        from custom_components.swissweather import forecast_points as module

        class _BrokenSession:
            def get(self, *args, **kwargs):
                raise TimeoutError("boom")

        assert asyncio.run(getattr(module, loader_name)(_BrokenSession())) == expected
        return

    if loader_name == "async_load_weather_station_list":
        from custom_components.swissweather import station_lookup as module

        class _BrokenSession:
            def get(self, *args, **kwargs):
                raise TimeoutError("boom")

        assert asyncio.run(getattr(module, loader_name)(_BrokenSession())) == expected
        return

    from custom_components.swissweather import station_lookup as module

    class _BrokenPollenClient:
        async def async_get_pollen_station_list(self):
            raise RuntimeError("boom")

    assert (
        asyncio.run(getattr(module, loader_name)(_BrokenPollenClient())) == expected
    )


def test_pollen_station_loader_skips_invalid_station_rows():
    from custom_components.swissweather import station_lookup as module

    pollen_station = SimpleNamespace(
        name="Basel",
        abbreviation="BAS",
        altitude=None,
        lat=47.0,
        lng=8.0,
        canton="BS",
    )

    class _PollenClient:
        async def async_get_pollen_station_list(self):
            return [pollen_station]

    assert asyncio.run(module.async_load_pollen_station_list(_PollenClient())) == [
        module.WeatherStation("Basel", "BAS", None, 47.0, 8.0, "BS")
    ]


def test_meteo_client_returns_none_when_station_csv_unavailable():
    from custom_components.swissweather import meteo

    class _BrokenSession:
        def get(self, *args, **kwargs):
            raise TimeoutError("boom")

    with pytest.raises(meteo.MeteoSwissConnectionError):
        asyncio.run(
            meteo.MeteoClient(
                _BrokenSession()
            ).async_get_current_weather_for_all_stations()
        )


def test_pollen_client_returns_none_on_json_failure():
    from custom_components.swissweather import pollen

    class _BrokenResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        async def json(self):
            raise ValueError("bad json")

    class _Session:
        def get(self, *args, **kwargs):
            return _BrokenResponse()

    with pytest.raises(pollen.PollenDataError):
        asyncio.run(
            pollen.PollenClient(_Session()).async_get_current_pollen_for_station_type(
                "BAS", "birke"
            )
        )


def test_config_flow_caches_metadata_per_flow_instance(monkeypatch):
    calls: list[str] = []

    async def _load_forecast_points(session):
        calls.append("forecast")
        return []

    async def _load_weather_stations(session):
        calls.append("weather")
        return []

    async def _load_pollen_stations(client):
        calls.append("pollen")
        return []

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module, "async_load_forecast_point_list", _load_forecast_points
    )
    monkeypatch.setattr(
        config_flow_module, "async_load_weather_station_list", _load_weather_stations
    )
    monkeypatch.setattr(
        config_flow_module, "async_load_pollen_station_list", _load_pollen_stations
    )

    flow = ConfigFlow()
    flow.hass = FakeHass()

    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_pollen_stations())
    asyncio.run(flow._async_get_pollen_stations())

    assert calls == ["forecast", "weather", "pollen"]
