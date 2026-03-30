"""The Swiss Weather integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.issue_registry import IssueSeverity

from .const import (
    CONF_FORECAST_POINT_TYPE,
    CONF_FORECAST_NAME,
    CONF_POLLEN_STATION_CODE,
    CONF_POLLEN_STATION_NAME,
    CONF_POST_CODE,
    CONF_STATION_CODE,
    CONF_STATION_NAME,
    CONF_WARNINGS_ENABLED,
    CONF_WEATHER_WARNINGS_NUMBER,
    DOMAIN,
)
from .coordinator import SwissPollenDataCoordinator, SwissWeatherDataCoordinator
from .forecast_points import (
    ForecastPoint,
    ForecastPointMetadataLoadError,
    async_load_forecast_point_list,
    find_forecast_point_by_id,
    find_forecast_point_by_stored_value,
)
from .naming import (
    build_entry_title,
    build_entry_unique_id,
    format_station_display_name,
)
from .station_lookup import (
    PollenStationMetadataLoadError,
    WeatherStation,
    WeatherStationMetadataLoadError,
    async_load_pollen_station_list,
    async_load_weather_station_list,
    find_station_by_code,
    split_place_and_canton,
)
from .pollen import PollenClient

_LOGGER = logging.getLogger(__name__)
ENTRY_VERSION = 2

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.WEATHER]
_LEGACY_WARNING_INDEX_RE = re.compile(
    r"^(?P<post_code>.+)\.warning(?:\.level)?\.(?P<index>\d+)$"
)
_LEGACY_WARNING_SUMMARY_RE = re.compile(r"^(?P<post_code>.+)\.warnings$")
_LEGACY_WARNING_ENTITY_RE = re.compile(
    r"^(?:binary_sensor|sensor)\.(?:"
    r".*_most_severe_weather_warning(?:_level)?|"
    r"most_severe_weather_warning(?:_level)?_at_\d+|"
    r".*_weather_warning_\d+(?:_level)?|"
    r".*_weather_warnings|"
    r"weather_warnings_at_\d+"
    r")$"
)
_WARNING_ENTITY_SUFFIXES = (
    "has_warnings",
    "warning_count",
    "highest_warning_level",
    "primary_warning",
    "secondary_warning",
    "tertiary_warning",
)
ISSUE_ID_MISSING_FORECAST_POINT = "missing_forecast_point"
ISSUE_ID_MISSING_WEATHER_STATION = "missing_weather_station"
ISSUE_ID_MISSING_POLLEN_STATION = "missing_pollen_station"
REPAIRS_LEARN_MORE_URL = "https://github.com/mastameista/hass-swissweather"


@dataclass
class SwissWeatherRuntimeData:
    """Runtime objects stored on the config entry."""

    weather_coordinator: SwissWeatherDataCoordinator
    pollen_coordinator: SwissPollenDataCoordinator


@dataclass
class SwissWeatherMetadata:
    """Cached metadata used during setup-time enrichment and validation."""

    forecast_points: list[ForecastPoint]
    weather_stations: list[WeatherStation]
    pollen_stations: list[WeatherStation]
    forecast_points_loaded: bool = True
    weather_stations_loaded: bool = True
    pollen_stations_loaded: bool = True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older Swiss Weather config entries."""
    _LOGGER.debug("Migrating Swiss Weather entry %s from version %s", entry.entry_id, entry.version)

    if entry.version > ENTRY_VERSION:
        _LOGGER.error(
            "Cannot migrate Swiss Weather entry %s from unsupported future version %s",
            entry.entry_id,
            entry.version,
        )
        return False

    if entry.version < ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=ENTRY_VERSION)

    _LOGGER.info(
        "Swiss Weather entry %s migration complete at version %s",
        entry.entry_id,
        entry.version,
    )
    return True


