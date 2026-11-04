# MeteoSwiss Forecast & Warnings

**Unofficial** Home Assistant integration for Swiss weather data from MeteoSwiss: the local forecast as the MeteoSwiss app shows it, every official weather warning for your place (including drought, active and upcoming), live measurements from a weather station and pollen counts.

> [!NOTE]
> This project is not affiliated with, endorsed by or supported by the Federal Office of Meteorology and Climatology MeteoSwiss. It uses publicly reachable MeteoSwiss data; see [Data sources](#data-sources) and [Known limitations](#known-limitations).

## Features

- **Forecast as in the MeteoSwiss app** – a weather entity with hourly forecasts (about 7 days) and daily forecasts (8 days, today included) for a postal code, a place or a point of interest such as a peak, pass or hut.
- **All weather warnings** – wind, thunderstorms, rain, snow, slippery roads, frost, thaw, heat waves, avalanches, earthquakes, forest fires, floods and drought. Warnings that are already in force are told apart from announced ones.
- **Live measurements** – optional: temperature, precipitation, sunshine, global radiation, humidity, dew point, wind, gusts and air pressure from an automatic MeteoSwiss station of your choice. The weather entity then shows the measured current conditions.
- **Pollen** – optional: birch, grasses, alder, hazel, beech, ash and oak, as counts and as levels.
- Languages: English, German, French and Italian. Warning texts follow your Home Assistant language.
- Diagnostics, repair issues when MeteoSwiss removes a configured station, and reconfiguration without losing entities.

## Use cases

- Get a notification when a warning of level 3 or higher comes into force for your place, or ahead of it with `next_warning_start`.
- Retract awnings and close blinds when a wind or thunderstorm warning is announced.
- Pause irrigation during rain warnings, or remember watering bans during a drought warning.
- Show the forecast and the warnings on a wall tablet.
- Warn allergy sufferers when birch or grass pollen reach a strong level.

## Installation

The integration needs Home Assistant **2026.10** or newer.

### With HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mastameista&repository=ha-meteoswiss-forecast-warnings&category=integration)

1. In HACS, open the menu (three dots, top right) and select **Custom repositories**.
2. Enter `https://github.com/mastameista/ha-meteoswiss-forecast-warnings`, select the type **Integration** and select **Add**.
3. Search for **MeteoSwiss Forecast & Warnings** and download it.
4. Restart Home Assistant.

### Manually

Copy the folder `custom_components/meteoswiss_forecast_warnings` into the `custom_components` folder of your Home Assistant configuration and restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=meteoswiss_forecast_warnings)

Go to **Settings → Devices & services → Add integration** and search for **MeteoSwiss Forecast & Warnings**. Add one entry per place.

| Step | Parameter | Description |
|---|---|---|
| Forecast place | Forecast place search | A place name, a postal code (for example `8001`), a MeteoSwiss forecast point ID or a point of interest such as a peak, pass or hut. |
| Select forecast place | Matching forecast places | The place to use for the forecast and the warnings. |
| Stations | Weather station for current conditions | An automatic station for live measurements, sorted by distance to your Home location. Pick a station at a similar altitude: a summit station a few kilometres away measures something else than the valley. Select **No weather station** to take current conditions from the forecast. |
| | Pollen measuring station | A station for pollen counts, or **No pollen station**. |
| | Create weather warning entities | Creates the warning entities for the forecast place. |

To change the stations or the warning setting later, open the entry and select **Reconfigure**. Entity IDs and history stay the same.

### Coming from Swiss Weather

