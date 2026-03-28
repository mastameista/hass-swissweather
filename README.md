# MeteoSwiss integration for HASS

This is an integration to download data from [MeteoSwiss](https://www.meteoschweiz.admin.ch/#tab=forecast-map).

It currently supports:
  * Current weather state - temperature, precipitation, humidity, wind, etc. for a given autmated measurement station.
  * Hourly and daily weather forecast based on a location encoded with post nurmber, including the 8-day MeteoSwiss forecast.
  * Weather warnings (e.g. floods, fires, earthquake dangers, etc.) for the set location.
  * Pollen measurement status across a set of automated stations.

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

Add Swiss Weather integration to Home Assistant. You'll be asked for a few pieces of information:

* **Post Code**: The post code of your location, used for forecast and weather alerts - e.g. 8001 for Zurich.
* **Station code**: The station code of weather station measuring live data near you. Choose the closest station within reason - e.g. it probably doesn't make sense to select "Uetliberg" to get data in Zurich due to altitude difference. Choose Kloten on Fluntern instead. If not set, limited data will be pulled from the forecast.
* **Pollen station code**: The station code of pollen measurement station for pollen data. Same rules apply as before.
* **Create weather warning entities**: Enables warning entities for the selected forecast place. When enabled, the integration creates `has_warnings`, `warning_count`, `highest_warning_level`, and three prioritized warning slots: `primary`, `secondary`, and `tertiary`.

### Example Weather Alert mushroom card

Example mushroom cards that show the primary warning first and only reveal secondary / tertiary slots when they currently exist:

```yaml
type: custom:mushroom-template-card
icon: mdi:alert
primary: >
  {{ states('sensor.primary_weather_warning_8000') | replace('_', ' ') | title }}
secondary: "{{ state_attr('sensor.primary_weather_warning_8000', 'text') }}"
icon_color: >
  {{ state_attr('sensor.primary_weather_warning_8000', 'icon_color') }}
badge_color: red
badge_icon: |
  {% set number_of_warnings = states('sensor.weather_warning_count_8000') | int %}
  {% if number_of_warnings > 9 %}
    mdi:numeric-9-plus
  {% elif number_of_warnings > 1 and number_of_warnings < 10 %}
    mdi:numeric-{{ number_of_warnings }}
  {% endif %}
multiline_secondary: true
tap_action:
  action: more-info
  entity: sensor.primary_weather_warning_8000
visibility:
  - condition: state_not
    entity: sensor.primary_weather_warning_8000
    state: "unknown"
---
type: custom:mushroom-template-card
icon: mdi:alert-outline
primary: >
  {{ states('sensor.secondary_weather_warning_8000') | replace('_', ' ') | title }}
secondary: "{{ state_attr('sensor.secondary_weather_warning_8000', 'text') }}"
icon_color: >
  {{ state_attr('sensor.secondary_weather_warning_8000', 'icon_color') }}
multiline_secondary: true
visibility:
  - condition: state_not
    entity: sensor.secondary_weather_warning_8000
    state: "unknown"
---
type: custom:mushroom-template-card
icon: mdi:alert-outline
primary: >
  {{ states('sensor.tertiary_weather_warning_8000') | replace('_', ' ') | title }}
secondary: "{{ state_attr('sensor.tertiary_weather_warning_8000', 'text') }}"
icon_color: >
  {{ state_attr('sensor.tertiary_weather_warning_8000', 'icon_color') }}
multiline_secondary: true
visibility:
  - condition: state_not
    entity: sensor.tertiary_weather_warning_8000
    state: "unknown"
```
