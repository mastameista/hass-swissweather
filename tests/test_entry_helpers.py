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
    async_migrate_entry,
)
from custom_components.swissweather.const import (
    CONF_POST_CODE,
    CONF_WARNINGS_ENABLED,
    CONF_WEATHER_WARNINGS_NUMBER,
    DOMAIN,
)
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
