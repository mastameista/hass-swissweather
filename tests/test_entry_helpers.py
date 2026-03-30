from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.__init__ import (
    _async_cleanup_legacy_devices,
    _async_cleanup_disabled_warning_entities,
    _async_ensure_entry_names,
    _async_ensure_entry_unique_id,
    _async_migrate_warning_config,
    _async_sync_entry_device_names,
    _async_sync_repairs_issues,
    SwissWeatherMetadata,
    async_migrate_entry,
    async_setup_entry,
)
from custom_components.swissweather.const import (
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
    CONF_WEATHER_WARNINGS_NUMBER,
    DOMAIN,
)
from custom_components.swissweather.forecast_points import ForecastPoint
from custom_components.swissweather.station_lookup import WeatherStation
from custom_components.swissweather.naming import build_entry_unique_id


class FakeConfigEntries:
    def __init__(self, entries: list[SimpleNamespace] | None = None) -> None:
        self._entries = entries or []
        self.async_update_entry = Mock()

    def async_entries(self, domain: str) -> list[SimpleNamespace]:
        assert domain == DOMAIN
        return list(self._entries)


class FakeEntityRegistry:
    def __init__(self, entities: list[SimpleNamespace]) -> None:
        self.entities = {entity.entity_id: entity for entity in entities}
        self.removed: list[str] = []

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)


class FakeDeviceRegistry:
    def __init__(self, devices: dict[str, SimpleNamespace]) -> None:
        self._devices = devices
        self.devices = {
            device.id: SimpleNamespace(
                id=device.id,
                identifiers={(DOMAIN, identifier)},
                config_entries=getattr(device, "config_entries", []),
                name=getattr(device, "name", None),
                name_by_user=getattr(device, "name_by_user", None),
            )
            for identifier, device in devices.items()
        }
        self.removed: list[str] = []
        self.updated: list[tuple[str, str]] = []

    def async_get_device(self, *, identifiers, connections):
        del connections
        identifier = next(iter(identifiers))[1]
        device = self._devices.get(identifier)
        if device is None:
            return None
        return self.devices[device.id]

    def async_remove_device(self, device_id: str) -> None:
        self.removed.append(device_id)

    def async_update_device(self, device_id: str, **kwargs) -> None:
        if "name" in kwargs:
            self.devices[device_id].name = kwargs["name"]
            self.updated.append((device_id, kwargs["name"]))


def test_migrate_warning_config_replaces_legacy_count():
    entry = SimpleNamespace(
        data={CONF_POST_CODE: "8620", CONF_WEATHER_WARNINGS_NUMBER: 0},
        entry_id="entry-1",
    )
    hass = SimpleNamespace(config_entries=FakeConfigEntries())

    updated_entry = asyncio.run(_async_migrate_warning_config(hass, entry))

    assert updated_entry is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={CONF_POST_CODE: "8620", CONF_WARNINGS_ENABLED: False},
    )


def test_ensure_entry_unique_id_backfills_missing_unique_id():
    entry = SimpleNamespace(data={CONF_POST_CODE: "6500"}, entry_id="entry-1", unique_id=None)
    hass = SimpleNamespace(config_entries=FakeConfigEntries([entry]))

    updated_entry = asyncio.run(_async_ensure_entry_unique_id(hass, entry))

    assert updated_entry is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        unique_id=build_entry_unique_id("6500"),
    )


def test_ensure_entry_unique_id_skips_when_duplicate_exists():
    entry = SimpleNamespace(data={CONF_POST_CODE: "6500"}, entry_id="entry-1", unique_id=None)
    duplicate = SimpleNamespace(
        data={CONF_POST_CODE: "6500"},
        entry_id="entry-2",
        unique_id=build_entry_unique_id("6500"),
    )
    hass = SimpleNamespace(config_entries=FakeConfigEntries([entry, duplicate]))

    updated_entry = asyncio.run(_async_ensure_entry_unique_id(hass, entry))

    assert updated_entry is entry
    hass.config_entries.async_update_entry.assert_not_called()


