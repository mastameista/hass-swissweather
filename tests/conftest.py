"""Shared test configuration."""

from __future__ import annotations

import importlib.util

import pytest

# pytest-homeassistant-custom-component needs Linux (Home Assistant imports
# fcntl), so a plain Windows checkout runs the unit tests without it.
if importlib.util.find_spec("pytest_homeassistant_custom_component") is not None:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Let Home Assistant load custom_components/swissweather in `hass` tests."""
        return
