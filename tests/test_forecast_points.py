"""Tests for forecast-point search helpers."""

from custom_components.swissweather.forecast_points import (
    ForecastPoint,
    search_forecast_points,
)


def test_search_forecast_points_matches_umlaut_variants() -> None:
    points = [
        ForecastPoint("800000", "2", "8000", "Zürich", "ZIP", 408, 47.37, 8.54),
        ForecastPoint("862000", "2", "8620", "Wetzikon ZH", "ZIP", 535, 47.32, 8.79),
    ]

    assert [point.point_id for point in search_forecast_points(points, "Zürich")] == [
        "800000"
    ]
    assert [point.point_id for point in search_forecast_points(points, "Zurich")] == [
        "800000"
    ]
    assert [point.point_id for point in search_forecast_points(points, "Zuerich")] == [
        "800000"
    ]


def test_search_forecast_points_still_matches_plain_substrings() -> None:
    points = [
        ForecastPoint("650000", "2", "6500", "Bellinzona", "ZIP", 238, 46.19, 9.02),
        ForecastPoint("650300", "2", "6503", "Bellinzona", "ZIP", 238, 46.19, 9.02),
    ]

    assert [point.point_id for point in search_forecast_points(points, "Bellin")] == [
        "650000",
        "650300",
    ]
