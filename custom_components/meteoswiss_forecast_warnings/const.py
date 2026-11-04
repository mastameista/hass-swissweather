"""Constants for the MeteoSwiss Forecast & Warnings integration."""

DOMAIN = "meteoswiss_forecast_warnings"
# Domain this integration grew out of (izacus/hass-swissweather); its config
# entries can be taken over, keeping entity IDs and history.
LEGACY_DOMAIN = "swissweather"
# Marks an entry created from a legacy entry until the takeover has run.
CONF_IMPORTED_FROM = "importedFromEntryId"

CONF_STATION_CODE = "stationCode"
CONF_POLLEN_STATION_CODE = "pollenStationCode"
CONF_POST_CODE = "postCode"
CONF_FORECAST_POINT_TYPE = "forecastPointType"
CONF_WARNINGS_ENABLED = "warningsEnabled"
CONF_WEATHER_WARNINGS_NUMBER = "weatherWarningsNumber"
CONF_FORECAST_NAME = "forecastName"
CONF_STATION_NAME = "stationName"
CONF_POLLEN_STATION_NAME = "pollenStationName"