def test_cleanup_disabled_warning_entities_only_removes_current_entry(monkeypatch):
    target_entry = SimpleNamespace(
        data={CONF_POST_CODE: "6500", CONF_WARNINGS_ENABLED: False},
        entry_id="entry-1",
    )
    other_entry = SimpleNamespace(
        data={CONF_POST_CODE: "6500", CONF_WARNINGS_ENABLED: True},
        entry_id="entry-2",
    )
    registry = FakeEntityRegistry(
        [
            SimpleNamespace(
                platform=DOMAIN,
                config_entry_id="entry-1",
                unique_id="6500.primary_warning",
                entity_id="sensor.bellinzona_primary_weather_warning",
            ),
            SimpleNamespace(
                platform=DOMAIN,
                config_entry_id="entry-2",
                unique_id="6500.primary_warning",
                entity_id="sensor.bellinzona_primary_weather_warning_duplicate",
            ),
        ]
    )

    from custom_components.swissweather import __init__ as init_module

    monkeypatch.setattr(init_module.er, "async_get", lambda hass: registry)

    asyncio.run(
        _async_cleanup_disabled_warning_entities(SimpleNamespace(), target_entry)
    )

    assert registry.removed == ["sensor.bellinzona_primary_weather_warning"]
    assert "sensor.bellinzona_primary_weather_warning_duplicate" not in registry.removed


def test_async_migrate_entry_bumps_major_version():
    entry = SimpleNamespace(entry_id="entry-1", version=1)
    hass = SimpleNamespace(config_entries=FakeConfigEntries())

    result = asyncio.run(async_migrate_entry(hass, entry))

    assert result is True
    hass.config_entries.async_update_entry.assert_called_once_with(entry, version=2)


def test_async_migrate_entry_rejects_future_version():
    entry = SimpleNamespace(entry_id="entry-1", version=3)
    hass = SimpleNamespace(config_entries=FakeConfigEntries())

    result = asyncio.run(async_migrate_entry(hass, entry))

    assert result is False
    hass.config_entries.async_update_entry.assert_not_called()


def test_ensure_entry_names_backfills_forecast_name_from_legacy_postal_code():
    entry = SimpleNamespace(
        data={CONF_POST_CODE: "8803"},
        title="MeteoSwiss 8803",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    metadata = SwissWeatherMetadata(
        forecast_points=[
            ForecastPoint("880300", "2", "8803", "Zürich", "ZIP", 0, 0.0, 0.0)
        ],
        weather_stations=[],
        pollen_stations=[],
    )

    result = asyncio.run(_async_ensure_entry_names(hass, entry, metadata))

    assert result is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            CONF_POST_CODE: "8803",
            "forecastPointType": "2",
            "forecastName": "Zürich",
            "warningsEnabled": True,
        },
        title="MeteoSwiss Zürich",
    )

def test_ensure_entry_names_backfills_pollen_station_name_with_canton():
    entry = SimpleNamespace(
        data={
            CONF_POST_CODE: "8001",
            CONF_POLLEN_STATION_CODE: "PZH",
        },
        title="MeteoSwiss 8001",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    metadata = SwissWeatherMetadata(
        forecast_points=[],
        weather_stations=[],
        pollen_stations=[WeatherStation("ZÃ¼rich", "PZH", 0, 0.0, 0.0, "ZH")],
    )

    result = asyncio.run(_async_ensure_entry_names(hass, entry, metadata))

    assert result is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            CONF_POST_CODE: "8001",
            CONF_POLLEN_STATION_CODE: "PZH",
            CONF_POLLEN_STATION_NAME: "ZÃ¼rich ZH",
            "forecastName": "8001",
            "warningsEnabled": True,
        },
        title="MeteoSwiss 8001 / ZÃ¼rich ZH",
    )


def test_ensure_entry_names_refreshes_existing_station_and_pollen_names():
    entry = SimpleNamespace(
        data={
            CONF_POST_CODE: "7320",
            CONF_STATION_CODE: "GLA",
            CONF_STATION_NAME: "Glarus",
            CONF_POLLEN_STATION_CODE: "PDS",
            CONF_POLLEN_STATION_NAME: "Davos / Wolfgang",
        },
        title="MeteoSwiss Sargans / Glarus / Davos / Wolfgang",
    )
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    metadata = SwissWeatherMetadata(
        forecast_points=[],
        weather_stations=[WeatherStation("Glarus", "GLA", 0, 0.0, 0.0, "GL")],
        pollen_stations=[WeatherStation("Davos / Wolfgang", "PDS", 0, 0.0, 0.0, "GR")],
    )

    result = asyncio.run(_async_ensure_entry_names(hass, entry, metadata))

    assert result is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            CONF_POST_CODE: "7320",
            CONF_STATION_CODE: "GLA",
            CONF_STATION_NAME: "Glarus GL",
            CONF_POLLEN_STATION_CODE: "PDS",
            CONF_POLLEN_STATION_NAME: "Davos / Wolfgang GR",
            "forecastName": "7320",
            "warningsEnabled": True,
        },
        title="MeteoSwiss 7320 / Glarus GL / Davos / Wolfgang GR",
    )


