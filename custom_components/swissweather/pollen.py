import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import logging

from aiohttp import ClientError, ClientSession

from .meteo import (
    DEFAULT_LANGUAGE,
    FORECAST_USER_AGENT,
    FloatValue,
    StationInfo,
    to_meteoswiss_language,
)
from .request import REQUEST_TIMEOUT, async_get_with_retry

logger = logging.getLogger(__name__)

POLLEN_STATIONS_URL = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-pollen/ogd-pollen_meta_stations.csv"
POLLEN_DATA_URL = "https://www.meteoschweiz.admin.ch/product/output/measured-values/stationsTable/messwerte-pollen-{key}-1h/stationsTable.messwerte-pollen-{key}-1h.{language}.json"


class PollenClientError(Exception):
    """Base error for pollen client failures."""


class PollenConnectionError(PollenClientError):
    """Raised when pollen endpoints cannot be reached."""


class PollenDataError(PollenClientError):
    """Raised when pollen payloads are invalid."""

class PollenLevel(StrEnum):
    """Marks pollen level."""

    NONE = "None"
    LOW = "Low"
    MEDIUM = "Medium"
    STRONG = "Strong"
    VERY_STRONG = "Very Strong"

# Plant-specific load thresholds (low, medium, strong) based on the official
# MeteoSwiss classification:
# https://www.meteoswiss.admin.ch/dam/jcr:43b4f361-8bc1-4af7-a232-c126de0f2f80/Belastungsklassen-der-allergenen-Pollenarten_E.pdf
_POLLEN_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "birch": (10, 70, 300),
    "grasses": (20, 50, 150),
    "alder": (10, 70, 250),
    "hazel": (10, 70, 250),
    "beech": (50, 130, 400),
    "ash": (10, 100, 350),
    "oak": (50, 130, 400),
}
_DEFAULT_POLLEN_THRESHOLDS = (10, 70, 250)


def get_pollen_level(value: float | None, plant_key: str) -> PollenLevel | None:
    """Return the pollen load level for a given value and plant type."""
    if value is None:
        return None
    if value <= 0:
        return PollenLevel.NONE
    low, medium, strong = _POLLEN_THRESHOLDS.get(plant_key, _DEFAULT_POLLEN_THRESHOLDS)
    if value <= low:
        return PollenLevel.LOW
    if value <= medium:
        return PollenLevel.MEDIUM
    if value <= strong:
        return PollenLevel.STRONG
    return PollenLevel.VERY_STRONG


