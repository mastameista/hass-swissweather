from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings.meteo import MeteoClient

STATION_ROW = {
    "Station/Location": "TAE",
    "Date": "202609301200",
    "tre200s0": "21.5",
    "rre150z0": "0.2",
    "sre000z0": "10",
    "gre000z0": "450",
    "ure200s0": "65",
    "tde200s0": "14.3",
    "dkl010z0": "270",
    "fu3010z0": "12",
    "fu3010z1": "25",
    # Three distinct pressure columns, deliberately far apart so a
    # mis-mapping cannot pass unnoticed.
    "prestas0": "950.1",
    "pp0qffs0": "1013.2",
    "pp0qnhs0": "1015.3",
}


def test_pressure_columns_map_to_distinct_fields():
    """Regression: pressureSeaLevel used to read prestas0 (station level)."""
    client = MeteoClient(session=object())

    weather = client._get_current_data_for_row(STATION_ROW)

    assert weather.pressureStationLevel == (950.1, "hPa")
    assert weather.pressureSeaLevel == (1013.2, "hPa")
    assert weather.pressureSeaLevelAtStandardAtmosphere == (1015.3, "hPa")


def test_station_row_maps_remaining_measurements():
    client = MeteoClient(session=object())

    weather = client._get_current_data_for_row(STATION_ROW)

    assert weather.airTemperature == (21.5, "°C")
    assert weather.dewPoint == (14.3, "°C")
    assert weather.relativeHumidity == (65.0, "%")
    assert weather.windDirection == (270.0, "°")
    assert weather.globalRadiation == (450.0, "W/m²")


def test_missing_pressure_columns_yield_none():
    client = MeteoClient(session=object())

    weather = client._get_current_data_for_row(
        {"Station/Location": "TAE", "Date": "202609301200"}
    )

    assert weather.pressureStationLevel == (None, "hPa")
    assert weather.pressureSeaLevel == (None, "hPa")
    assert weather.pressureSeaLevelAtStandardAtmosphere == (None, "hPa")


@pytest.mark.parametrize("date", [None, "", "not-a-date", "2026-09-30"])
def test_row_without_valid_timestamp_is_rejected(date):
    """A station row that cannot be dated is treated as corrupt, not as current data."""
    client = MeteoClient(session=object())
    row = {**STATION_ROW, "Date": date}

    assert client._get_current_data_for_row(row) is None


def test_row_timestamp_is_timezone_aware_utc():
    client = MeteoClient(session=object())

    weather = client._get_current_data_for_row(STATION_ROW)

    assert weather.date.tzinfo is not None
    assert weather.date.utcoffset().total_seconds() == 0
