"""Drive the config flow end to end through Home Assistant's flow manager.

Covers success, input errors, metadata and connectivity failures, search
again, duplicate places and reconfigure. Only the network is replaced
(`meteoswiss_api`). Needs pytest-homeassistant-custom-component (Linux).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swissweather.config_flow import (
    NO_POLLEN_STATION_OPTION,
    NO_WEATHER_STATION_OPTION,
    SEARCH_AGAIN_OPTION,
)
from custom_components.swissweather.const import (
    CONF_FORECAST_NAME,
    CONF_POLLEN_STATION_CODE,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_WARNINGS_ENABLED,
    DOMAIN,
)
from custom_components.swissweather.forecast_points import FORECAST_POINT_LIST_URL
from custom_components.swissweather.meteo import FORECAST_URL

QUERY = "forecast_query"
POINT = "forecast_point"


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _step(hass: HomeAssistant, flow_id: str, data: dict):
    return await hass.config_entries.flow.async_configure(flow_id, data)


async def test_full_flow_creates_an_entry(hass, meteoswiss_api):
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await _step(hass, result["flow_id"], {QUERY: "8001"})
    assert result["step_id"] == "forecast_pick"

    result = await _step(hass, result["flow_id"], {POINT: "800100"})
    assert result["step_id"] == "details"

    result = await _step(
        hass,
        result["flow_id"],
        {CONF_STATION_CODE: "SMA", CONF_POLLEN_STATION_CODE: "PZH", CONF_WARNINGS_ENABLED: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_POST_CODE] == "800100"
    assert data[CONF_STATION_CODE] == "SMA"
    assert data[CONF_POLLEN_STATION_CODE] == "PZH"
    assert data[CONF_FORECAST_NAME]
    assert result["result"].unique_id == "swissweather_800100"


async def test_flow_without_stations_stores_none(hass, meteoswiss_api):
    result = await _start(hass)
    result = await _step(hass, result["flow_id"], {QUERY: "Wetzikon"})
    result = await _step(hass, result["flow_id"], {POINT: "862000"})
    result = await _step(
        hass,
        result["flow_id"],
        {
            CONF_STATION_CODE: NO_WEATHER_STATION_OPTION,
            CONF_POLLEN_STATION_CODE: NO_POLLEN_STATION_OPTION,
            CONF_WARNINGS_ENABLED: False,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATION_CODE] is None
    assert result["data"][CONF_POLLEN_STATION_CODE] is None
    assert result["data"][CONF_WARNINGS_ENABLED] is False


@pytest.mark.parametrize(
    ("query", "error"),
    [
        ("", "forecast_query_required"),
        ("x", "forecast_query_too_short"),
        ("Atlantis", "forecast_query_not_found"),
    ],
)
async def test_search_errors(hass, meteoswiss_api, query, error):
    result = await _start(hass)

    result = await _step(hass, result["flow_id"], {QUERY: query})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {QUERY: error}


async def test_unavailable_forecast_point_metadata(hass, meteoswiss_api):
    meteoswiss_api.fail(FORECAST_POINT_LIST_URL)
    result = await _start(hass)

    result = await _step(hass, result["flow_id"], {QUERY: "8001"})

    assert result["errors"] == {QUERY: "forecast_query_metadata_unavailable"}


async def test_search_again_returns_to_the_search_form(hass, meteoswiss_api):
    result = await _start(hass)
    result = await _step(hass, result["flow_id"], {QUERY: "Wetzikon"})

    result = await _step(hass, result["flow_id"], {POINT: SEARCH_AGAIN_OPTION})

    assert result["step_id"] == "user"


async def test_unreachable_forecast_blocks_entry_creation(hass, meteoswiss_api):
    result = await _start(hass)
    result = await _step(hass, result["flow_id"], {QUERY: "8001"})
    result = await _step(hass, result["flow_id"], {POINT: "800100"})
    meteoswiss_api.fail(FORECAST_URL.format("800100"))

    result = await _step(
        hass,
        result["flow_id"],
        {
            CONF_STATION_CODE: NO_WEATHER_STATION_OPTION,
            CONF_POLLEN_STATION_CODE: NO_POLLEN_STATION_OPTION,
            CONF_WARNINGS_ENABLED: True,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured_place_aborts(hass, meteoswiss_api):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="swissweather_800100",
        data={CONF_POST_CODE: "800100"},
        version=2,
    ).add_to_hass(hass)
    result = await _start(hass)
    result = await _step(hass, result["flow_id"], {QUERY: "8001"})

    result = await _step(hass, result["flow_id"], {POINT: "800100"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_stations(hass, meteoswiss_api):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="swissweather_800100",
        version=2,
        data={
            CONF_POST_CODE: "800100",
            "forecastPointType": "2",
            CONF_FORECAST_NAME: "Zürich",
            CONF_STATION_CODE: "SMA",
            CONF_POLLEN_STATION_CODE: "PZH",
            CONF_WARNINGS_ENABLED: True,
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await _step(
        hass,
        result["flow_id"],
        {
            CONF_STATION_CODE: "TAE",
            CONF_POLLEN_STATION_CODE: NO_POLLEN_STATION_OPTION,
            CONF_WARNINGS_ENABLED: True,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_STATION_CODE] == "TAE"
    assert entry.data[CONF_POLLEN_STATION_CODE] is None
    assert entry.data[CONF_POST_CODE] == "800100"
