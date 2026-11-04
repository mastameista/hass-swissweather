"""Taking over entries of the legacy swissweather integration.

Recreates an installation that runs the old domain: a loaded entry with
devices (one with an area and a user-chosen name) and entities with fixed
entity IDs. After the takeover everything must run under the new domain
with the same entity IDs, device IDs, areas and names. Needs
pytest-homeassistant-custom-component (Linux).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.meteoswiss_forecast_warnings.const import (
    CONF_FORECAST_NAME,
    CONF_FORECAST_POINT_TYPE,
    CONF_IMPORTED_FROM,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
    DOMAIN,
    LEGACY_DOMAIN,
)

LEGACY_DATA = {
    CONF_POST_CODE: "800100",
    CONF_FORECAST_POINT_TYPE: "2",
    CONF_FORECAST_NAME: "Zürich",
    CONF_STATION_CODE: "SMA",
    CONF_STATION_NAME: "Zürich / Fluntern ZH",
    CONF_WARNINGS_ENABLED: True,
}


class _LegacyConfigFlow(config_entries.ConfigFlow):
    """Stands in for the config flow of the legacy integration."""

    VERSION = 2


@pytest.fixture(autouse=True)
def legacy_config_flow():
    """Register a flow handler; HA sets up no entry of a domain without one."""
    with mock_config_flow(LEGACY_DOMAIN, _LegacyConfigFlow):
        yield


async def _legacy_installation(hass: HomeAssistant) -> MockConfigEntry:
    """A loaded swissweather entry with registered devices and entities."""
    mock_integration(
        hass,
        MockModule(
            LEGACY_DOMAIN,
            async_setup_entry=AsyncMock(return_value=True),
            async_unload_entry=AsyncMock(return_value=True),
        ),
    )
    mock_platform(hass, f"{LEGACY_DOMAIN}.config_flow", None)
    legacy = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        entry_id="legacy-1",
        unique_id="swissweather_800100",
        version=2,
        title="MeteoSwiss Zürich / Zürich / Fluntern ZH",
        data=LEGACY_DATA,
    )
    legacy.add_to_hass(hass)
    assert await hass.config_entries.async_setup(legacy.entry_id)
    assert legacy.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    garden = ar.async_get(hass).async_create("Garten")
    forecast = device_registry.async_get_or_create(
        config_entry_id=legacy.entry_id,
        identifiers={(LEGACY_DOMAIN, "legacy-1-forecast")},
        name="Zürich",
    )
    device_registry.async_update_device(
        forecast.id, area_id=garden.id, name_by_user="Wetter daheim"
    )
    station = device_registry.async_get_or_create(
        config_entry_id=legacy.entry_id,
        identifiers={(LEGACY_DOMAIN, "legacy-1-weather-station")},
        name="Zürich / Fluntern ZH",
    )
    for domain, unique_id, object_id, device in (
        ("weather", "swiss_weather.800100", "zurich", forecast),
        ("binary_sensor", "800100.has_warnings", "zurich_has_weather_warnings", forecast),
        ("sensor", "800100.temperature", "zurich_fluntern_temperature", station),
    ):
        entity_registry.async_get_or_create(
            domain,
            LEGACY_DOMAIN,
            unique_id,
            suggested_object_id=object_id,
            config_entry=legacy,
            device_id=device.id,
        )
    return legacy


async def test_takeover_keeps_entity_ids_devices_areas_and_names(hass, meteoswiss_api):
    legacy = await _legacy_installation(hass)
    device_registry = dr.async_get(hass)
    forecast_id = device_registry.async_get_device_by_identifier(
        (LEGACY_DOMAIN, "legacy-1-forecast"), legacy.entry_id
    ).id
    registry_ids = {
        entity.entity_id: entity.id
        for entity in er.async_entries_for_config_entry(er.async_get(hass), legacy.entry_id)
    }
    assert len(registry_ids) == 3

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "legacy"
    assert "Zürich" in result["description_placeholders"]["entries"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "take_over_legacy"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "legacy_take_over_started"
    await hass.async_block_till_done()

    # The legacy entry is gone; one entry of the new domain runs.
    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "swissweather_800100"
    assert CONF_IMPORTED_FROM not in entry.data

    # The registry entries were moved, not removed and created again: a
    # recreated entry gets a new ID and loses customisations and history links.
    entity_registry = er.async_get(hass)
    for entity_id, registry_id in registry_ids.items():
        registry_entry = entity_registry.async_get(entity_id)
        assert registry_entry is not None, entity_id
        assert registry_entry.id == registry_id, entity_id
        assert registry_entry.platform == DOMAIN
        assert registry_entry.config_entry_id == entry.entry_id
        assert hass.states.get(entity_id) is not None, entity_id
    assert float(hass.states.get("sensor.zurich_fluntern_temperature").state) == 16.0
    # No second copy was created next to the taken-over entity.
    assert entity_registry.async_get("sensor.zurich_fluntern_temperature_2") is None

    # The device keeps its ID, area and user-chosen name.
    forecast = device_registry.async_get(forecast_id)
    assert forecast.config_entry_id == entry.entry_id
    assert forecast.identifiers == {(DOMAIN, f"{entry.entry_id}-forecast")}
    assert forecast.name_by_user == "Wetter daheim"
    assert forecast.area_id is not None


async def test_menu_is_skipped_when_everything_was_taken_over(hass, meteoswiss_api):
    await _legacy_installation(hass)
    MockConfigEntry(
        domain=DOMAIN, unique_id="swissweather_800100", data=LEGACY_DATA, version=2
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_menu_offers_a_new_place_instead(hass, meteoswiss_api):
    await _legacy_installation(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_import_of_a_vanished_entry_aborts(hass, meteoswiss_api):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_IMPORT},
        data={CONF_IMPORTED_FROM: "does-not-exist"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "legacy_entry_missing"


async def test_remaining_legacy_integration_raises_a_repair_issue(hass, meteoswiss_api):
    legacy = await _legacy_installation(hass)
    with patch(
        "custom_components.meteoswiss_forecast_warnings.async_get_custom_components",
        AsyncMock(return_value={LEGACY_DOMAIN: object()}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "take_over_legacy"}
        )
        await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "legacy_integration_installed")
