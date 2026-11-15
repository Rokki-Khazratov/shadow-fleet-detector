# Зависимости разработки

Проверка 2026-11-14: установленные метаданные и лицензионные файлы дистрибутивов; компоненты используются для локальной разработки.

| Пакет | Версия | Лицензия | Источник |
|---|---|---|---|
| pytest | 8.4.2 | MIT | https://pypi.org/project/pytest/8.4.2/ |
| ruff | 0.14.6 | MIT | https://pypi.org/project/ruff/0.14.6/ |
| iniconfig | 2.3.1 | MIT | https://pypi.org/project/iniconfig/2.3.1/ |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://pypi.org/project/packaging/26.3/ |
| pluggy | 1.7.0 | MIT | https://pypi.org/project/pluggy/1.7.0/ |
| Pygments | 2.21.0 | BSD-2-Clause | https://pypi.org/project/Pygments/2.21.0/ |

Условия включения этих компонентов в распространяемый продукт и необходимые уведомления проверяются отдельно. Собственная лицензия проекта не выбрана.

## Драйвер базы данных (локальная разработка)

Проверка 2026-11-14: метаданные и файлы лицензий установленных Python-дистрибутивов.

| Пакет | Версия | Лицензия | Источник |
|---|---|---|---|
| psycopg | 3.2.13 | LGPL-3.0-only | https://pypi.org/project/psycopg/3.2.13/ |
| psycopg-binary | 3.2.13 | LGPL-3.0-only | https://pypi.org/project/psycopg-binary/3.2.13/ |
| typing-extensions | 4.16.0 | PSF-2.0 | https://pypi.org/project/typing-extensions/4.16.0/ |

Для распространения необходимо отдельно проверить и включить уведомления вложенных библиотек бинарного дистрибутива и контейнерного образа; этот список не является готовым комплектом для релиза.

## API и тестовый HTTP-клиент

Проверка 2026-11-14: метаданные установленных дистрибутивов; для FastAPI также проверен файл LICENSE. Пакеты используются локально; комплект уведомлений для распространения и лицензии вложенных бинарных компонентов ещё требуют проверки.

| Пакет | Версия | Лицензия | Источник |
|---|---|---|---|
| fastapi | 0.115.12 | MIT | https://pypi.org/project/fastapi/0.115.12/ |
| uvicorn | 0.34.3 | BSD-3-Clause | https://pypi.org/project/uvicorn/0.34.3/ |
| httpx | 0.28.1 | BSD-3-Clause | https://pypi.org/project/httpx/0.28.1/ |
| anyio | 4.9.0 | MIT | https://pypi.org/project/anyio/4.9.0/ |
| annotated-types | 0.8.0 | MIT | https://pypi.org/project/annotated-types/0.8.0/ |
| certifi | 2026.10.23 | MPL-2.0 | https://pypi.org/project/certifi/2026.10.23/ |
| click | 8.5.1 | BSD-3-Clause | https://pypi.org/project/click/8.5.1/ |
| h11 | 0.16.0 | MIT | https://pypi.org/project/h11/0.16.0/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://pypi.org/project/httpcore/1.0.9/ |
| idna | 3.20 | BSD-3-Clause | https://pypi.org/project/idna/3.20/ |
| pydantic | 2.14.3 | MIT | https://pypi.org/project/pydantic/2.14.3/ |
| pydantic-core | 2.50.4 | MIT | https://pypi.org/project/pydantic-core/2.50.4/ |
| starlette | 0.46.2 | BSD-3-Clause | https://pypi.org/project/starlette/0.46.2/ |
| typing-inspection | 0.4.5 | MIT | https://pypi.org/project/typing-inspection/0.4.5/ |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | https://pypi.org/project/sniffio/1.3.1/ |

## Пакеты браузерного клиента (draft)

Проверка 2026-11-14: версии и сведения из package.json установленных npm-пакетов. Перед распространением требуется сверить LICENSE и полные notices, включая транзитивные и платформенные компоненты; этот перечень не является готовым комплектом релиза.

| Пакет | Версия | Метаданные лицензии |
|---|---|---|
| bidi-js | 1.1.0 | MIT |
| earcut | 3.2.4 | ISC |
| esbuild | 0.28.2 | MIT |
| fdir | 6.5.0 | MIT |
| fsevents | 2.3.2 | MIT |
| gl-matrix | 3.4.4 | MIT |
| json-stringify-pretty-compact | 4.0.0 | MIT |
| kdbush | 4.1.0 | ISC |
| maplibre-gl | 6.18.0 | BSD-3-Clause |
| minimist | 1.2.8 | MIT |
| murmurhash-js | 1.0.0 | MIT |
| nanoid | 3.3.20 | MIT |
| pbf | 5.1.2 | BSD-3-Clause |
| picocolors | 1.1.1 | ISC |
| picomatch | 4.0.7 | MIT |
| playwright | 1.56.1 | Apache-2.0 |
| playwright-core | 1.56.1 | Apache-2.0 |
| postcss | 8.5.33 | MIT |
| potpack | 2.1.0 | ISC |
| protocol-buffers-schema | 3.6.1 | MIT |
| quickselect | 3.0.0 | ISC |
| require-from-string | 2.0.2 | MIT |
| resolve-protobuf-schema | 2.1.0 | MIT |
| rollup | 4.68.3 | MIT |
| source-map-js | 1.2.2 | BSD-3-Clause |
| tinyglobby | 0.2.17 | MIT |
| tinyqueue | 3.0.0 | ISC |
| typescript | 5.9.3 | Apache-2.0 |
| vite | 7.3.8 | MIT |
| @esbuild/darwin-arm64 | 0.28.2 | MIT |
| @mapbox/jsonlint-lines-primitives | 2.0.3 | MIT |
| @mapbox/point-geometry | 1.1.0 | ISC |
| @mapbox/tiny-sdf | 2.3.0 | BSD-2-Clause |
| @mapbox/unitbezier | 1.0.0 | BSD-2-Clause |
| @mapbox/vector-tile | 3.0.0 | BSD-3-Clause |
| @maplibre/geojson-vt | 6.3.1 | ISC |
| @maplibre/maplibre-gl-style-spec | 26.8.0 | ISC |
| @maplibre/mlt | 1.3.0 | (MIT OR Apache-2.0) |
| @maplibre/vt-pbf | 4.3.3 | MIT |
| @playwright/test | 1.56.1 | Apache-2.0 |
| @rollup/rollup-darwin-arm64 | 4.68.3 | MIT |
| @types/estree | 1.0.10 | MIT |
| @types/geojson | 7946.0.16 | MIT |

## MQTT

Проверка 2026-11-14: метаданные и файл лицензии установленного пакета. `paho-mqtt` 2.1.0 — EPL-2.0 OR BSD-3-Clause (метаданные; файл лицензии указывает EPL 2.0 и Eclipse Distribution License 1.0). Источник: https://pypi.org/project/paho-mqtt/2.1.0/. Полные условия и уведомления необходимо проверить до распространения.