async def _async_remove_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_suffix: str
) -> None:
    """Remove an entry-owned device and all of its entities from the registries."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}-{device_suffix}")},
        connections=set(),
    )
    if device is None:
        return

    for entity_entry in er.async_entries_for_device(
        entity_registry, device.id, include_disabled_entities=True
    ):
        entity_registry.async_remove(entity_entry.entity_id)

    device_registry.async_remove_device(device.id)


async def _async_cleanup_optional_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove optional devices that are no longer configured."""
    if entry.data.get(CONF_POLLEN_STATION_CODE) is None:
        await _async_remove_entry_device(hass, entry, "pollen-station")


async def _async_cleanup_legacy_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove empty devices from the legacy upstream device model."""
    post_code = _coerce_config_value(entry.data.get(CONF_POST_CODE, ""))
    if not post_code:
        return

    station_code = _coerce_config_value(entry.data.get(CONF_STATION_CODE, ""))
    legacy_identifiers = {f"swissweather-{post_code}"}
    if station_code:
        legacy_identifiers.add(f"swissweather-{post_code}-{station_code}")

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    removed_count = 0

    devices_by_identifier: dict[str, object] = {}
    for device in getattr(device_registry, "devices", {}).values():
        for identifier in getattr(device, "identifiers", set()) or set():
            if not identifier or identifier[0] != DOMAIN:
                continue
            devices_by_identifier[str(identifier[1])] = device

    for legacy_identifier in legacy_identifiers:
        device = devices_by_identifier.get(legacy_identifier)
        if device is None:
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, legacy_identifier)},
                connections=set(),
            )
        if device is None:
            continue

        if not getattr(device, "config_entries", None):
            device_registry.async_remove_device(device.id)
            removed_count += 1
            continue

        device_entities = er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        )
        if device_entities:
            continue

        device_registry.async_remove_device(device.id)
        removed_count += 1

    if removed_count:
        _LOGGER.info("Removed %d empty legacy swissweather devices", removed_count)


async def _async_cleanup_legacy_warning_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove warning entities from the legacy numbered warning model."""
    entity_registry = er.async_get(hass)
    removed_count = 0
    for entity_entry in list(entity_registry.entities.values()):
        if entity_entry.platform != DOMAIN:
            continue
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        unique_id = entity_entry.unique_id or ""
        entity_id = entity_entry.entity_id or ""
        if entity_id.endswith("_has_weather_warnings"):
            continue
        if (
            _LEGACY_WARNING_INDEX_RE.match(unique_id)
            or _LEGACY_WARNING_SUMMARY_RE.match(unique_id)
            or _LEGACY_WARNING_ENTITY_RE.match(entity_id)
        ):
            entity_registry.async_remove(entity_entry.entity_id)
            removed_count += 1
    if removed_count:
        _LOGGER.info("Removed %d legacy swissweather warning entities", removed_count)


async def _async_cleanup_disabled_warning_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove current warning entities when warnings are disabled for the entry."""
    if entry.data.get(CONF_WARNINGS_ENABLED, True):
        return

    entity_registry = er.async_get(hass)
    post_code = str(entry.data.get(CONF_POST_CODE, "")).strip()
    if not post_code:
        return

    expected_unique_ids = {
        f"{post_code}.{suffix}" for suffix in _WARNING_ENTITY_SUFFIXES
    }
    removed_count = 0
    for entity_entry in list(entity_registry.entities.values()):
        if entity_entry.platform != DOMAIN:
            continue
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        if entity_entry.unique_id not in expected_unique_ids:
            continue
        entity_registry.async_remove(entity_entry.entity_id)
        removed_count += 1

    if removed_count:
        _LOGGER.info(
            "Removed %d swissweather warning entities because warnings are disabled",
            removed_count,
        )


async def _async_sync_entry_device_names(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Keep registry device names aligned with the current config entry names."""
    device_registry = dr.async_get(hass)
    expected_names = {
        f"{entry.entry_id}-forecast": entry.data.get(CONF_FORECAST_NAME),
        f"{entry.entry_id}-weather-station": entry.data.get(CONF_STATION_NAME),
        f"{entry.entry_id}-pollen-station": entry.data.get(CONF_POLLEN_STATION_NAME),
    }

    updated_count = 0
    for identifier, expected_name in expected_names.items():
        if not expected_name:
            continue

        device = device_registry.async_get_device(
            identifiers={(DOMAIN, identifier)},
            connections=set(),
        )
        if device is None or getattr(device, "name_by_user", None):
            continue
        if device.name == expected_name:
            continue

        device_registry.async_update_device(
            device.id,
            name=expected_name,
            new_identifiers=device.identifiers,
        )
        updated_count += 1

    if updated_count:
        _LOGGER.info("Updated %d swissweather device names from config entry metadata", updated_count)


