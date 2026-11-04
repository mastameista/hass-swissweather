"""Warnings switch active/expired at their own start and end, not only on polls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.swissweather import coordinator as coordinator_module
from custom_components.swissweather.const import CONF_POST_CODE
from custom_components.swissweather.coordinator import (
    SwissWeatherDataCoordinator,
    WeatherData,
    build_warning_snapshot,
    next_warning_boundary,
)

from .test_warnings import make_warning

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
START = NOW + timedelta(minutes=1)
END = NOW + timedelta(minutes=2)


def test_next_boundary_is_the_earliest_start_or_end_ahead():
    later = make_warning(valid_from=NOW + timedelta(hours=3), valid_to=NOW + timedelta(hours=5))
    active = make_warning(valid_from=NOW - timedelta(hours=1), valid_to=NOW + timedelta(hours=1))
    upcoming = make_warning(valid_from=START, valid_to=END)

    assert next_warning_boundary([later, active, upcoming], NOW) == START
    assert next_warning_boundary([later, active], NOW) == NOW + timedelta(hours=1, seconds=1)


def test_open_ended_active_warning_has_no_boundary():
    drought = make_warning(valid_from=NOW - timedelta(days=100))
    drought.validTo = None

    assert next_warning_boundary([drought], NOW) is None


class _Timers:
    """Stand-in for async_track_point_in_utc_time that records each timer."""

    def __init__(self) -> None:
        self.scheduled: list[tuple] = []
        self.cancelled = 0

    def track(self, hass, action, point_in_time):
        self.scheduled.append((action, point_in_time))

        def _cancel() -> None:
            self.cancelled += 1

        return _cancel


@pytest.fixture
def setup(monkeypatch):
    timers = _Timers()
    notified: list[int] = []
    monkeypatch.setattr(coordinator_module, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(coordinator_module, "MeteoClient", lambda session, language: object())
    monkeypatch.setattr(coordinator_module, "async_track_point_in_utc_time", timers.track)
    monkeypatch.setattr(
        DataUpdateCoordinator, "async_update_listeners", lambda self: notified.append(1)
    )
    entry = SimpleNamespace(data={CONF_POST_CODE: "8620"}, async_on_unload=lambda cb: None)
    coordinator = SwissWeatherDataCoordinator(
        SimpleNamespace(config=SimpleNamespace(language="de")), entry
    )
    return coordinator, timers, notified


def _load(coordinator, warnings) -> None:
    coordinator.data = WeatherData(
        current_weather=None,
        forecast=None,
        warning_snapshot=build_warning_snapshot(warnings, now=NOW),
    )


def test_warning_becomes_active_and_expires_between_polls(setup, monkeypatch):
    """Regression: a warning from 12:01 to 12:02 fell between two 10-minute polls."""
    coordinator, timers, notified = setup
    monkeypatch.setattr(
        coordinator_module.datetime, "datetime", _FrozenDatetime, raising=True
    )
    _load(coordinator, [make_warning(valid_from=START, valid_to=END)])

    coordinator.async_update_listeners()
    action, when = timers.scheduled[-1]
    assert when == START
    assert coordinator.data.warning_snapshot.active_warnings == []

    action(START)
    assert len(coordinator.data.warning_snapshot.active_warnings) == 1
    action, when = timers.scheduled[-1]
    assert when == END + timedelta(seconds=1)

    action(when)
    assert coordinator.data.warning_snapshot.count == 0
    assert len(notified) == 3


def test_no_timer_while_warnings_are_unreadable(setup):
    coordinator, timers, _ = setup
    _load(coordinator, None)

    coordinator.async_update_listeners()

    assert timers.scheduled == []


def test_shutdown_cancels_the_pending_timer(setup, monkeypatch):
    coordinator, timers, _ = setup
    monkeypatch.setattr(
        coordinator_module.datetime, "datetime", _FrozenDatetime, raising=True
    )
    _load(coordinator, [make_warning(valid_from=START, valid_to=END)])
    coordinator.async_update_listeners()

    async def _noop(self) -> None:
        return None

    monkeypatch.setattr(DataUpdateCoordinator, "async_shutdown", _noop)
    asyncio.run(coordinator.async_shutdown())

    assert timers.cancelled == 1


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW
