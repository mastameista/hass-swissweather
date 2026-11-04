from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings.__init__ import (
    SwissWeatherMetadata,
    _async_cleanup_disabled_warning_entities,
    _async_ensure_entry_names,
    _async_ensure_entry_unique_id,
    _async_migrate_warning_config,
    _async_sync_repairs_issues,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.meteoswiss_forecast_warnings.const import (
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
    CONF_WEATHER_WARNINGS_NUMBER,
    DOMAIN,
)
from custom_components.meteoswiss_forecast_warnings.forecast_points import ForecastPoint
from custom_components.meteoswiss_forecast_warnings.naming import build_entry_unique_id
from custom_components.meteoswiss_forecast_warnings.station_lookup import WeatherStation


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





def test_migrate_warning_config_replaces_legacy_count():
    entry = SimpleNamespace(
        data={CONF_POST_CODE: "8107", CONF_WEATHER_WARNINGS_NUMBER: 0},
        entry_id="entry-1",
    )
    hass = SimpleNamespace(config_entries=FakeConfigEntries())

    updated_entry = asyncio.run(_async_migrate_warning_config(hass, entry))

    assert updated_entry is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={CONF_POST_CODE: "8107", CONF_WARNINGS_ENABLED: False},
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

    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
        pollen_stations=[WeatherStation("Zürich", "PZH", 0, 0.0, 0.0, "ZH")],
    )

    result = asyncio.run(_async_ensure_entry_names(hass, entry, metadata))

    assert result is entry
    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            CONF_POST_CODE: "8001",
            CONF_POLLEN_STATION_CODE: "PZH",
            CONF_POLLEN_STATION_NAME: "Zürich ZH",
            "forecastName": "8001",
            "warningsEnabled": True,
        },
        title="MeteoSwiss 8001 / Zürich ZH",
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


@pytest.mark.parametrize(
    ("entry_data", "expected_refreshes", "expect_pollen_coordinator"),
    [
        ({}, ["refresh-weather"], False),
        (
            {CONF_POLLEN_STATION_CODE: "PBE"},
            ["refresh-weather", "refresh-pollen"],
            True,
        ),
    ],
    ids=["without-pollen-station", "with-pollen-station"],
)
def test_async_setup_entry_rechecks_legacy_devices_after_platform_setup(
    monkeypatch, entry_data, expected_refreshes, expect_pollen_coordinator
):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

    cleanup_calls: list[str] = []
    call_order: list[str] = []
    entry = SimpleNamespace(data=entry_data, entry_id="entry-1")
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
        label = ""

        def __init__(self, hass, current_entry):
            del hass
            assert current_entry is entry

        async def async_config_entry_first_refresh(self):
            call_order.append(f"refresh-{self.label}")

    class FakeWeatherCoordinator(FakeCoordinator):
        label = "weather"

    class FakePollenCoordinator(FakeCoordinator):
        label = "pollen"

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
    monkeypatch.setattr(init_module, "_async_sync_legacy_integration_issue", AsyncMock())
    monkeypatch.setattr(init_module, "_async_cleanup_legacy_warning_entities", fake_noop)
    monkeypatch.setattr(init_module, "_async_cleanup_disabled_warning_entities", fake_noop)
    monkeypatch.setattr(init_module, "SwissWeatherDataCoordinator", FakeWeatherCoordinator)
    monkeypatch.setattr(init_module, "SwissPollenDataCoordinator", FakePollenCoordinator)

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(side_effect=fake_forward_entry_setups))
    )

    result = asyncio.run(async_setup_entry(hass, entry))

    assert result is True
    assert cleanup_calls == ["entry-1", "entry-1"]
    assert call_order == [
        "cleanup-1",
        *expected_refreshes,
        "forward",
        "sync-device-names",
        "cleanup-2",
    ]
    # Without a pollen station no pollen coordinator is created at all, so no
    # idle hourly refresh is scheduled for it.
    assert (entry.runtime_data.pollen_coordinator is not None) is expect_pollen_coordinator


def test_sync_repairs_issues_creates_issue_for_missing_forecast_point(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
    assert (DOMAIN, "missing_weather_station_entry-1") in deleted
    assert (DOMAIN, "missing_pollen_station_entry-1") in deleted


def test_sync_repairs_issues_clears_weather_issue_when_station_exists(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
    assert (DOMAIN, "missing_forecast_point_entry-2") in deleted
    assert (DOMAIN, "missing_weather_station_entry-2") in deleted


def test_sync_repairs_issues_accepts_legacy_postal_code_forecast_match(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
    assert (DOMAIN, "missing_forecast_point_entry-legacy-postal") in deleted


def test_sync_repairs_issues_keeps_existing_issues_when_metadata_unknown(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

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
    assert (DOMAIN, "missing_pollen_station_entry-4") in deleted


def test_async_unload_entry_delegates_to_platform_unload():
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_unload_platforms=AsyncMock(return_value=True)
        )
    )
    entry = SimpleNamespace(entry_id="entry-1")

    result = asyncio.run(async_unload_entry(hass, entry))

    assert result is True
    hass.config_entries.async_unload_platforms.assert_awaited_once()


def test_async_remove_config_entry_device_rejects_foreign_devices(monkeypatch):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

    monkeypatch.setattr(init_module.er, "async_get", lambda hass: object())
    monkeypatch.setattr(
        init_module.er,
        "async_entries_for_device",
        lambda registry, device_id, include_disabled_entities=True: [],
    )

    result = asyncio.run(
        async_remove_config_entry_device(
            SimpleNamespace(),
            SimpleNamespace(entry_id="entry-1"),
            SimpleNamespace(id="device-1", identifiers={("other", "device-1")}),
        )
    )

    assert result is False


def test_async_remove_config_entry_device_allows_orphaned_swissweather_devices(
    monkeypatch,
):
    from custom_components.meteoswiss_forecast_warnings import __init__ as init_module

    monkeypatch.setattr(init_module.er, "async_get", lambda hass: object())
    monkeypatch.setattr(
        init_module.er,
        "async_entries_for_device",
        lambda registry, device_id, include_disabled_entities=True: [],
    )

    result = asyncio.run(
        async_remove_config_entry_device(
            SimpleNamespace(),
            SimpleNamespace(entry_id="entry-1"),
            SimpleNamespace(id="device-1", identifiers={(DOMAIN, "entry-1-forecast")}),
        )
    )

    assert result is True