async def _async_migrate_warning_config(
    hass: HomeAssistant, entry: ConfigEntry
) -> ConfigEntry:
    """Migrate warning settings from legacy warning count to a boolean toggle."""
    if CONF_WARNINGS_ENABLED in entry.data and CONF_WEATHER_WARNINGS_NUMBER not in entry.data:
        return entry

    legacy_value = entry.data.get(CONF_WEATHER_WARNINGS_NUMBER)
    warnings_enabled = True if legacy_value is None else int(legacy_value) >= 1
    merged_data = dict(entry.data)
    merged_data[CONF_WARNINGS_ENABLED] = warnings_enabled
    merged_data.pop(CONF_WEATHER_WARNINGS_NUMBER, None)
    hass.config_entries.async_update_entry(entry, data=merged_data)
    return entry


async def _async_ensure_entry_unique_id(
    hass: HomeAssistant, entry: ConfigEntry
) -> ConfigEntry:
    """Backfill a stable unique ID for existing config entries."""
    post_code = str(entry.data.get(CONF_POST_CODE, "")).strip()
    if not post_code:
        return entry

    expected_unique_id = build_entry_unique_id(post_code)
    if entry.unique_id == expected_unique_id:
        return entry

    for existing_entry in hass.config_entries.async_entries(DOMAIN):
        if existing_entry.entry_id == entry.entry_id:
            continue
        if existing_entry.unique_id == expected_unique_id:
            _LOGGER.warning(
                "Skipping unique_id backfill for entry %s because %s already uses %s",
                entry.entry_id,
                existing_entry.entry_id,
                expected_unique_id,
            )
            return entry

    hass.config_entries.async_update_entry(entry, unique_id=expected_unique_id)
    return entry


async def _async_load_metadata(
    hass: HomeAssistant, entry: ConfigEntry
) -> SwissWeatherMetadata:
    """Load setup-time metadata once for this entry."""
    session = async_get_clientsession(hass)
    forecast_points_loaded = True
    try:
        forecast_points = await async_load_forecast_point_list(
            session, raise_on_error=True
        )
    except ForecastPointMetadataLoadError:
        forecast_points = []
        forecast_points_loaded = False

    weather_stations: list[WeatherStation] = []
    weather_stations_loaded = True
    if entry.data.get(CONF_STATION_CODE):
        try:
            weather_stations = await async_load_weather_station_list(
                session, raise_on_error=True
            )
        except WeatherStationMetadataLoadError:
            weather_stations = []
            weather_stations_loaded = False

    pollen_stations: list[WeatherStation] = []
    pollen_stations_loaded = True
    if entry.data.get(CONF_POLLEN_STATION_CODE):
        try:
            pollen_stations = await async_load_pollen_station_list(
                PollenClient(session), raise_on_error=True
            )
        except PollenStationMetadataLoadError:
            pollen_stations = []
            pollen_stations_loaded = False

    return SwissWeatherMetadata(
        forecast_points=forecast_points,
        weather_stations=weather_stations,
        pollen_stations=pollen_stations,
        forecast_points_loaded=forecast_points_loaded,
        weather_stations_loaded=weather_stations_loaded,
        pollen_stations_loaded=pollen_stations_loaded,
    )


