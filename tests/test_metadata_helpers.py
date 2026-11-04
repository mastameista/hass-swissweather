"""Forecast point and station metadata helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("homeassistant")

from custom_components.meteoswiss_forecast_warnings import forecast_points, station_lookup
from custom_components.meteoswiss_forecast_warnings.forecast_points import (
    ForecastPoint,
    find_forecast_point_by_id,
    find_forecast_point_by_stored_value,
    format_forecast_point_label,
    search_forecast_points,
)
from custom_components.meteoswiss_forecast_warnings.station_lookup import (
    PollenStationMetadataLoadError,
    async_load_pollen_station_list,
    find_station_by_code,
    split_place_and_canton,
)

HEADER = (
    "point_id;point_type_id;station_abbr;postal_code;point_name;point_type_en;"
    "point_height_masl;point_coordinates_wgs84_lat;point_coordinates_wgs84_lon"
)


def _point(point_id, type_id="2", postal=None, name="Zürich", height=None):
    return ForecastPoint(point_id, type_id, postal, name, None, height, None, None)


def _load_points(csv_text: str):
    response = MagicMock()
    response.text = AsyncMock(return_value=csv_text)

    async def fake_get_with_retry(session, url, **kwargs):
        return await kwargs["response_handler"](response)

    with patch.object(forecast_points, "async_get_with_retry", fake_get_with_retry):
        return asyncio.run(
            forecast_points.async_load_forecast_point_list(object(), raise_on_error=True)
        )


def test_point_with_unreadable_numbers_does_not_drop_the_list():
    """Regression: one bad height or coordinate failed the whole point list."""
    points = _load_points(
        "\n".join(
            [
                HEADER,
                "800100;2;;8001;Zürich;Postal code center;409.0;47.37;8.54",
                "810700;2;;8107;Buchs ZH;Postal code center;n/a;;x",
                "999;9;;;Unsupported type;Other;1;1;1",
            ]
        )
    )

    assert [p.point_id for p in points] == ["800100", "810700"]
    assert (points[1].point_height_masl, points[1].lat, points[1].lng) == (None, None, None)


def test_point_labels():
    assert format_forecast_point_label(_point("810700", postal="8107", name="Buchs ZH")) == (
        "Buchs ZH [PLZ 8107]"
    )
    assert format_forecast_point_label(_point("1", postal=None)) == "Zürich [PLZ]"
    assert format_forecast_point_label(_point("711", type_id="3", name="Säntis", height=2502)) == (
        "Säntis [POI, 2502 m, id 711]"
    )
    assert format_forecast_point_label(_point("712", type_id="3", name="Gipfel")) == (
        "Gipfel [POI, id 712]"
    )


def test_search_rejects_empty_and_single_letter_queries():
    points = [_point("800100", postal="8001")]

    assert search_forecast_points(points, "  ") == []
    assert search_forecast_points(points, "z") == []
    assert search_forecast_points(points, "8001") == points
    assert search_forecast_points(points, "zuerich") == points


def test_point_lookups_handle_missing_values():
    points = [_point("800100", postal="8001")]

    assert find_forecast_point_by_id(points, None) is None
    assert find_forecast_point_by_stored_value(points, None) is None
    assert find_forecast_point_by_stored_value(points, "  ") is None
    assert find_forecast_point_by_id(points, "800100") is points[0]


def test_station_helpers():
    assert split_place_and_canton(None) == (None, None)
    assert split_place_and_canton("Basel") == ("Basel", None)
    assert split_place_and_canton("Pfäffikon, ZH") == ("Pfäffikon", "ZH")
    assert find_station_by_code([], None) is None


def test_pollen_station_list_failures():
    failing = SimpleNamespace(async_get_pollen_station_list=AsyncMock(side_effect=OSError("down")))
    empty = SimpleNamespace(async_get_pollen_station_list=AsyncMock(return_value=None))

    assert asyncio.run(async_load_pollen_station_list(failing)) == []
    with pytest.raises(PollenStationMetadataLoadError):
        asyncio.run(async_load_pollen_station_list(failing, raise_on_error=True))
    assert asyncio.run(async_load_pollen_station_list(empty)) == []


def test_unreadable_station_number_is_none():
    assert station_lookup._float_or_none("n/a") is None
    assert station_lookup._int_or_none("") is None
