from __future__ import annotations

from datetime import UTC, datetime, timedelta
import pytest

pytest.importorskip("homeassistant")

from custom_components.swissweather.coordinator import build_warning_snapshot
from custom_components.swissweather.meteo import (
    Warning,
    WarningLevel,
    WarningLink,
    WarningType,
    build_warning_fingerprint,
    parse_warning_level,
    parse_warning_type,
)
from custom_components.swissweather.sensor import (
    get_color_for_warning_level,
    get_icon_for_warning,
)


def make_warning(
    *,
    warning_type: WarningType = WarningType.WIND,
    raw_type: int | None = None,
    warning_level: WarningLevel = WarningLevel.MODERATE_HAZARD,
    raw_level: int | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    outlook: bool = False,
    ordering: str | None = None,
    text: str | None = "warning",
) -> Warning:
    valid_from = valid_from or datetime.now(UTC) - timedelta(hours=1)
    valid_to = valid_to or datetime.now(UTC) + timedelta(hours=1)
    raw_type = raw_type if raw_type is not None else int(warning_type)
    raw_level = raw_level if raw_level is not None else int(warning_level)
    return Warning(
        warningType=warning_type,
        warningLevel=warning_level,
        text=text,
        htmlText=None,
        outlook=outlook,
        validFrom=valid_from,
        validTo=valid_to,
        links=[WarningLink(url="https://example.com", text="More")],
        ordering=ordering,
        raw_type=raw_type,
        raw_level=raw_level,
        fingerprint=build_warning_fingerprint(
            raw_type, raw_level, valid_from, valid_to, ordering, text
        ),
    )


def test_parse_warning_type_unknown():
    assert parse_warning_type(42) == WarningType.UNKNOWN


def test_parse_warning_level_unknown():
    assert parse_warning_level(42) == WarningLevel.UNKNOWN


def test_warning_fingerprint_is_stable():
    now = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    fingerprint = build_warning_fingerprint(0, 3, now, now, "abc", "hello")
    assert fingerprint == build_warning_fingerprint(0, 3, now, now, "abc", "hello")


def test_snapshot_handles_no_warnings():
    snapshot = build_warning_snapshot([])
    assert snapshot.count == 0
    assert snapshot.primary is None
    assert snapshot.highest_level is None


def test_snapshot_prioritizes_higher_level_first():
    now = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    low = make_warning(warning_level=WarningLevel.MODERATE_HAZARD, raw_level=2)
    high = make_warning(warning_level=WarningLevel.SEVERE_HAZARD, raw_level=4)
    snapshot = build_warning_snapshot([low, high], now=now)
    assert snapshot.primary == high
    assert snapshot.secondary == low
    assert snapshot.highest_level == 4


def test_snapshot_prioritizes_active_before_future_outlook():
    now = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    active = make_warning(
        warning_level=WarningLevel.SIGNIFICANT_HAZARD,
        raw_level=3,
        valid_from=now - timedelta(hours=1),
        valid_to=now + timedelta(hours=2),
        outlook=False,
    )
    future_outlook = make_warning(
        warning_level=WarningLevel.SIGNIFICANT_HAZARD,
        raw_level=3,
        valid_from=now + timedelta(hours=5),
        valid_to=now + timedelta(hours=7),
        outlook=True,
    )
    snapshot = build_warning_snapshot([future_outlook, active], now=now)
    assert snapshot.primary == active
    assert snapshot.secondary == future_outlook


def test_snapshot_uses_earlier_start_as_tiebreaker():
    now = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    first = make_warning(
        valid_from=now - timedelta(hours=2),
        valid_to=now + timedelta(hours=2),
        ordering="b",
    )
    second = make_warning(
        valid_from=now - timedelta(hours=1),
        valid_to=now + timedelta(hours=2),
        ordering="a",
    )
    snapshot = build_warning_snapshot([second, first], now=now)
    assert snapshot.primary == first


def test_snapshot_keeps_unknown_level_raw_value():
    now = datetime(2026, 3, 26, 12, 0, tzinfo=UTC)
    unknown = make_warning(
        warning_type=WarningType.UNKNOWN,
        raw_type=42,
        warning_level=WarningLevel.UNKNOWN,
        raw_level=7,
        ordering="z",
    )
    snapshot = build_warning_snapshot([unknown], now=now)
    assert snapshot.primary is not None
    assert snapshot.primary.type_state == "unknown_42"
    assert snapshot.highest_level == 7


@pytest.mark.parametrize(
    ("level", "expected_color"),
    [
        (None, "gray"),
        (0, "gray"),
        (1, "green"),
        (2, "yellow"),
        (3, "orange"),
        (4, "red"),
        (5, "#B71C1C"),
        (7, "#B71C1C"),
    ],
)
def test_warning_level_color_mapping(level, expected_color):
    assert get_color_for_warning_level(level) == expected_color


@pytest.mark.parametrize(
    ("warning_type", "expected_icon"),
    [
        (WarningType.WIND, "mdi:weather-windy"),
        (WarningType.THUNDERSTORMS, "mdi:weather-lightning-rainy"),
        (WarningType.RAIN, "mdi:weather-pouring"),
        (WarningType.SNOW, "mdi:snowflake"),
        (WarningType.SLIPPERY_ROADS, "mdi:car-brake-alert"),
        (WarningType.FROST, "mdi:snowflake-thermometer"),
        (WarningType.THAW, "mdi:thermometer-high"),
        (WarningType.HEAT_WAVES, "mdi:thermometer-high"),
        (WarningType.AVALANCHES, "mdi:snowflake-alert"),
        (WarningType.EARTHQUAKES, "mdi:pulse"),
        (WarningType.FOREST_FIRES, "mdi:fire-alert"),
        (WarningType.FLOOD, "mdi:waves-arrow-up"),
        (WarningType.DROUGHT, "mdi:water-off"),
        (WarningType.UNKNOWN, "mdi:alert"),
    ],
)
def test_warning_type_icon_mapping(warning_type, expected_icon):
    warning = make_warning(warning_type=warning_type)
    assert get_icon_for_warning(warning) == expected_icon


def test_empty_warning_icon_mapping():
    assert get_icon_for_warning(None) == "mdi:alert-outline"
