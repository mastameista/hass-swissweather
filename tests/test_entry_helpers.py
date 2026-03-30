from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.__init__ import (
    _async_cleanup_disabled_warning_entities,
    _async_ensure_entry_unique_id,
    _async_migrate_warning_config,
    _async_sync_repairs_issues,
    SwissWeatherMetadata,
    async_migrate_entry,
)
from custom_components.swissweather.const import CONF_POST_CODE, CONF_WARNINGS_ENABLED, CONF_WEATHER_WARNINGS_NUMBER, DOMAIN
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
