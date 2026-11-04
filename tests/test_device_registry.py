"""Device cleanup and naming against the real Home Assistant registries.

These replace stand-in registries that modelled the pre-2026.8 API and so
could not notice its deprecation. They need pytest-homeassistant-custom-component
(Linux only) and run in CI.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteoswiss_forecast_warnings.__init__ import (
    _async_cleanup_legacy_devices,
    _async_cleanup_optional_devices,
    _async_sync_entry_device_names,
)
from custom_components.meteoswiss_forecast_warnings.const import (
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    DOMAIN,
)


def _entry(hass: HomeAssistant, entry_id: str, **data) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id, data=data)
    entry.add_to_hass(hass)
    return entry


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str, **kwargs):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, identifier)}, **kwargs
    )


def _entity(hass: HomeAssistant, entry: MockConfigEntry, device, unique_id: str):
    return er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, unique_id, config_entry=entry, device_id=device.id
    )


@pytest.fixture(autouse=True)
def _no_deprecated_registry_use(caplog):
    """Fail if the code under test triggers a Home Assistant deprecation report."""
    caplog.set_level(logging.WARNING)
    yield
    reports = [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage()]
    assert not reports, reports


async def test_unconfigured_optional_devices_are_removed_with_their_entities(hass):
    entry = _entry(
        hass, "entry-1",
        **{CONF_POST_CODE: "650000", CONF_STATION_CODE: None, CONF_POLLEN_STATION_CODE: None},
    )
    weather = _device(hass, entry, "entry-1-weather-station")
    pollen = _device(hass, entry, "entry-1-pollen-station")
    forecast = _device(hass, entry, "entry-1-forecast")
    _entity(hass, entry, weather, "650000.temperature")
    _entity(hass, entry, pollen, "650000.birch")

    await _async_cleanup_optional_devices(hass, entry)

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(weather.id) is None
    assert device_registry.async_get(pollen.id) is None
    assert device_registry.async_get(forecast.id) is not None
    assert er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) == []


async def test_optional_device_cleanup_leaves_other_entries_alone(hass):
    """Identifiers are only unique per config entry since HA 2026.8."""
    entry = _entry(hass, "entry-1", **{CONF_POST_CODE: "650000", CONF_STATION_CODE: None})
    other = _entry(hass, "entry-2", **{CONF_POST_CODE: "862000", CONF_STATION_CODE: "PFA"})
    # Same identifier string, owned by another entry.
    foreign = _device(hass, other, "entry-1-weather-station")

    await _async_cleanup_optional_devices(hass, entry)

    assert dr.async_get(hass).async_get(foreign.id) is not None


@pytest.mark.parametrize(
    ("post_code", "station", "legacy_identifier"),
    [("8803", "KLO", "swissweather-8803-KLO"), ("7320", None, "swissweather-7320")],
)
async def test_empty_legacy_device_is_removed(hass, post_code, station, legacy_identifier):
    entry = _entry(hass, "entry-legacy", **{CONF_POST_CODE: post_code, CONF_STATION_CODE: station})
    legacy = _device(hass, entry, legacy_identifier)

    await _async_cleanup_legacy_devices(hass, entry)

    assert dr.async_get(hass).async_get(legacy.id) is None


async def test_legacy_device_with_entities_is_kept(hass):
    entry = _entry(hass, "entry-legacy", **{CONF_POST_CODE: "7320", CONF_STATION_CODE: "GLA"})
    legacy = _device(hass, entry, "swissweather-7320-GLA")
    _entity(hass, entry, legacy, "7320.temperature")

    await _async_cleanup_legacy_devices(hass, entry)

    assert dr.async_get(hass).async_get(legacy.id) is not None


async def test_legacy_cleanup_ignores_devices_of_other_entries(hass):
    entry = _entry(hass, "entry-legacy", **{CONF_POST_CODE: "7320", CONF_STATION_CODE: None})
    other = _entry(hass, "entry-other", **{CONF_POST_CODE: "7320", CONF_STATION_CODE: None})
    foreign = _device(hass, other, "swissweather-7320")

    await _async_cleanup_legacy_devices(hass, entry)

    assert dr.async_get(hass).async_get(foreign.id) is not None


async def test_device_names_follow_the_config_entry(hass):
    entry = _entry(hass, "entry-1", **{CONF_POLLEN_STATION_NAME: "Davos / Wolfgang GR"})
    pollen = _device(hass, entry, "entry-1-pollen-station", name="Davos / Wolfgang")

    await _async_sync_entry_device_names(hass, entry)

    assert dr.async_get(hass).async_get(pollen.id).name == "Davos / Wolfgang GR"


async def test_device_names_keep_a_user_chosen_name(hass):
    entry = _entry(hass, "entry-1", **{CONF_POLLEN_STATION_NAME: "Davos / Wolfgang GR"})
    pollen = _device(hass, entry, "entry-1-pollen-station", name="Davos / Wolfgang")
    dr.async_get(hass).async_update_device(pollen.id, name_by_user="Pollen Davos")

    await _async_sync_entry_device_names(hass, entry)

    device = dr.async_get(hass).async_get(pollen.id)
    assert device.name == "Davos / Wolfgang"
    assert device.name_by_user == "Pollen Davos"
