from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
import hashlib
import itertools
import logging
from typing import NewType

from aiohttp import ClientError, ClientSession

from .request import REQUEST_TIMEOUT, async_get_with_retry

logger = logging.getLogger(__name__)

CURRENT_CONDITION_URL = (
    "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-aktuell/VQHA80.csv"
)
FORECAST_URL = "https://app-prod-ws.meteoswiss-app.ch/v2/plzDetail?plz={}"
FORECAST_USER_AGENT = "android-31 ch.admin.meteoswiss-2160000"
# Languages MeteoSwiss publishes its data in.
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = frozenset({"de", "en", "fr", "it"})


def to_meteoswiss_language(language: str | None) -> str:
    """Map a Home Assistant language tag onto a language MeteoSwiss supports.

    Home Assistant hands out tags like "de", "de-CH" or "pt-BR"; MeteoSwiss only
    serves de, fr, it and en. Anything else falls back to English.
    """
    if not language:
        return DEFAULT_LANGUAGE

    base = language.replace("_", "-").split("-", 1)[0].lower()
    if base in SUPPORTED_LANGUAGES:
        return base

    logger.debug(
        "Language %s is not served by MeteoSwiss, falling back to %s",
        language,
        DEFAULT_LANGUAGE,
    )
    return DEFAULT_LANGUAGE

CONDITION_CLASSES = {
    "clear-night": [101],
    "cloudy": [5, 35, 105, 126, 135],
    "fog": [27, 28, 127, 128],
    "hail": [],
    "lightning": [12, 36, 40, 41, 112, 136, 140, 141],
    "lightning-rainy": [13, 23, 24, 25, 32, 38, 113, 123, 124, 125, 138],
    "partlycloudy": [2, 3, 4, 102, 103, 104],
    "pouring": [20, 120],
    "rainy": [6, 9, 14, 17, 29, 33, 106, 109, 114, 117, 129, 132, 133],
    "snowy": [
        8,
        11,
        16,
        19,
        22,
        30,
        34,
        37,
        42,
        108,
        111,
        116,
        119,
        122,
        130,
        134,
        137,
        142,
    ],
    "snowy-rainy": [7, 10, 15, 18, 21, 31, 39, 107, 110, 115, 118, 121, 131, 139],
    "sunny": [1, 26],
    "windy": [],
    "windy-variant": [],
    "exceptional": [],
}

ICON_TO_CONDITION_MAP: dict[int, str] = {
    icon: condition
    for condition, icons in CONDITION_CLASSES.items()
    for icon in icons
}

# MeteoSwiss uses 32767 (Int16 max) as a "no data" sentinel in the plzDetail
# currentWeather block.
MISSING_VALUE_SENTINEL = 32767


class MeteoSwissClientError(Exception):
    """Base error for MeteoSwiss client failures."""


class MeteoSwissConnectionError(MeteoSwissClientError):
    """Raised when MeteoSwiss cannot be reached."""


class MeteoSwissDataError(MeteoSwissClientError):
    """Raised when MeteoSwiss returns invalid data."""


def to_float(string: str) -> float | None:
    """Convert a MeteoSwiss number string to float."""
    if string is None or string == "-":
        return None
    try:
        return float(string)
    except ValueError:
        logger.exception("Failed to convert value %s", string)
        return None


def to_int(string: str) -> int | None:
    """Convert a MeteoSwiss number string to int."""
    if string is None or string == "-":
        return None
    try:
        return int(string)
    except ValueError:
        logger.exception("Failed to convert value %s", string)
        return None


FloatValue = NewType("FloatValue", tuple[float | None, str | None])


@dataclass
class StationInfo:
    name: str
    abbreviation: str
    type: str
    altitude: float
    lat: float
    lng: float
    canton: str

    def __str__(self) -> str:
        return (
            f"Station {self.abbreviation} - [Name: {self.name}, Lat: {self.lat}, "
            f"Lng: {self.lng}, Canton: {self.canton}]"
        )


