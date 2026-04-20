import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import logging

from aiohttp import ClientError, ClientSession

from .meteo import FORECAST_USER_AGENT, FloatValue, StationInfo
from .request import REQUEST_TIMEOUT, async_get_with_retry

logger = logging.getLogger(__name__)

POLLEN_STATIONS_URL = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-pollen/ogd-pollen_meta_stations.csv"
POLLEN_DATA_URL = "https://www.meteoschweiz.admin.ch/product/output/measured-values/stationsTable/messwerte-pollen-{}-1h/stationsTable.messwerte-pollen-{}-1h.en.json"


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


@dataclass
class CurrentPollen:
    stationAbbr: str
    timestamp: datetime
    birch: FloatValue
    grasses: FloatValue
    alder: FloatValue
    hazel: FloatValue
    beech: FloatValue
    ash: FloatValue
    oak: FloatValue


def to_float(string: str) -> float | None:
    if string is None:
        return None

    try:
        return float(string)
    except ValueError:
        return None


class PollenClient:
    """Returns values for pollen."""

    def __init__(self, session: ClientSession) -> None:
        """Initialize pollen client."""
        self._session = session

    async def async_get_pollen_station_list(self) -> list[StationInfo] | None:
        station_list = await self._async_get_csv_dictionary_for_url(
            POLLEN_STATIONS_URL, encoding="latin-1"
        )
        logger.debug("Loading %s", POLLEN_STATIONS_URL)
        if station_list is None:
            return None
        stations = []
        for row in station_list:
            stations.append(
                StationInfo(
                    row.get("station_name"),
                    row.get("station_abbr"),
                    row.get("station_type_en"),
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
        url = POLLEN_DATA_URL.format(pollen_key, pollen_key)
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
            stations = pollen_json.get("stations")
            if stations is None:
                return (None, None)
            for station in stations:
                if (
                    station.get("id") is None
                    or station.get("id").lower() != station_abbrev.lower()
                ):
                    continue
                current = station.get("current")
                if current is None:
                    logger.warning(
                        "No current data for %s in dataset for %s!",
                        station_abbrev,
                        pollen_key,
                    )
                    continue
                timestamp_val = current.get("date")
                if timestamp_val is not None:
                    timestamp = datetime.fromtimestamp(timestamp_val / 1000, UTC)
                else:
                    timestamp = None
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
