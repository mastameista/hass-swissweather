from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow

from custom_components.swissweather import config_flow as config_flow_module
from custom_components.swissweather.config_flow import ConfigFlow
from custom_components.swissweather.forecast_points import ForecastPoint
from custom_components.swissweather.station_lookup import WeatherStation


class FakeHass:
    def __init__(self) -> None:
        self.config = SimpleNamespace(latitude=47.0, longitude=8.0, language="en")

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def create_flow(source: str = config_entries.SOURCE_USER) -> ConfigFlow:
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


def test_user_step_reports_metadata_unavailable(monkeypatch) -> None:
    flow = create_flow()

    monkeypatch.setattr(
        config_flow_module,
        "async_load_forecast_point_list",
        AsyncMock(side_effect=config_flow_module.ForecastPointMetadataLoadError),
    )

    result = asyncio.run(
        flow.async_step_user({config_flow_module.CONF_FORECAST_QUERY: "Bellinzona"})
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {
        config_flow_module.CONF_FORECAST_QUERY: "forecast_query_metadata_unavailable"
    }


def test_forecast_pick_sets_unique_id_and_checks_duplicates() -> None:
    flow = create_flow()
    point = create_forecast_point()
    flow._pending_forecast_matches = [point]
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow._show_details_form = AsyncMock(
        return_value={"type": "form", "step_id": "details"}
    )

    result = asyncio.run(
        flow.async_step_forecast_pick(
            {config_flow_module.CONF_FORECAST_POINT: point.point_id}
        )
    )

    assert result["step_id"] == "details"
    flow.async_set_unique_id.assert_awaited_once_with("swissweather_650000")
    flow._abort_if_unique_id_configured.assert_called_once()


def test_forecast_pick_aborts_when_selected_point_already_configured() -> None:
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

def test_details_step_shows_form_again_when_connectivity_validation_fails() -> None:
    flow = create_flow()
    flow._selected_forecast_point_id = "650000"
    flow._augment_entry_data = AsyncMock(
        return_value={"postCode": "650000", "forecastPointType": "2"}
    )
    flow._async_validate_runtime_connectivity = AsyncMock(
        return_value={"base": "cannot_connect"}
    )

    result = asyncio.run(flow.async_step_details({}))

    assert result["type"] == "form"
    assert result["step_id"] == "details"
    assert result["errors"] == {"base": "cannot_connect"}


def test_validate_runtime_connectivity_returns_cannot_connect_on_missing_forecast(
    monkeypatch,
) -> None:
    flow = create_flow()
    monkeypatch.setattr(
        config_flow_module.MeteoClient,
        "get_forecast",
        Mock(return_value=None),
    )

    result = asyncio.run(
        flow._async_validate_runtime_connectivity(
            {"postCode": "650000", "forecastPointType": "2"}
        )
    )

    assert result == {"base": "cannot_connect"}


def test_metadata_helpers_are_cached_per_flow(monkeypatch) -> None:
    flow = create_flow()
    forecast_loader = AsyncMock(return_value=[create_forecast_point()])
    weather_loader = Mock(return_value=[create_weather_station()])
    pollen_loader = Mock(return_value=[create_pollen_station()])

    monkeypatch.setattr(
        config_flow_module, "async_load_forecast_point_list", forecast_loader
    )
    monkeypatch.setattr(config_flow_module, "load_weather_station_list", weather_loader)
    monkeypatch.setattr(config_flow_module, "load_pollen_station_list", pollen_loader)

    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_forecast_points())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_weather_stations())
    asyncio.run(flow._async_get_pollen_stations())
    asyncio.run(flow._async_get_pollen_stations())

    assert forecast_loader.await_count == 1
    assert weather_loader.call_count == 1
    assert pollen_loader.call_count == 1
