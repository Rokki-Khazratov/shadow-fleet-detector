# Fintraffic: сопоставление полей

Проверено 2026-11-14: [OpenAPI](https://meri.digitraffic.fi/swagger/openapi.json), [описание MQTT](https://www.digitraffic.fi/en/marine-traffic/) и локальные агрегированные результаты проб. Синтетические тесты не подтверждают доступность сервиса.

| Канал | Идентификатор | Координаты | Время | Движение |
|---|---|---|---|---|
| REST GeoJSON Feature | properties.mmsi; id при наличии сверяется | geometry.coordinates: долгота, широта | properties.timestampExternal, Unix миллисекунды | properties.sog, cog, heading |
| MQTT location | MMSI в topic; mmsi в payload при наличии сверяется | lon, lat | time, Unix секунды | sog, cog, heading |

Документация содержит оба варианта location/locations; пример и локальная проба подтверждают topic с singular `location`. Проверка дополнительного MMSI в payload — защитное правило проекта, а не утверждение, что поле присутствует всегда. Поле REST `timestamp` обозначает секунду AIS и не заменяет полную дату.