@dataclass
class CurrentWeather:
    station: StationInfo | None
    date: datetime
    airTemperature: FloatValue | None
    precipitation: FloatValue | None
    sunshine: FloatValue | None
    globalRadiation: FloatValue | None
    relativeHumidity: FloatValue | None
    dewPoint: FloatValue | None
    windDirection: FloatValue | None
    windSpeed: FloatValue | None
    gustPeak1s: FloatValue | None
    pressureStationLevel: FloatValue | None
    pressureSeaLevel: FloatValue | None
    pressureSeaLevelAtStandardAtmosphere: FloatValue | None


@dataclass
class CurrentState:
    currentTemperature: FloatValue | None
    currentIcon: int | None
    currentCondition: str | None


@dataclass
class Forecast:
    timestamp: datetime
    icon: int | None
    condition: str | None
    temperatureMax: FloatValue | None
    temperatureMin: FloatValue | None
    precipitation: FloatValue | None
    temperatureMean: FloatValue | None = None
    precipitationProbability: FloatValue | None = None
    windSpeed: FloatValue | None = None
    windDirection: FloatValue | None = None
    windGustSpeed: FloatValue | None = None
    sunshine: FloatValue | None = None


class WarningType(IntEnum):
    WIND = 0
    THUNDERSTORMS = 1
    RAIN = 2
    SNOW = 3
    SLIPPERY_ROADS = 4
    FROST = 5
    THAW = 6
    HEAT_WAVES = 7
    AVALANCHES = 8
    EARTHQUAKES = 9
    FOREST_FIRES = 10
    FLOOD = 11
    DROUGHT = 12
    UNKNOWN = 99


class WarningLevel(IntEnum):
    UNKNOWN = -1
    NO_DANGER = 0
    NO_OR_MINIMAL_HAZARD = 1
    MODERATE_HAZARD = 2
    SIGNIFICANT_HAZARD = 3
    SEVERE_HAZARD = 4
    VERY_SEVERE_HAZARD = 5


@dataclass
class WarningLink:
    url: str | None
    text: str | None
    alt_url: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a Home Assistant-safe mapping for state attributes."""
        return {"url": self.url, "text": self.text, "alt_url": self.alt_url}


@dataclass
class Warning:
    warningType: WarningType
    warningLevel: WarningLevel
    text: str | None
    htmlText: str | None
    outlook: bool
    validFrom: datetime | None
    validTo: datetime | None
    links: list[WarningLink]
    ordering: str | None = None
    raw_type: int | None = None
    raw_level: int | None = None
    fingerprint: str | None = None

    @property
    def effective_level(self) -> int:
        """Return the warning level as integer for sorting and comparisons."""
        if self.warningLevel == WarningLevel.UNKNOWN and self.raw_level is not None:
            return self.raw_level
        return int(self.warningLevel.value)

    @property
    def type_name(self) -> str:
        """Return a lowercase warning type label for state attributes."""
        return self.warningType.name.lower()

    @property
    def type_state(self) -> str:
        """Return a readable entity state for ranked warning entities."""
        if self.warningType == WarningType.UNKNOWN and self.raw_type is not None:
            return f"unknown_{self.raw_type}"
        return self.warningType.name.lower()

    @property
    def level_name(self) -> str | None:
        """Return a human-friendly warning level label."""
        if self.warningLevel == WarningLevel.UNKNOWN:
            return (
                f"Level {self.raw_level}"
                if self.raw_level is not None
                else None
            )
        return self.warningLevel.name.replace("_", " ").title()

    def is_active(self, now: datetime | None = None) -> bool:
        """Return whether the warning is currently active."""
        now = now or datetime.now(UTC)
        if self.validFrom and now < self.validFrom:
            return False
        if self.validTo and now > self.validTo:
            return False
        return True

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return whether the warning has already expired."""
        now = now or datetime.now(UTC)
        return self.validTo is not None and now > self.validTo


@dataclass
class WeatherForecast:
    current: CurrentState | None
    dailyForecast: list[Forecast] | None
    hourlyForecast: list[Forecast] | None
    sunrises: list[datetime] | None
    sunsets: list[datetime] | None
    warnings: list[Warning] | None


def _chunked(values: list, size: int):
    return list(itertools.zip_longest(*(iter(values),) * size, fillvalue=None))