If the integration [Swiss Weather](https://github.com/izacus/hass-swissweather) (`swissweather`) is set up, adding this integration first offers to **take over the existing entries**. Entity IDs, history, areas, device names, dashboards and automations stay as they are; the Swiss Weather entries are removed afterwards. A repair issue then reminds you to remove Swiss Weather in HACS.

Swiss Weather keeps all entities of an entry on one device. This integration splits them over a forecast, a weather station and a pollen device and gives those the area of the old device. The warning entities of Swiss Weather (`most_severe_weather_warning`, `weather_warning_2` and so on) are replaced by the warning entities described below; dashboards and automations that use them need updating.

## Entities

Each entry creates up to three devices.

### Forecast place

| Entity | Description |
|---|---|
| Weather | Current conditions and hourly and daily forecasts (`weather.get_forecasts`). Current conditions come from the weather station if one is configured. |
| Has weather warnings | On while at least one warning is in force or announced. |
| Has active weather warnings | On while at least one warning is in force. |
| Weather warning count | Number of warnings. Attributes: `active_count`, `upcoming_count`, `next_warning_start`. |
| Highest weather warning level | Highest level of the current warnings, 1 to 5; no value while there are no warnings. Attributes: `level_name`, `icon_color`. |
| Primary, secondary and tertiary weather warning | The three most severe warnings: highest level first; at equal level, warnings in force before announced ones, then by start. State: warning type, `none` without a warning. Attributes: `warning_level`, `level_name`, `valid_from`, `valid_to`, `active`, `outlook`, `text`, `html_text`, `links`, `icon_color`. |

Warning levels: 1 no or minimal danger, 2 moderate, 3 considerable, 4 high, 5 very high danger.

### Weather station

Temperature, precipitation (10 min), sunshine (10 min), global radiation, relative humidity, dew point, wind direction, wind speed, wind gusts (peak 1 s), air pressure at station level and at sea level (QFF). The sea-level pressure QNH and the measurement time are disabled by default; enable them under the device if you need them.

### Pollen station

For each of the seven pollen types a count in particles/m³ (`p/m³`) and a level (`None`, `Low`, `Medium`, `Strong`, `Very Strong`). The measurement time is disabled by default.

## Examples

Notify when a warning of level 3 or higher comes into force:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.zurich_highest_weather_warning_level
    above: 2
conditions:
  - condition: state
    entity_id: binary_sensor.zurich_has_active_weather_warnings
    state: "on"
actions:
  - action: notify.notify
    data:
      title: >-
        {{ state_attr('sensor.zurich_primary_weather_warning', 'level_name') }}:
        {{ states('sensor.zurich_primary_weather_warning') }}
      message: "{{ state_attr('sensor.zurich_primary_weather_warning', 'text') }}"
```

Show the forecast in a dashboard:

```yaml
type: weather-forecast
entity: weather.zurich
forecast_type: daily
```

Replace `zurich` with the entity IDs of your place.

## Data updates

The integration polls MeteoSwiss; nothing is pushed.

- Forecast, warnings and weather station: every 10 minutes. The stations publish new values every 10 minutes.
- Pollen: every 60 minutes. Pollen counts are published once an hour.
- Warning entities also switch at the exact start and end of a warning, between two updates.

If MeteoSwiss cannot be reached, the integration retries the request and keeps its entities unavailable until data arrives again. A failed warning download makes the warning entities unavailable; it never shows up as "no warnings".

## Data sources

| Data | Source |
|---|---|
| Forecast and warnings | The MeteoSwiss app backend (`app-prod-ws.meteoswiss-app.ch`), the same data as the MeteoSwiss app and website |
| Weather station measurements | MeteoSwiss open data, current values of the SwissMetNet stations |
| Pollen | MeteoSwiss pollen measurements |
| Station and forecast place lists | MeteoSwiss open data and geo.admin.ch |

## Known limitations

- **Undocumented forecast endpoint.** MeteoSwiss does not document the app backend. If MeteoSwiss changes it, the forecast and the warnings stop until the integration is adapted. The official open-data forecast is not an alternative for a single place: it comes as files covering all of Switzerland, several hundred megabytes per update.
- Forecasts reach 8 days ahead, today included, as in the app.
- MeteoSwiss occasionally renames or removes stations. The integration then opens a repair issue; reconfigure the entry and choose another station.
- Not every station measures every value. Sensors for values a station does not measure have no value (`unknown`).
- Pollen stations report no counts outside the pollen season.

## Troubleshooting

- **Entities are unavailable.** Check the log for messages from `meteoswiss_forecast_warnings`. Short MeteoSwiss outages resolve themselves at the next update.
- **A repair issue says a station is missing.** Open the entry, select **Reconfigure** and choose another station.
- **Current values look wrong.** Check which weather station the entry uses. A distant station or one at another altitude measures different conditions.
- **Reporting a problem.** Download the diagnostics (entry menu → **Download diagnostics**) and attach them to an [issue](https://github.com/mastameista/ha-meteoswiss-forecast-warnings/issues). Diagnostics leave out the configured places, stations and coordinates.

Debug logging:

```yaml
logger:
  logs:
    custom_components.meteoswiss_forecast_warnings: debug
```

## Removal

1. Go to **Settings → Devices & services**, open **MeteoSwiss Forecast & Warnings** and delete each entry.
2. If you installed with HACS, remove the integration in HACS. Otherwise delete the folder `custom_components/meteoswiss_forecast_warnings`.
3. Restart Home Assistant.

## Credits and license

This integration grew out of [Swiss Weather](https://github.com/izacus/hass-swissweather) by Jernej Virag and keeps its history. Licensed under the [Apache License 2.0](LICENSE).

Weather data © MeteoSwiss. The name MeteoSwiss and the app icon used as this integration's icon belong to the Federal Office of Meteorology and Climatology MeteoSwiss.
