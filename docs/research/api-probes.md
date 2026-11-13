# Проверка источников и API

Дата исследования: 2026-11-13. Это реальные ограниченные Python-пробы, не готовые интеграции. Каждый JSON содержит время UTC, адрес, результат, длительность; HTTP-ответы содержат хеш прочитанного тела. Полные наборы данных не сохранялись.

## Результаты

| Проба | HTTP | Результат | Артефакт |
|---|---|---|---|
| aisstream_docs | 200 | http_success | [JSON](../../research/probes/results/aisstream_docs.json) |
| danish_catalog | 200 | http_success | [JSON](../../research/probes/results/danish_catalog.json) |
| digitraffic_locations | 200 | http_success | [JSON](../../research/probes/results/digitraffic_locations.json) |
| digitraffic_locations_initial_406 | 406 | http_error | [JSON](../../research/probes/results/digitraffic_locations_initial_406.json) |
| digitraffic_vessels | 200 | http_success | [JSON](../../research/probes/results/digitraffic_vessels.json) |
| digitraffic_vessels_initial_406 | 406 | http_error | [JSON](../../research/probes/results/digitraffic_vessels_initial_406.json) |
| gfw_without_token | 401 | http_error | [JSON](../../research/probes/results/gfw_without_token.json) |
| kystverket_tcp | — | transport_error | [JSON](../../research/probes/results/kystverket_tcp.json) |
| noaa_catalog | 200 | http_success | [JSON](../../research/probes/results/noaa_catalog.json) |
| opensanctions_catalog | 200 | http_success | [JSON](../../research/probes/results/opensanctions_catalog.json) |

## Digitraffic: реальный JSON позиций и метаданных

[Официальная документация](https://www.digitraffic.fi/en/marine-traffic/). GET `/api/ais/v1/locations` и `/api/ais/v1/vessels`. Первые запросы получили 406: сервер потребовал `Accept-Encoding: gzip`. После добавления заголовка и декомпрессии оба вернули 200. В снимке 814 объектов позиций и 793 записи метаданных. Это размеры конкретных ответов, не число всех судов региона. Снимки получены раздельно и не обязаны совпадать по составу.

Позиции — GeoJSON FeatureCollection; координаты `[longitude, latitude]`. В сохранённом примере `timestamp` равен 11, а `timestampExternal` — 1794594912508: первое поле нельзя интерпретировать как полный Unix timestamp. Время поступления и время наблюдения нужно разделять и сверять по схеме REST. MQTT имеет другой контракт; REST-парсер нельзя переносить без проверки. Метаданные содержат MMSI, IMO, имя, destination, shipType; встречается IMO=0, который нельзя считать действительным идентификатором.

Образцы — первые две записи каждого ответа; это не выборка для выводов о флоте. Ни одной записи не присвоен статус подозрительной. Полный поток, MQTT, восстановление соединения и длительная свежесть не тестировались.

Данные: Fintraffic / digitraffic.fi, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [Условия и атрибуция](https://www.digitraffic.fi/en/terms-of-service/). Изменения при сохранении: ответ сокращён до двух записей и помещён в диагностическую оболочку; исходные значения сохранены. Данные предоставляются источником без гарантии пригодности; один успешный ответ не является SLA.

## AISstream: документация доступна, поток ещё не проверен

[Документация](https://www.aisstream.io/documentation/) вернула 200; это проверка страницы, не WebSocket. Для `wss://stream.aisstream.io/v0/stream` нужен персональный ключ. Используются JSON-подписка с BoundingBoxes и типами сообщений, бинарные фреймы с UTF-8 JSON. Ключ должен оставаться серверным. По документации нет durable replay/SLA; нужна обработка потерь. Полноту глобального покрытия не предполагаем. Подписка только на PositionReport исключит другие типы AIS, поэтому противоречит задаче «все типы судов».

Проверка с ключом остаётся открытой; никакие ключи не запрашивались из чужих файлов и не публиковались. Условия хранения/перераспространения требуют отдельного подтверждения до публичного накопления потока.

## Global Fishing Watch: ожидаемый отказ без токена

Реальный GET `/v3/vessels/search?query=EXAMPLE` вернул 401 и `{"error":"invalid token"}`. Это подтверждает границу аутентификации, но не валидирует контракт успешного поиска или доступность конкретного dataset. [Официальная аутентификация](https://globalfishingwatch.org/our-apis/documentation/docs/authentication): персональный Bearer-токен и согласие с условиями. GFW рассматриваем для внешнего контекста/событий, не как доказанную замену live AIS.

## Kystverket: сетевой тайм-аут

[Официальный адрес](https://www.kystverket.no/en/sea-transport-and-ports/ais/access-to-ais-data/) — TCP `153.44.253.27:5631`. Две ограниченные попытки завершились тайм-аутом. Причина не установлена: маршрут, фильтрация, сервис или среда. Признавать источник неработающим нельзя. Формат по документации NMEA/IEC, а не JSON; нужен отдельный декодер. Ограничения открытого покрытия и атрибуцию проверять отдельно от закрытого доступа.

## OpenSanctions: каталог доступен

GET каталога вернул 200 и JSON. Сущности, совпадения и данные отдельных судов не загружались. [Правила некоммерческого использования](https://www.opensanctions.org/docs/commercial/exemption/) и [bulk access](https://www.opensanctions.org/docs/bulk/updates/): бесплатность зависит от характера использования; hosted API и bulk не одно и то же. Совпадение имени не подтверждает идентичность; санкционный статус не эквивалентен теневому флоту.

## NOAA и Danish AIS: доступны страницы, данные ещё не проверены

Официальные страницы вернули 200: [NOAA metadata](https://www.fisheries.noaa.gov/inport/item/80362), [Danish AIS](https://www.dma.dk/safety-at-sea/navigational-information/ais-data). Архивы не скачивались, схемы и пригодность временного периода не доказаны. Их исследование относится прежде всего к истории и валидации; наличие каталога не доказывает доступный live-поток.

## Решение для следующего исследования

Предложение: начать проверку нормализации на Digitraffic, затем подключить AISstream после получения ключа и проверки условий. Это порядок испытаний, а не ограничение глобального продукта Финляндией. GFW/OpenSanctions подключать независимыми каналами evidence. Kystverket повторить из другой сети перед выводами о доступности.

## Воспроизведение

`python3 research/probes/probe_sources.py`

Только стандартная библиотека. Семь GET-запросов и одна краткая TCP-проба; HTTP timeout 20 секунд, TCP 10 секунд, ограничение тела 8 MB, сохраняются максимум две записи AIS. Скрипт перезаписывает основные результаты; initial_406 сохранены отдельно. Нужен сетевой доступ. Нет приложения, фонового сервиса, БД или автоматических повторов. Время машины и серверное Date записываются отдельно.

## Открытые проверки

- AISstream authenticated subscription, Class A/B/static messages, reconnect и условия распространения.
- Digitraffic MQTT, полная семантика REST-времени, sentinels, возраст всех позиций и географическое покрытие.
- GFW: конкретный dataset, sample успешного ответа, лимиты аккаунта.
- Исторические архивы: маленький разрешённый sample, схема и доступность.
- Сопоставление identity: временные MMSI, IMO, смена названий, конфликт источников.