def _get_float_value(values: list[float | None], unit: str) -> list[FloatValue | None]:
    return [(value, unit) if value is not None else None for value in values]


def build_warning_fingerprint(
    raw_type: int | None,
    raw_level: int | None,
    valid_from: datetime | None,
    valid_to: datetime | None,
    ordering: str | None,
    text: str | None,
) -> str:
    """Build a stable warning fingerprint from the warning payload."""
    text_hash = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]
    payload = "|".join(
        [
            "" if raw_type is None else str(raw_type),
            "" if raw_level is None else str(raw_level),
            "" if valid_from is None else valid_from.isoformat(),
            "" if valid_to is None else valid_to.isoformat(),
            ordering or "",
            text_hash,
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def parse_warning_type(value: int | None) -> WarningType:
    """Map the raw MeteoSwiss warning type to a supported enum."""
    if value is None:
        return WarningType.UNKNOWN
    try:
        return WarningType(value)
    except ValueError:
        return WarningType.UNKNOWN


def parse_warning_level(value: int | None) -> WarningLevel:
    """Map the raw MeteoSwiss warning level to a supported enum."""
    if value is None:
        return WarningLevel.UNKNOWN
    try:
        return WarningLevel(value)
    except ValueError:
        return WarningLevel.UNKNOWN


class MeteoClient:
    """Client for MeteoSwiss weather data.

    MeteoSwiss currently supports the languages ``de``, ``en``, ``fr``, and ``it``.
    """

    language: str = DEFAULT_LANGUAGE

    def __init__(
        self, session: ClientSession, language: str | None = DEFAULT_LANGUAGE
    ) -> None:
        """Initialize the MeteoSwiss client."""
        self._session = session
        self.language = to_meteoswiss_language(language)

    async def async_get_current_weather_for_all_stations(
        self,
    ) -> list[CurrentWeather] | None:
        logger.debug("Retrieving current weather for all stations ...")
        data = await self._async_get_csv_dictionary_for_url(CURRENT_CONDITION_URL)
        if data is None:
            return None
        weather = []
        for row in data:
            item = self._get_current_data_for_row(row)
            if item is not None:
                weather.append(item)
        return weather

    async def async_get_current_weather_for_station(
        self, station: str
    ) -> CurrentWeather | None:
        logger.debug("Retrieving current weather...")
        data = await self._async_get_current_weather_line_for_station(station)
        if data is None:
            logger.warning("Couldn't find data for station %s", station)
            return None
        return self._get_current_data_for_row(data)

    def _get_current_data_for_row(self, csv_row) -> CurrentWeather | None:
        timestamp_raw = csv_row.get("Date")
        if not timestamp_raw:
            return None
        try:
            timestamp = datetime.strptime(timestamp_raw, "%Y%m%d%H%M").replace(
                tzinfo=UTC
            )
        except (ValueError, TypeError):
            logger.warning("Failed to parse date %s from row", timestamp_raw)
            return None

        return CurrentWeather(
            csv_row.get("Station/Location"),
            timestamp,
            (to_float(csv_row.get("tre200s0", None)), "°C"),
            (to_float(csv_row.get("rre150z0", None)), "mm"),
            (to_float(csv_row.get("sre000z0", None)), "min"),
            (to_float(csv_row.get("gre000z0", None)), "W/m²"),
            (to_float(csv_row.get("ure200s0", None)), "%"),
            (to_float(csv_row.get("tde200s0", None)), "°C"),
            (to_float(csv_row.get("dkl010z0", None)), "°"),
            (to_float(csv_row.get("fu3010z0", None)), "km/h"),
            (to_float(csv_row.get("fu3010z1", None)), "km/h"),
            (to_float(csv_row.get("prestas0", None)), "hPa"),
            (to_float(csv_row.get("pp0qffs0", None)), "hPa"),
            (to_float(csv_row.get("pp0qnhs0", None)), "hPa"),
        )

    async def async_get_forecast(
        self, postCode, forecastPointType: str | None = None
    ) -> WeatherForecast | None:
        forecastJson = await self._async_get_forecast_json(
            postCode, self.language, forecastPointType
        )
        logger.debug("Forecast JSON: %s", forecastJson)
        if forecastJson is None:
            return None

        currentState = self._get_current_state(forecastJson)
        dailyForecast = self._get_daily_forecast(forecastJson)
        hourlyForecast = self._get_hourly_forecast(forecastJson)
        try:
            warnings = self._get_weather_warnings(forecastJson)
        except MeteoSwissDataError as err:
            logger.warning(
                "Failed to parse MeteoSwiss warnings for %s; continuing without warnings: %s",
                postCode,
                err,
            )
            warnings = []

        sunrises = None
        sunriseJson = forecastJson.get("graph", {}).get("sunrise", None)
        if sunriseJson is not None and isinstance(sunriseJson, list):
            sunrises = []
            for epoch in sunriseJson:
                try:
                    sunrises.append(datetime.fromtimestamp(epoch / 1000, UTC))
                except (ValueError, TypeError, OSError):
                    pass

        sunsets = None
        sunsetJson = forecastJson.get("graph", {}).get("sunset", None)
        if sunsetJson is not None and isinstance(sunsetJson, list):
            sunsets = []
            for epoch in sunsetJson:
                try:
                    sunsets.append(datetime.fromtimestamp(epoch / 1000, UTC))
                except (ValueError, TypeError, OSError):
                    pass

        return WeatherForecast(
            currentState,
            dailyForecast,
            hourlyForecast,
            sunrises,
            sunsets,
            warnings,
        )

    def _get_current_state(self, forecastJson) -> CurrentState | None:
        if "currentWeather" not in forecastJson:
            return None
        currentWeather = forecastJson.get("currentWeather", {})

        currentIcon = to_int(currentWeather.get("iconV2", None))
        if currentIcon == MISSING_VALUE_SENTINEL:
            currentIcon = None
        currentCondition = (
            None if currentIcon is None else ICON_TO_CONDITION_MAP.get(currentIcon)
        )

        currentTemperature = to_float(currentWeather.get("temperature"))
        if currentTemperature == MISSING_VALUE_SENTINEL:
            currentTemperature = None

        if currentCondition is None:
            # iconV2 can be missing or the sentinel while the legacy field still
            # carries a usable code, so fall back to it before giving up.
            legacy_icon = to_int(currentWeather.get("icon", None))
            if legacy_icon is not None and legacy_icon != MISSING_VALUE_SENTINEL:
                legacy_condition = ICON_TO_CONDITION_MAP.get(legacy_icon)
                if legacy_condition is not None:
                    currentIcon = legacy_icon
                    currentCondition = legacy_condition

        return CurrentState(
            (currentTemperature, "°C"),
            currentIcon,
            currentCondition,
        )

    def _get_daily_forecast(self, forecastJson) -> list[Forecast] | None:
        forecast: list[Forecast] = []
        if "forecast" not in forecastJson or not isinstance(forecastJson["forecast"], list):
            return forecast

        for dailyJson in forecastJson["forecast"]:
            if not isinstance(dailyJson, dict) or "dayDate" not in dailyJson:
                continue
            try:
                timestamp = datetime.strptime(dailyJson["dayDate"], "%Y-%m-%d").replace(
                    tzinfo=UTC
                )
            except (ValueError, TypeError):
                logger.warning("Failed to parse dayDate: %s", dailyJson.get("dayDate"))
                continue
            icon = to_int(dailyJson.get("iconDay", None))
            condition = ICON_TO_CONDITION_MAP.get(icon)
            forecast.append(
                Forecast(
                    timestamp,
                    icon,
                    condition,
                    (to_float(dailyJson.get("temperatureMax", None)), "°C"),
                    (to_float(dailyJson.get("temperatureMin", None)), "°C"),
                    (to_float(dailyJson.get("precipitation", None)), "mm/h"),
                )
            )
        return forecast

    def _get_hourly_forecast(self, forecastJson) -> list[Forecast] | None:
        graphJson = forecastJson.get("graph", None)
        if graphJson is None or not isinstance(graphJson, dict):
            return None

        startTimestampEpoch = to_int(graphJson.get("start", None))
        if startTimestampEpoch is None:
            return None
        try:
            startTimestamp = datetime.fromtimestamp(startTimestampEpoch / 1000, UTC)
        except (ValueError, TypeError, OSError):
            return None

        forecast = []
        temperatureMaxList = [
            (value, "°C") for value in (graphJson.get("temperatureMax1h") or [])
        ]
        temperatureMeanList = [
            (value, "°C") for value in (graphJson.get("temperatureMean1h") or [])
        ]
        temperatureMinList = [
            (value, "°C") for value in (graphJson.get("temperatureMin1h") or [])
        ]
        windGustSpeedList = [
            (value, "km/h") for value in (graphJson.get("gustSpeed1h") or [])
        ]
        windSpeedList = [
            (value, "km/h") for value in (graphJson.get("windSpeed1h") or [])
        ]
        sunshineList = [
            (value, "min/h") for value in (graphJson.get("sunshine1h") or [])
        ]

        precipitationList = []
        precipitation10mList = graphJson.get("precipitation10m")
        precipitation1hList = graphJson.get("precipitation1h")
        if precipitation1hList and precipitation10mList:
            # The hourly series starts where the 10-minute series ends, so the
            # 10-minute values are averaged into hourly buckets and prepended.
            # Work on a copy so the parsed payload is not mutated.
            precip10m = list(precipitation10mList)
            # The 10-minute list is usually one value short of a full bucket;
            # borrow the first hourly value to complete it.
            precip10m.append(precipitation1hList[0])
            precipitationList = [
                sum(precip10m[i : i + 6]) / 6.0 for i in range(0, len(precip10m), 6)
            ]
            # Trim so the merged series lines up with the other hourly lists.
            lenDiff = len(temperatureMeanList) - len(precipitation1hList)
            logger.debug(
                "Need to leave %d 10min datapoints out of %d (%d pre merge)",
                lenDiff,
                len(precipitationList),
                len(precip10m),
            )
            del precipitationList[lenDiff:]
            precipitationList += precipitation1hList
            precipitationList = [(value, "mm/h") for value in precipitationList]

        # Icons, wind direction and precipitation probability arrive in 3-hour
        # steps; repeat each value three times to align with the hourly series.
        weatherIcon3h = graphJson.get("weatherIcon3h") or []
        windDirection3h = graphJson.get("windDirection3h") or []
        precipitationProbability3h = graphJson.get("precipitationProbability3h") or []

        iconList = list(
            itertools.chain.from_iterable(itertools.repeat(x, 3) for x in weatherIcon3h)
        )
        windDirectionList = list(
            itertools.chain.from_iterable(
                itertools.repeat((x, "°"), 3) for x in windDirection3h
            )
        )
        precipitationProbabilityList = list(
            itertools.chain.from_iterable(
                itertools.repeat((x, "%"), 3) for x in precipitationProbability3h
            )
        )

        minForecastHours = min(
            len(temperatureMaxList),
            len(temperatureMeanList),
            len(temperatureMinList),
            len(precipitationList),
            len(iconList),
        )
        timestampList = [
            startTimestamp + timedelta(hours=value)
            for value in range(0, minForecastHours)
        ]

        for (
            ts,
            icon,
            tMax,
            tMean,
            tMin,
            precipitation,
            precipitationProbability,
            windDirection,
            windSpeed,
            windGustSpeed,
            sunshine,
        ) in zip(
            timestampList,
            iconList,
            temperatureMaxList,
            temperatureMeanList,
            temperatureMinList,
            precipitationList,
            precipitationProbabilityList,
            windDirectionList,
            windSpeedList,
            windGustSpeedList,
            sunshineList,
            strict=False,
        ):
            forecast.append(
                Forecast(
                    ts,
                    icon,
                    ICON_TO_CONDITION_MAP.get(icon),
                    tMax,
                    tMin,
                    precipitation,
                    precipitationProbability=precipitationProbability,
                    windSpeed=windSpeed,
                    windDirection=windDirection,
                    windGustSpeed=windGustSpeed,
                    temperatureMean=tMean,
                    sunshine=sunshine,
                )
            )
        return forecast

    def _get_weather_warnings(self, forecastJson) -> list[Warning]:
        warningsJson = forecastJson.get("warnings", None)
        if warningsJson is None or not isinstance(warningsJson, list):
            return []

        warnings: list[Warning] = []
        parse_errors = 0
        for warningJson in warningsJson:
            if not isinstance(warningJson, dict):
                # Count it so a payload whose shape changed entirely surfaces as
                # a data error instead of silently reading as "no warnings".
                parse_errors += 1
                continue
            try:
                raw_type = to_int(warningJson.get("warnType"))
                raw_level = to_int(warningJson.get("warnLevel"))
                validFrom = None
                validTo = None
                validFromEpoch = to_int(warningJson.get("validFrom"))
                validToEpoch = to_int(warningJson.get("validTo"))
                if validFromEpoch is not None:
                    try:
                        validFrom = datetime.fromtimestamp(validFromEpoch / 1000, UTC)
                    except (ValueError, TypeError, OSError):
                        pass
                if validToEpoch is not None:
                    try:
                        validTo = datetime.fromtimestamp(validToEpoch / 1000, UTC)
                    except (ValueError, TypeError, OSError):
                        pass

                links = [
                    WarningLink(
                        url=link.get("url"),
                        text=link.get("text"),
                        alt_url=link.get("altUrl"),
                    )
                    for link in warningJson.get("links") or []
                    if isinstance(link, dict)
                ]
                text = warningJson.get("text")
                ordering = warningJson.get("ordering")
                warnings.append(
                    Warning(
                        warningType=parse_warning_type(raw_type),
                        warningLevel=parse_warning_level(raw_level),
                        text=text,
                        htmlText=warningJson.get("htmlText"),
                        outlook=bool(warningJson.get("outlook")),
                        validFrom=validFrom,
                        validTo=validTo,
                        links=links,
                        ordering=ordering,
                        raw_type=raw_type,
                        raw_level=raw_level,
                        fingerprint=build_warning_fingerprint(
                            raw_type,
                            raw_level,
                            validFrom,
                            validTo,
                            ordering,
                            text,
                        ),
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                parse_errors += 1
                logger.error("Failed to parse warning", exc_info=True)

        if warningsJson and parse_errors == len(warningsJson):
            raise MeteoSwissDataError("Failed to parse MeteoSwiss warnings payload")

        return warnings

    async def _async_get_current_weather_line_for_station(self, station):
        if station is None:
            return None
        data = await self._async_get_csv_dictionary_for_url(CURRENT_CONDITION_URL)
        if data is None:
            return None
        return next(
            (
                row
                for row in data
                if row.get("Station/Location", "").casefold() == station.casefold()
            ),
            None,
        )

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
            raise MeteoSwissConnectionError(
                f"Failed to fetch MeteoSwiss CSV from {url}"
            ) from err
        except (UnicodeDecodeError, csv.Error) as err:
            raise MeteoSwissDataError(
                f"Invalid MeteoSwiss CSV payload from {url}"
            ) from err

    def _build_forecast_query_value(
        self, postCode, forecastPointType: str | None = None
    ) -> str:
        normalized = str(postCode).strip()
        if forecastPointType == "2":
            return normalized if len(normalized) != 4 else normalized.ljust(6, "0")
        if forecastPointType == "3":
            return normalized
        if normalized.isdigit() and len(normalized) == 4:
            return normalized.ljust(6, "0")
        return normalized

    async def _async_get_forecast_json(
        self, postCode, language, forecastPointType: str | None = None
    ):
        query_value = self._build_forecast_query_value(postCode, forecastPointType)
        url = FORECAST_URL.format(query_value)
        logger.debug("Requesting forecast data from %s...", url)
        try:

            async def _parse_json(response):
                return await response.json()

            return await async_get_with_retry(
                self._session,
                url,
                logger=logger,
                response_handler=_parse_json,
                headers={
                    "User-Agent": FORECAST_USER_AGENT,
                    "Accept-Language": language,
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError) as err:
            raise MeteoSwissConnectionError(
                f"Failed to fetch MeteoSwiss forecast from {url}"
            ) from err
        except ValueError as err:
            raise MeteoSwissDataError(
                f"Invalid MeteoSwiss forecast payload from {url}"
            ) from err