def test_cleanup_legacy_devices_removes_empty_upstream_device(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    device_registry = FakeDeviceRegistry(
        {
            "swissweather-8803-KLO": SimpleNamespace(id="legacy-device"),
        }
    )
    entity_registry = FakeEntityRegistry([])

    monkeypatch.setattr(init_module.dr, "async_get", lambda hass: device_registry)
    monkeypatch.setattr(init_module.er, "async_get", lambda hass: entity_registry)
    monkeypatch.setattr(
        init_module.er,
        "async_entries_for_device",
        lambda registry, device_id, include_disabled_entities=True: [],
    )

    entry = SimpleNamespace(
        data={CONF_POST_CODE: "8803", "stationCode": "KLO"},
        entry_id="entry-legacy",
    )

    asyncio.run(_async_cleanup_legacy_devices(SimpleNamespace(), entry))

    assert device_registry.removed == ["legacy-device"]


def test_cleanup_legacy_devices_removes_active_legacy_device_without_entities(
    monkeypatch,
):
    from custom_components.swissweather import __init__ as init_module

    device_registry = FakeDeviceRegistry(
        {
            "swissweather-7320-GLA": SimpleNamespace(
                id="legacy-active-device",
                config_entries=["entry-legacy"],
            ),
        }
    )
    entity_registry = FakeEntityRegistry([])

    monkeypatch.setattr(init_module.dr, "async_get", lambda hass: device_registry)
    monkeypatch.setattr(init_module.er, "async_get", lambda hass: entity_registry)
    monkeypatch.setattr(
        init_module.er,
        "async_entries_for_device",
        lambda registry, device_id, include_disabled_entities=True: [],
    )

    entry = SimpleNamespace(
        data={CONF_POST_CODE: "7320", "stationCode": "GLA"},
        entry_id="entry-legacy",
    )

    asyncio.run(_async_cleanup_legacy_devices(SimpleNamespace(), entry))

    assert device_registry.removed == ["legacy-active-device"]


def test_sync_entry_device_names_updates_existing_pollen_device(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    device_registry = FakeDeviceRegistry(
        {
            "entry-1-pollen-station": SimpleNamespace(
                id="pollen-device",
                name="Davos / Wolfgang",
            ),
        }
    )

    monkeypatch.setattr(init_module.dr, "async_get", lambda hass: device_registry)

    entry = SimpleNamespace(
        entry_id="entry-1",
        data={CONF_POLLEN_STATION_NAME: "Davos / Wolfgang GR"},
    )

    asyncio.run(_async_sync_entry_device_names(SimpleNamespace(), entry))

    assert device_registry.updated == [("pollen-device", "Davos / Wolfgang GR")]


def test_async_setup_entry_rechecks_legacy_devices_after_platform_setup(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    cleanup_calls: list[str] = []
    call_order: list[str] = []
    entry = SimpleNamespace(data={}, entry_id="entry-1")
    metadata = SwissWeatherMetadata([], [], [])

    async def passthrough_step(hass, current_entry, *args):
        del hass, args
        return current_entry

    async def fake_load_metadata(hass, current_entry):
        del hass
        assert current_entry is entry
        return metadata

    async def fake_cleanup_legacy_devices(hass, current_entry):
        del hass
        assert current_entry is entry
        cleanup_calls.append(current_entry.entry_id)
        call_order.append(f"cleanup-{len(cleanup_calls)}")

    async def fake_sync_entry_device_names(hass, current_entry):
        del hass
        assert current_entry is entry
        call_order.append("sync-device-names")

    async def fake_noop(hass, current_entry):
        del hass, current_entry
        return None

    class FakeCoordinator:
        def __init__(self, hass, current_entry):
            del hass
            assert current_entry is entry

        async def async_config_entry_first_refresh(self):
            call_order.append("refresh")

    async def fake_forward_entry_setups(current_entry, platforms):
        assert current_entry is entry
        assert list(platforms) == list(init_module.PLATFORMS)
        call_order.append("forward")

    monkeypatch.setattr(init_module, "_async_migrate_warning_config", passthrough_step)
    monkeypatch.setattr(init_module, "_async_ensure_entry_unique_id", passthrough_step)
    monkeypatch.setattr(init_module, "_async_load_metadata", fake_load_metadata)
    monkeypatch.setattr(init_module, "_async_ensure_entry_names", passthrough_step)
    monkeypatch.setattr(init_module, "_async_sync_repairs_issues", lambda hass, current_entry, current_metadata: None)
    monkeypatch.setattr(init_module, "_async_cleanup_legacy_devices", fake_cleanup_legacy_devices)
    monkeypatch.setattr(init_module, "_async_sync_entry_device_names", fake_sync_entry_device_names)
    monkeypatch.setattr(init_module, "_async_cleanup_optional_devices", fake_noop)
    monkeypatch.setattr(init_module, "_async_cleanup_legacy_warning_entities", fake_noop)
    monkeypatch.setattr(init_module, "_async_cleanup_disabled_warning_entities", fake_noop)
    monkeypatch.setattr(init_module, "SwissWeatherDataCoordinator", FakeCoordinator)
    monkeypatch.setattr(init_module, "SwissPollenDataCoordinator", FakeCoordinator)

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(side_effect=fake_forward_entry_setups))
    )

    result = asyncio.run(async_setup_entry(hass, entry))

    assert result is True
    assert cleanup_calls == ["entry-1", "entry-1"]
    assert call_order == [
        "cleanup-1",
        "refresh",
        "refresh",
        "forward",
        "sync-device-names",
        "cleanup-2",
    ]


def test_sync_repairs_issues_creates_issue_for_missing_forecast_point(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    created: list[tuple[str, str, dict]] = []
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        init_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append((domain, issue_id, kwargs)),
    )
    monkeypatch.setattr(
        init_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )

    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Bellinzona",
        data={CONF_POST_CODE: "9999"},
    )
    metadata = SwissWeatherMetadata(
        forecast_points=[
            ForecastPoint("6500", "2", "6500", "Bellinzona", "ZIP", 0, 0.0, 0.0)
        ],
        weather_stations=[],
        pollen_stations=[],
    )

    _async_sync_repairs_issues(SimpleNamespace(), entry, metadata)

    assert created[0][0] == DOMAIN
    assert created[0][1] == "missing_forecast_point_entry-1"
    assert created[0][2]["translation_key"] == "missing_forecast_point"
    assert created[0][2]["translation_placeholders"]["post_code"] == "9999"
    assert ("swissweather", "missing_weather_station_entry-1") in deleted
    assert ("swissweather", "missing_pollen_station_entry-1") in deleted


