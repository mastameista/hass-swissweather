from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow

from custom_components.swissweather import config_flow as config_flow_module
from custom_components.swissweather.config_flow import (
    ConfigFlow,
    NO_POLLEN_STATION_OPTION,
    SEARCH_AGAIN_OPTION,
)
from custom_components.swissweather.const import (
    CONF_FORECAST_NAME,
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
)
from custom_components.swissweather.forecast_points import (
    ForecastPoint,
    ForecastPointMetadataLoadError,
)
from custom_components.swissweather.station_lookup import WeatherStation


class FakeHass:
    def __init__(self) -> None:
        self.config = SimpleNamespace(latitude=47.0, longitude=8.0)


def create_flow(
    source: str = config_entries.SOURCE_USER,
) -> ConfigFlow:
    flow = ConfigFlow()
    flow.hass = FakeHass()
    flow.context = {"source": source}
    flow.flow_id = "test-flow"
    return flow


def create_forecast_point() -> ForecastPoint:
    return ForecastPoint(
        "650000",
        "2",
        "6500",
        "Bellinzona",
        "ZIP",
        238,
        46.19,
        9.02,
    )


def create_weather_station() -> WeatherStation:
    return WeatherStation("Biasca", "BIA", 301, 46.36, 8.97, "TI")


def create_pollen_station() -> WeatherStation:
    return WeatherStation("Basel", "BAS", 260, 47.56, 7.59, "BS")


def test_user_step_shows_search_form() -> None:
    flow = create_flow()

    result = asyncio.run(flow.async_step_user())

    assert result["type"] == "form"
    assert result["step_id"] == "user"


def test_reconfigure_step_shows_station_form(monkeypatch) -> None:
    flow = create_flow(config_entries.SOURCE_RECONFIGURE)
    entry = SimpleNamespace(
        data={
            CONF_POST_CODE: "650000",
            CONF_STATION_CODE: "BIA",
            CONF_POLLEN_STATION_CODE: "BAS",
            CONF_WARNINGS_ENABLED: True,
        }
    )
    flow._get_reconfigure_entry = Mock(return_value=entry)

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[create_weather_station()]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[create_pollen_station()]),
    )

    result = asyncio.run(flow.async_step_reconfigure())

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"


def test_user_step_reports_metadata_unavailable(monkeypatch) -> None:
    flow = create_flow()

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(side_effect=ForecastPointMetadataLoadError("boom")),
    )

    result = asyncio.run(
        flow.async_step_user({config_flow_module.CONF_FORECAST_QUERY: "Bellinzona"})
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {
        config_flow_module.CONF_FORECAST_QUERY: "forecast_query_metadata_unavailable"
    }


def test_user_step_routes_to_forecast_pick_form(monkeypatch) -> None:
    flow = create_flow()
    match = create_forecast_point()

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[match]),
    )

    result = asyncio.run(
        flow.async_step_user({config_flow_module.CONF_FORECAST_QUERY: "6500"})
    )

    assert result["type"] == "form"
    assert result["step_id"] == "forecast_pick"
    assert flow._pending_forecast_matches == [match]
    assert flow._selected_forecast_point_id is None


def test_forecast_pick_search_again_returns_search_form() -> None:
    flow = create_flow()
    flow._pending_forecast_matches = [create_forecast_point()]
    flow._last_forecast_query = "Bellinzona"

    result = asyncio.run(
        flow.async_step_forecast_pick(
            {config_flow_module.CONF_FORECAST_POINT: SEARCH_AGAIN_OPTION}
        )
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert flow._pending_forecast_matches == []
    assert flow._selected_forecast_point_id is None


def test_forecast_pick_selected_point_routes_to_details_form(monkeypatch) -> None:
    flow = create_flow()
    point = create_forecast_point()
    weather_station = create_weather_station()
    pollen_station = create_pollen_station()
    flow._pending_forecast_matches = [point]
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[weather_station]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[pollen_station]),
    )

    result = asyncio.run(
        flow.async_step_forecast_pick(
            {config_flow_module.CONF_FORECAST_POINT: point.point_id}
        )
    )

    assert result["type"] == "form"
    assert result["step_id"] == "details"
    assert flow._selected_forecast_point_id == point.point_id
    assert flow._selected_forecast_point_type == point.point_type_id
    flow.async_set_unique_id.assert_awaited_once()
    flow._abort_if_unique_id_configured.assert_called_once()


def test_forecast_pick_aborts_when_point_is_already_configured() -> None:
    flow = create_flow()
    point = create_forecast_point()
    flow._pending_forecast_matches = [point]
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock(
        side_effect=AbortFlow("already_configured")
    )

    with pytest.raises(AbortFlow, match="already_configured"):
        asyncio.run(
            flow.async_step_forecast_pick(
                {config_flow_module.CONF_FORECAST_POINT: point.point_id}
            )
        )


