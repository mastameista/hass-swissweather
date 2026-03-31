# MeteoSwiss integration for Home Assistant

This custom integration adds weather data from [MeteoSwiss](https://www.meteoschweiz.admin.ch/#tab=forecast-map) to Home Assistant.

It combines three MeteoSwiss data sources behind one config entry:

* A forecast place for hourly and daily forecast data
* An optional live weather station for current measurements such as temperature, precipitation, humidity, wind, and pressure
* An optional pollen station for local pollen measurements

The integration currently provides:

* A Home Assistant weather entity for the selected MeteoSwiss forecast place
* Current weather sensors from a nearby measurement station
* Weather warning entities for the selected forecast place
* Optional pollen sensors and pollen level sensors from a selected pollen station

## What gets created

Depending on your configuration, the integration creates up to three logical devices:

* **Forecast place**: the weather entity plus warning entities
* **Weather station**: current weather sensors
* **Pollen station**: pollen sensors and pollen level sensors

The warning model in this fork is:

* `has_warnings`
* `warning_count`
* `highest_warning_level`
* `primary_warning`
* `secondary_warning`
* `tertiary_warning`

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=izacus&repository=hass-swissweather&category=integration)

### With HACS

1. Go to HACS page in Home Assistant
2. Click "three dots" in upper right corner and select "Custom Repositories..."
3. Enter `https://github.com/izacus/hass-swissweather` into "Repository" field
4. Select "Integration"
5. Click "Add"
6. On "Integrations" tab click "Explore And Download Repositories"
7. Enter "Swiss Weather" in search box and download the integration
8. Restart HASS

### Configure integration

Add the Swiss Weather integration in Home Assistant and follow the config flow:

1. **Search forecast place**
   Search by place name, postal code, MeteoSwiss forecast point ID, or points of interest such as peaks, passes, and huts.
2. **Select forecast place**
   Choose the exact forecast place you want to use.
3. **Choose stations**
   Select the optional weather station and optional pollen station you want to use.
4. **Enable warnings**
   Decide whether warning entities should be created for the selected forecast place.

Configuration options:

* **Forecast place**: Used for the weather entity, hourly and daily forecast, and weather warnings.
* **Weather station for current weather state**: Optional live measurement station. When configured, the weather entity uses this station for current conditions and the forecast place for the forecast. Choose a nearby station within reason, especially with altitude differences in mind.
* **Pollen measuring station**: Optional pollen station for pollen entities.
* **Create weather warning entities**: Enables the warning entities for the selected forecast place.

You can reconfigure an existing entry later to change the weather station, pollen station, or warning setting without creating a new entry.

## Notes and limitations

* Forecast data is based on the selected MeteoSwiss forecast place.
* If a weather station is selected, current conditions in the weather entity and the current weather sensors come from that live measurement station.
* If no weather station is selected, the weather entity falls back to MeteoSwiss forecast data for current conditions and no current weather sensors are created.
* Pollen entities are only created when a pollen station is selected.
* The integration depends on MeteoSwiss forecast and station metadata being available. If MeteoSwiss changes or temporarily removes metadata, the integration may ask you to reconfigure the affected entry.

## Migration notes

This fork uses a redesigned warning model with a warning summary and three prioritized warning slots (`primary`, `secondary`, `tertiary`) instead of the older numbered warning entities. Existing users migrating from older versions should update dashboards or template references if they still point to the legacy warning entities.

## Removing the integration

This integration follows standard Home Assistant integration removal.

1. Go to **Settings > Devices & Services > Integrations**
2. Open **Swiss Weather**
3. Select **Delete**

If you installed the integration through HACS and no longer want to keep the custom repository installed, remove it from HACS after deleting the integration from Home Assistant.