def _parse_epoch_millis(value: str | float | None) -> datetime | None:
    """Convert a MeteoSwiss epoch-milliseconds value to an aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None

@dataclass
class CurrentPollen:
    stationAbbr: str
    timestamp: datetime | None
    birch: FloatValue
    grasses: FloatValue
    alder: FloatValue
    hazel: FloatValue
    beech: FloatValue
    ash: FloatValue
    oak: FloatValue


def to_float(string: str | float | None) -> float | None:
    if string is None:
        return None

    try:
        return float(string)
    except ValueError:
        return None


class PollenClient:
    """Returns values for pollen."""

    def __init__(
        self, session: ClientSession, language: str | None = DEFAULT_LANGUAGE
    ) -> None:
        """Initialize the pollen client.

        MeteoSwiss serves en, de, fr and it; any other tag (including full
        Home Assistant tags such as "de-CH") is normalized to one of those.
        """
        self._session = session
        self._language = to_meteoswiss_language(language)

    async def async_get_pollen_station_list(self) -> list[StationInfo] | None:
        station_list = await self._async_get_csv_dictionary_for_url(
            POLLEN_STATIONS_URL, encoding="latin-1"
        )
        logger.debug("Loading %s", POLLEN_STATIONS_URL)
        if station_list is None:
            return None
        stations = []
        for row in station_list:
            name = row.get("station_name")
            abbr = row.get("station_abbr")
            if not name or not abbr:
                continue
            stations.append(
                StationInfo(
                    name,
                    abbr,
                    row.get(f"station_type_{self._language}"),
                    to_float(row.get("station_height_masl")),
                    to_float(row.get("station_coordinates_wgs84_lat")),
                    to_float(row.get("station_coordinates_wgs84_lon")),
                    row.get("station_canton"),
                )
            )
        if len(stations) == 0:
            logger.warning("Couldn't find any stations in the dataset!")
            return None
        logger.info("Found %d stations for pollen.", len(stations))
        return stations

    async def async_get_current_pollen_for_station(
        self, station_abbrev: str
    ) -> CurrentPollen | None:
        timestamp = None
        unit = "p/m³"
        types = ["birke", "graeser", "erle", "hasel", "buche", "esche", "eiche"]
        values = []
        for pollen_type in types:
            value, ts = await self.async_get_current_pollen_for_station_type(
                station_abbrev, pollen_type
            )
            if timestamp is None and ts is not None:
                timestamp = ts
            values.append(value)
        if all(v is None for v in values):
            return None

        return CurrentPollen(
            station_abbrev,
            timestamp,
            (values[0], unit),
            (values[1], unit),
            (values[2], unit),
            (values[3], unit),
            (values[4], unit),
            (values[5], unit),
            (values[6], unit),
        )

    async def async_get_current_pollen_for_station_type(
        self, station_abbrev: str, pollen_key: str
    ) -> tuple[float | None, datetime | None]:
        url = POLLEN_DATA_URL.format(key=pollen_key, language=self._language)
        logger.debug("Loading %s", url)
        try:

            async def _parse_json(response):
                return await response.json()

            pollen_json = await async_get_with_retry(
                self._session,
                url,
                logger=logger,
                response_handler=_parse_json,
                headers={
                    "User-Agent": FORECAST_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
            if not isinstance(pollen_json, dict):
                raise PollenDataError(f"Unexpected MeteoSwiss pollen payload from {url}")
            stations = pollen_json.get("stations")
            if stations is None:
                return (None, None)
            if not isinstance(stations, list):
                raise PollenDataError(f"Unexpected MeteoSwiss pollen stations from {url}")
            for station in stations:
                if not isinstance(station, dict):
                    continue
                station_id = station.get("id")
                if (
                    not isinstance(station_id, str)
                    or station_id.lower() != station_abbrev.lower()
                ):
                    continue
                current = station.get("current")
                if not isinstance(current, dict):
                    logger.warning(
                        "No current data for %s in dataset for %s!",
                        station_abbrev,
                        pollen_key,
                    )
                    continue
                timestamp = _parse_epoch_millis(current.get("date"))
                if timestamp is None:
                    # A reading that cannot be dated may be stale; keep looking
                    # rather than presenting it as current.
                    logger.warning(
                        "No valid timestamp for %s in dataset for %s!",
                        station_abbrev,
                        pollen_key,
                    )
                    continue
                value = to_float(current.get("value"))
                return (value, timestamp)
            logger.warning(
                "Couldn't find %s in dataset for %s!", station_abbrev, pollen_key
            )
            return (None, None)
        except (ClientError, TimeoutError) as err:
            raise PollenConnectionError(
                f"Failed to fetch MeteoSwiss pollen data from {url}"
            ) from err
        except ValueError as err:
            raise PollenDataError(
                f"Invalid MeteoSwiss pollen payload from {url}"
            ) from err

    async def _async_get_csv_dictionary_for_url(self, url, encoding="utf-8"):
        try:
            logger.debug("Requesting station data from %s...", url)

            async def _parse_csv(response) -> list[dict[str, str]]:
                text = await response.text(encoding=encoding)
                return list(csv.DictReader(text.splitlines(), delimiter=";"))

            return await async_get_with_retry(
                self._session,
                url,
                logger=logger,
                response_handler=_parse_csv,
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError) as err:
            raise PollenConnectionError(
                f"Failed to fetch MeteoSwiss pollen CSV from {url}"
            ) from err
        except (UnicodeDecodeError, csv.Error) as err:
            raise PollenDataError(
                f"Invalid MeteoSwiss pollen CSV payload from {url}"
            ) from err