def test_details_step_creates_entry_from_public_flow(monkeypatch) -> None:
    flow = create_flow()
    point = create_forecast_point()
    weather_station = create_weather_station()
    pollen_station = create_pollen_station()
    flow._selected_forecast_point_id = point.point_id
    flow._selected_forecast_point_type = point.point_type_id

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[point]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[weather_station]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[pollen_station]),
    )

    result = asyncio.run(
        flow.async_step_details(
            {
                CONF_STATION_CODE: weather_station.code,
                CONF_POLLEN_STATION_CODE: NO_POLLEN_STATION_OPTION,
                CONF_WARNINGS_ENABLED: True,
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "MeteoSwiss Bellinzona / Biasca TI"
    assert result["description"] == "650000"
    assert result["data"][CONF_POST_CODE] == point.point_id
    assert result["data"][CONF_FORECAST_NAME] == "Bellinzona"
    assert result["data"][CONF_STATION_CODE] == weather_station.code
    assert result["data"][CONF_POLLEN_STATION_CODE] is None
    assert result["data"][CONF_WARNINGS_ENABLED] is True


def test_reconfigure_step_updates_existing_entry(monkeypatch) -> None:
    flow = create_flow(config_entries.SOURCE_RECONFIGURE)
    entry = SimpleNamespace(
        unique_id="forecast_650000",
        data={
            CONF_POST_CODE: "650000",
            CONF_FORECAST_NAME: "Bellinzona",
            CONF_STATION_CODE: "OLD",
            CONF_POLLEN_STATION_CODE: "OLDP",
            CONF_WARNINGS_ENABLED: True,
        }
    )
    weather_station = create_weather_station()
    pollen_station = create_pollen_station()
    flow._get_reconfigure_entry = Mock(return_value=entry)
    flow.async_update_reload_and_abort = Mock(
        return_value={"type": "abort", "reason": "reconfigure_successful"}
    )

    async def _set_unique_id(value: str) -> None:
        flow.context["unique_id"] = value

    flow.async_set_unique_id = AsyncMock(side_effect=_set_unique_id)

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[create_forecast_point()]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[weather_station]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[pollen_station]),
    )

    result = asyncio.run(
        flow.async_step_reconfigure(
            {
                CONF_STATION_CODE: weather_station.code,
                CONF_POLLEN_STATION_CODE: NO_POLLEN_STATION_OPTION,
                CONF_WARNINGS_ENABLED: False,
            }
        )
    )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    flow.async_set_unique_id.assert_awaited_once_with(entry.unique_id)
    flow.async_update_reload_and_abort.assert_called_once()
    assert (
        flow.async_update_reload_and_abort.call_args.kwargs["data_updates"][
            CONF_STATION_NAME
        ]
        == "Biasca TI"
    )
    assert (
        flow.async_update_reload_and_abort.call_args.kwargs["data_updates"][
            CONF_POLLEN_STATION_CODE
        ]
        is None
    )


def test_details_step_formats_pollen_station_like_weather_station(monkeypatch) -> None:
    flow = create_flow()
    point = create_forecast_point()
    weather_station = create_weather_station()
    pollen_station = create_pollen_station()
    flow._selected_forecast_point_id = point.point_id
    flow._selected_forecast_point_type = point.point_type_id

    monkeypatch.setattr(
        config_flow_module, "async_get_clientsession", lambda hass: object()
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(return_value=[point]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_weather_station_list",
        AsyncMock(return_value=[weather_station]),
    )
    monkeypatch.setattr(
        config_flow_module,
        "async_load_pollen_station_list",
        AsyncMock(return_value=[pollen_station]),
    )

    result = asyncio.run(
        flow.async_step_details(
            {
                CONF_STATION_CODE: weather_station.code,
                CONF_POLLEN_STATION_CODE: pollen_station.code,
                CONF_WARNINGS_ENABLED: True,
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "MeteoSwiss Bellinzona / Biasca TI / Basel BS"
    assert result["data"][CONF_STATION_NAME] == "Biasca TI"
    assert result["data"][CONF_POLLEN_STATION_NAME] == "Basel BS"


def test_ensure_entry_names_keeps_setup_alive_when_metadata_unavailable(monkeypatch):
    import custom_components.swissweather as init_module

    entry = SimpleNamespace(
        data={CONF_POST_CODE: "6500"},
        title="MeteoSwiss",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))

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

    async def _load_forecast_points(session, **kwargs):
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

    flow = create_flow()

    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_pollen_stations())
    asyncio.run(flow._async_get_pollen_stations())

    assert calls == ["forecast", "weather", "pollen"]