def _entry_issue_id(entry: ConfigEntry, issue_key: str) -> str:
    """Build a stable issue ID scoped to a config entry."""
    return f"{issue_key}_{entry.entry_id}"


def _coerce_config_value(value: object) -> str:
    """Return a normalized config-entry string value."""
    if value is None:
        return ""
    return str(value).strip()


def _async_update_metadata_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    issue_key: str,
    *,
    active: bool,
    translation_key: str,
    translation_placeholders: dict[str, str],
) -> None:
    """Create or clear a metadata repair issue for an entry."""
    issue_id = _entry_issue_id(entry, issue_key)
    if active:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            learn_more_url=REPAIRS_LEARN_MORE_URL,
            severity=IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders=translation_placeholders,
        )
        return
    ir.async_delete_issue(hass, DOMAIN, issue_id)


def _async_sync_repairs_issues(
    hass: HomeAssistant, entry: ConfigEntry, metadata: SwissWeatherMetadata
) -> None:
    """Create repairs issues for stale stored metadata references."""
    post_code = _coerce_config_value(entry.data.get(CONF_POST_CODE, ""))
    station_code = _coerce_config_value(entry.data.get(CONF_STATION_CODE, ""))
    pollen_station_code = _coerce_config_value(
        entry.data.get(CONF_POLLEN_STATION_CODE, "")
    )

    if metadata.forecast_points_loaded:
        forecast_missing = bool(
            post_code
            and find_forecast_point_by_stored_value(
                metadata.forecast_points,
                post_code,
                entry.data.get(CONF_FORECAST_POINT_TYPE),
            )
            is None
        )
        _async_update_metadata_issue(
            hass,
            entry,
            ISSUE_ID_MISSING_FORECAST_POINT,
            active=forecast_missing,
            translation_key=ISSUE_ID_MISSING_FORECAST_POINT,
            translation_placeholders={"post_code": post_code, "entry_title": entry.title},
        )

    if metadata.weather_stations_loaded:
        weather_missing = bool(
            station_code
            and find_station_by_code(metadata.weather_stations, station_code) is None
        )
        _async_update_metadata_issue(
            hass,
            entry,
            ISSUE_ID_MISSING_WEATHER_STATION,
            active=weather_missing,
            translation_key=ISSUE_ID_MISSING_WEATHER_STATION,
            translation_placeholders={"station_code": station_code, "entry_title": entry.title},
        )

    if not pollen_station_code:
        _async_update_metadata_issue(
            hass,
            entry,
            ISSUE_ID_MISSING_POLLEN_STATION,
            active=False,
            translation_key=ISSUE_ID_MISSING_POLLEN_STATION,
            translation_placeholders={"station_code": pollen_station_code, "entry_title": entry.title},
        )
    elif metadata.pollen_stations_loaded:
        pollen_missing = (
            find_station_by_code(metadata.pollen_stations, pollen_station_code) is None
        )
        _async_update_metadata_issue(
            hass,
            entry,
            ISSUE_ID_MISSING_POLLEN_STATION,
            active=pollen_missing,
            translation_key=ISSUE_ID_MISSING_POLLEN_STATION,
            translation_placeholders={"station_code": pollen_station_code, "entry_title": entry.title},
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Swiss Weather from a config entry."""
    entry = await _async_migrate_warning_config(hass, entry)
    entry = await _async_ensure_entry_unique_id(hass, entry)
    metadata = await _async_load_metadata(hass, entry)
    entry = await _async_ensure_entry_names(hass, entry, metadata)
    _async_sync_repairs_issues(hass, entry, metadata)
    await _async_cleanup_legacy_devices(hass, entry)
    await _async_cleanup_optional_devices(hass, entry)
    await _async_cleanup_legacy_warning_entities(hass, entry)
    await _async_cleanup_disabled_warning_entities(hass, entry)

    coordinator = SwissWeatherDataCoordinator(hass, entry)
    pollen_coordinator = SwissPollenDataCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    await pollen_coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SwissWeatherRuntimeData(
        weather_coordinator=coordinator,
        pollen_coordinator=pollen_coordinator,
    )
    _LOGGER.debug("Bootstrapped entry %s", entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_sync_entry_device_names(hass, entry)
    await _async_cleanup_legacy_devices(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing stale devices from the registry."""
    if not any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
        return False

    entity_registry = er.async_get(hass)
    device_entities = er.async_entries_for_device(
        entity_registry, device_entry.id, include_disabled_entities=True
    )
    return len(device_entities) == 0


async def _async_ensure_entry_names(
    hass: HomeAssistant,
    entry: ConfigEntry,
    metadata: SwissWeatherMetadata | None = None,
) -> ConfigEntry:
    """Populate cached display names in older config entries and keep the title in sync."""
    data_updates = {}
    if metadata is None:
        metadata = await _async_load_metadata(hass, entry)

    forecast_name = entry.data.get(CONF_FORECAST_NAME)
    post_code = str(entry.data.get(CONF_POST_CODE, "")).strip()
    forecast_point_type = entry.data.get(CONF_FORECAST_POINT_TYPE)
    if not forecast_name or forecast_name == post_code:
        forecast_point = find_forecast_point_by_stored_value(
            metadata.forecast_points, post_code, forecast_point_type
        )
        forecast_name = (
            forecast_point.display_name if forecast_point is not None else post_code
        )
        if forecast_point is not None and forecast_point_type != forecast_point.point_type_id:
            data_updates[CONF_FORECAST_POINT_TYPE] = forecast_point.point_type_id
    elif forecast_point_type is None:
        forecast_point = find_forecast_point_by_stored_value(
            metadata.forecast_points, post_code, forecast_point_type
        )
        if forecast_point is not None:
            data_updates[CONF_FORECAST_POINT_TYPE] = forecast_point.point_type_id
    if forecast_name and entry.data.get(CONF_FORECAST_NAME) != forecast_name:
        data_updates[CONF_FORECAST_NAME] = forecast_name

    if entry.data.get(CONF_STATION_CODE):
        station = find_station_by_code(
            metadata.weather_stations, entry.data.get(CONF_STATION_CODE)
        )
        if station is not None:
            station_name, station_canton = split_place_and_canton(station.name)
            formatted_station_name = format_station_display_name(
                station_name, station_canton or station.canton, include_canton=True
            )
            if entry.data.get(CONF_STATION_NAME) != formatted_station_name:
                data_updates[CONF_STATION_NAME] = formatted_station_name

    if entry.data.get(CONF_POLLEN_STATION_CODE):
        station = find_station_by_code(
            metadata.pollen_stations, entry.data.get(CONF_POLLEN_STATION_CODE)
        )
        if station is not None:
            formatted_pollen_station_name = format_station_display_name(
                station.name,
                station.canton,
                include_canton=True,
            )
            if entry.data.get(CONF_POLLEN_STATION_NAME) != formatted_pollen_station_name:
                data_updates[CONF_POLLEN_STATION_NAME] = formatted_pollen_station_name

    if CONF_WARNINGS_ENABLED not in entry.data:
        data_updates[CONF_WARNINGS_ENABLED] = bool(
            entry.data.get(CONF_WEATHER_WARNINGS_NUMBER, 1)
        )

    merged_data = {**entry.data, **data_updates}
    merged_data.pop(CONF_WEATHER_WARNINGS_NUMBER, None)
    new_title = build_entry_title(
        merged_data.get(CONF_FORECAST_NAME),
        merged_data.get(CONF_STATION_NAME),
        merged_data.get(CONF_POLLEN_STATION_NAME),
    )

    if data_updates or entry.title != new_title:
        hass.config_entries.async_update_entry(entry, data=merged_data, title=new_title)

    return entry