def test_sync_repairs_issues_clears_weather_issue_when_station_exists(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    created: list[tuple[str, str, dict]] = []
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        init_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append((domain, issue_id, kwargs)),
    )
    monkeypatch.setattr(
        init_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )

    entry = SimpleNamespace(
        entry_id="entry-2",
        title="Bellinzona",
        data={CONF_POST_CODE: "6500", "stationCode": "BAS"},
    )
    metadata = SwissWeatherMetadata(
        forecast_points=[
            ForecastPoint("6500", "2", "6500", "Bellinzona", "ZIP", 0, 0.0, 0.0)
        ],
        weather_stations=[
            WeatherStation("Biasca, TI", "BAS", 0, 0.0, 0.0, "TI")
        ],
        pollen_stations=[],
    )

    _async_sync_repairs_issues(SimpleNamespace(), entry, metadata)

    assert created == []
    assert ("swissweather", "missing_forecast_point_entry-2") in deleted
    assert ("swissweather", "missing_weather_station_entry-2") in deleted


def test_sync_repairs_issues_accepts_legacy_postal_code_forecast_match(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    created: list[tuple[str, str, dict]] = []
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        init_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append((domain, issue_id, kwargs)),
    )
    monkeypatch.setattr(
        init_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )

    entry = SimpleNamespace(
        entry_id="entry-legacy-postal",
        title="MeteoSwiss 8803",
        data={CONF_POST_CODE: "8803"},
    )
    metadata = SwissWeatherMetadata(
        forecast_points=[
            ForecastPoint("880300", "2", "8803", "Zürich", "ZIP", 0, 0.0, 0.0)
        ],
        weather_stations=[],
        pollen_stations=[],
    )

    _async_sync_repairs_issues(SimpleNamespace(), entry, metadata)

    assert created == []
    assert ("swissweather", "missing_forecast_point_entry-legacy-postal") in deleted


def test_sync_repairs_issues_keeps_existing_issues_when_metadata_unknown(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    created: list[tuple[str, str, dict]] = []
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        init_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append((domain, issue_id, kwargs)),
    )
    monkeypatch.setattr(
        init_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )

    entry = SimpleNamespace(
        entry_id="entry-3",
        title="Bellinzona",
        data={CONF_POST_CODE: "6500", "stationCode": "BAS", "pollenStationCode": "BAS"},
    )
    metadata = SwissWeatherMetadata(
        forecast_points=[],
        weather_stations=[],
        pollen_stations=[],
        forecast_points_loaded=False,
        weather_stations_loaded=False,
        pollen_stations_loaded=False,
    )

    _async_sync_repairs_issues(SimpleNamespace(), entry, metadata)

    assert created == []
    assert deleted == []


def test_sync_repairs_issues_ignores_unconfigured_pollen_station(monkeypatch):
    from custom_components.swissweather import __init__ as init_module

    created: list[tuple[str, str, dict]] = []
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        init_module.ir,
        "async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append((domain, issue_id, kwargs)),
    )
    monkeypatch.setattr(
        init_module.ir,
        "async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )

    entry = SimpleNamespace(
        entry_id="entry-4",
        title="Sevelen",
        data={
            CONF_POST_CODE: "9475",
            "stationCode": "VAD",
            "pollenStationCode": None,
        },
    )
    metadata = SwissWeatherMetadata(
        forecast_points=[SimpleNamespace(point_id="9475")],
        weather_stations=[SimpleNamespace(code="VAD")],
        pollen_stations=[SimpleNamespace(code="BAS")],
        pollen_stations_loaded=False,
    )

    _async_sync_repairs_issues(SimpleNamespace(), entry, metadata)

    assert created == []
    assert ("swissweather", "missing_pollen_station_entry-4") in deleted
