# Первый локальный срез — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, если навык доступен. При его отсутствии следовать этому документу последовательно. Подагенты не требуются. **Сейчас только план: реализацию не начинать.**

**Goal:** локальная карта последних доступных наблюдений Fintraffic с честным возрастом и состоянием источника.
**Architecture:** collector — единственный писатель PostgreSQL/PostGIS; отдельный API читает проекцию; браузер опрашивает API. Сначала нормализатор и merge на синтетике, затем БД и транспорт, затем интерфейс.
**Tech Stack:** draft Python 3.12 / pytest / psycopg / Paho / FastAPI; PostgreSQL/PostGIS; Vite / TypeScript / MapLibre / Playwright. Точные версии проверить и закрепить при реализации; не использовать floating latest для образов.
**Spec:** [ТЗ](../../architecture/technical-spec.md), [система](../../architecture/system-design.md), [БД](../../architecture/database-design.md), [контракт исполнителя](../../handoff/implementation-contract.md). Все документы обязательны, план не заменяет спецификацию.

Дата: 2026-11-14. Это предложение порядка разработки для экономной модели. Владелец пока не разрешил выполнять его.

## Global Constraints

- Один региональный источник, локальный запуск, без истории и доказательных меток теневого флота.
- API max 2000 позиций; fresh ≤300 s, TTL 24 h; ограничения транспорта из контракта.
- Никаких raw datasets и секретов в Git; только синтетические fixtures, агрегаты результатов.
- Сначала проверяемый контент задачи, затем реализация, затем проверки; никогда не сообщать pass без выполненной команды.
- Зафиксировать исходный `git status`; не присваивать существующие изменения себе. Запрещены git reset --hard, checkout поверх изменений, clean, git add ., автоматический push/deploy.
- Изменять AGENTS.md для этапа реализации только после нового явного разрешения владельца; исторические ограничения не стирать. Текущее «не начинать» имеет приоритет над шаблонами промптов.
- Нет собственного LICENSE: не выбирать за владельца. Проверять notices зависимостей и данные отдельно.
- Публичные API не вызываются в автоматических тестах. Сетевой smoke только после отдельного разрешения на конкретный bounded run.
- Одна задача ниже = одна завершённая поставка. После неё остановиться, представить проверку и ждать следующей задачи. Отдельный commit допустим после проверки, если пользователь разрешил commits; иначе оставить точный diff.

## Review Focus

1. Смена подключения одновременно с callback: старый epoch не пишет БД — задачи 3, 4.
2. Валидные нули/повреждённые необязательные поля: не терять неподвижные суда — задача 1.
3. REST и MQTT имеют разную точность времени: итог не зависит от порядка — задача 2.
4. Источник/БД/браузер восстанавливаются независимо: сохранённые данные не выглядят live — задачи 4–6.
5. Пограничные координаты и время: ±180, ровно 24 h, +60 s, NaN — задачи 1, 3, 5.

## Дерево будущих файлов

```text
pyproject.toml                     пакет, команды, test/lint конфигурация
requirements.lock                  точные Python зависимости, выбранный формат записать
.env.example                       placeholders и документированные настройки
compose.yaml                       только локальная БД; не публичный deployment
src/shadow_fleet/
  __init__.py
  model.py                         canonical types, RejectCode
  fintraffic.py                    чистая нормализация, без сетевого I/O
  reconcile.py                     чистый merge
  settings.py                      проверка конфигурации
  store.py                         миграции, writer session, batch, TTL
  transport.py                     bounded REST и MQTT callback adapter
  collector.py                     lifecycle, epoch, buffer, health
  api.py                           read routes, validation, JSON
  __main__.py                      migrate / collect / api команды
 db/migrations/001_v01.sql          таблицы, ограничения, индексы, grants
 tests/
  fixtures/ais/                    синтетика + README происхождения
  test_fintraffic.py
  test_reconcile.py
  test_settings.py
  test_transport.py
  test_collector.py
  integration/test_store.py
  integration/test_api.py
 web/
  package.json, package-lock.json
  index.html, vite.config.ts, tsconfig.json
  src/main.ts, map.ts, api.ts, details.ts, styles.css
  tests/map.spec.ts
 docs/api/fintraffic-mapping.md
 docs/api/v1.md
 docs/run-local.md
 docs/development/progress.md
 docs/development/acceptance.md
 THIRD_PARTY_NOTICES.md
```

Путь `db/` находится в корне (пробел в дереве только для форматирования). Не создавать пустые будущие файлы заранее. README.md, .gitignore, AGENTS.md менять только по необходимости конкретной задачи. Новые runtime-зависимости добавлять на этапе их первого использования. Прототипы в research/probes остаются исследовательскими.

## Общий цикл задачи

- [ ] Прочитать интерфейс и зависимые документы; записать границы разрешённых файлов.
- [ ] Добавить целевые тесты и запустить: получить ожидаемое падение по отсутствующему поведению, а не из-за сломанного окружения.
- [ ] Реализовать минимальное поведение по контракту.
- [ ] Запустить целевые тесты, затем уже существующие затронутые тесты; lint/typecheck где настроены.
- [ ] Проверить diff на секреты, raw data, сторонние изменения и незапланированные зависимости.
- [ ] Обновить progress: задача, файлы, команды, exit codes, ограничения, следующая задача. Остановиться.

## Задача 1. Чистый контракт AIS и нормализатор

**Зависимость:** новое разрешение владельца начать только эту задачу.
**Файлы:** pyproject.toml, requirements.lock, src/shadow_fleet/{__init__,model,fintraffic}.py, tests/test_fintraffic.py, tests/fixtures/ais/*, docs/api/fintraffic-mapping.md, docs/development/progress.md, THIRD_PARTY_NOTICES.md; при необходимости .gitignore/.env.example. БД, API, UI не создавать.

**Interfaces:**
- `normalize_rest_feature(feature: Mapping[str, object], *, received_at: datetime) -> NormalizeResult`.
- `normalize_mqtt(topic: str, payload: Mapping[str, object], *, received_at: datetime) -> NormalizeResult`.
- `canonical_fingerprint(lon: float, lat: float, sog_kn: float | None, cog_deg: float | None, heading_deg: float | None) -> bytes`.
- Типы NormalizedPosition/Reject/ProjectedPosition определены в контракте; network/DB imports запрещены в model.py/fintraffic.py.

- [ ] Проверить Python 3.12 и git status; создать изолированный .venv только после разрешения на исполнение. Не менять системный Python. Настроить pytest и Ruff; указать команды установки dev dependencies и lock workflow.
- [ ] Проверить поля источника по официальным схемам и существующим пробам; записать mapping и checked_at, отличить проверенное поле от гипотезы. Если сеть недоступна, не выдумывать совместимость: завершить canonical часть, пометить adapter blocked.
- [ ] Написать table-driven синтетические cases: валидный REST/MQTT, числовой MMSI с zfill, несовпадение ID, missing timestampExternal, sentinel, нули, bool, NaN, infinity, latitude91, longitude181, +180, +60/+60.001 s, TTL ровно24h/+1ms.
- [ ] Проверить конкретные утверждения:

```python
assert canonical_fingerprint(25.0, 60.0, 0.0, None, None) == hashlib.sha256(
    b'[25.0,60.0,0.0,null,null]'
).digest()
assert normalized.sog_kn == 0.0  # для fixture с нулевой скоростью
assert normalized.provider_bucket == 1794679202  # fixture времени 2026-11-14T18:00:02Z; сверить константу перед закреплением
assert normalized.clock_skew is False  # received_at не раньше provider_time
assert rejected.code == 'id_mismatch'  # намеренно разные ID fixture
```

Значение epoch в примере — проверяемая константа, не разрешение подгонять данные под неё. Названия отдельных fixtures и construction выбрать в тестах, UTC даты фиксированные.

- [ ] Реализовать обе функции без чтения wall clock и без сетевых запросов.
- [ ] Запустить `.venv/bin/python -m pytest tests/test_fintraffic.py -q` и `.venv/bin/python -m ruff check src tests`. Успех — все случаи проходят, ноль ошибок lint. `git diff --check` без ошибок.
- [ ] Документировать прямые зависимости/версии/лицензионные источники. Доставить только нормализатор, не создавать collector «заодно».

## Задача 2. Детерминированное разрешение конфликтов

**Depends:** 1. **Files:** reconcile.py, tests/test_reconcile.py, progress.
**Consumes:** NormalizedPosition, ProjectedPosition.
**Produces:** `merge_position(current: ProjectedPosition | None, incoming: NormalizedPosition) -> ProjectedPosition`.

- [ ] Создать кандидаты a,b,c одного MMSI/bucket: REST разного millisecond, MQTT с другим fingerprint; fixture другой MMSI для отказа.
- [ ] Проверить каждую перестановку [a,b,c], повтор [a,b,c,a,b,c], старший/младший bucket, identical content через два транспорта, минимальный received_at, sticky conflict, сброс conflict на новой секунде.
- [ ] Реализовать только чистую merge-функцию, правила из контракта §4.
- [ ] Проверить `reduce(merge_position, permutation, None)` одинаков для всех перестановок и повторное применение не меняет итог. Пример assert: `assert merge_position(winner, older) == winner`.
- [ ] `.venv/bin/python -m pytest tests/test_reconcile.py tests/test_fintraffic.py -q`; все PASS. Этот эталон используется в store; не писать второй конкурирующий merge в SQL.

## Задача 3. БД, миграция, текущая проекция

**Depends:** 2. **Files:** store.py, settings.py, __main__.py, db/migrations/001_v01.sql, compose.yaml, .env.example, tests/test_settings.py, tests/integration/test_store.py, docs/run-local.md.
**Interfaces:**
- `WriterSession.open(dsn: str, source_id: str) -> WriterSession`: захват lock, новый epoch; session.epoch int; close освобождает соединение.
- `WriterSession.apply_batch(candidates: Sequence[NormalizedPosition], *, epoch: int, state: SourceStateUpdate, now: datetime) -> BatchStats`.
- `WriterSession.prune(*, now: datetime, max_rows: int = 1000) -> int`.
- `migrate(dsn: str) -> None`; повторный запуск по журналу no-op, checksum mismatch — ошибка.
- SourceStateUpdate: sync_state, heartbeat_at, last_snapshot_at, last_mqtt_at, error_code. Все даты UTC, последние два timestamps nullable. BatchStats: inserted, updated, ignored, conflicted; счётчики означают действия над итоговыми ключами, не raw messages.

- [ ] Выбрать совместимый образ PostgreSQL/PostGIS и закрепить version/digest после проверки официального источника. Порт БД публиковать только на 127.0.0.1; именованный volume не в Git. Пароли из локального .env, не реальные credentials в compose.
- [ ] Создать тестовую отдельную БД. Integration suite отказывается запускать destructive reset, если имя не оканчивается на `_test`; production/local working БД не очищать.
- [ ] Написать тесты PK/FK, CHECK SRID/range/NaN, migration rerun/checksum, epoch, второй writer, connection loss, full rollback при ошибке пачки, перестановки как в задаче2.
- [ ] Реализовать writer без ORM; один connection/lock; API роль без INSERT/UPDATE/DELETE. Seed source fintraffic с проверенной атрибуцией.
- [ ] Проверить TTL ровно24h и +1ms, не реанимировать expired кандидата; EXPLAIN на5000 синтетических ключах, без требования всегда выбирать GiST.
- [ ] `SFD_TEST_DATABASE_URL=... .venv/bin/python -m pytest tests/integration/test_store.py -q` с локальным секретом из окружения. Все PASS; отсутствующая БД = «не проверено», а не PASS через skip.
- [ ] Добавить команды `.venv/bin/python -m shadow_fleet migrate` и инструкцию восстановления только текущего состояния, без обещаний истории.

## Задача 4. Ограниченный транспорт и lifecycle collector

**Depends:** 3. **Files:** transport.py, collector.py, settings.py, __main__.py, tests/test_transport.py, tests/test_collector.py; bounded synthetic fixtures.
**Interfaces:**
- `fetch_snapshot(settings: Settings) -> SnapshotEnvelope`: bounded decompression, FeatureCollection плюс received_at.
- `IncomingEnvelope(epoch: int, sequence: int, topic: str, payload: bytes, received_at: datetime, retained: bool)`.
- `Collector(settings: Settings, store: WriterSession, transport: Transport, clock: Clock)`; `run(stop_event) -> None`.
- Transport предоставляет connect/subscribe/fetch_snapshot/close и события callback; Clock предоставляет utc_now/monotonic. В тестах fake реализации без сети.
- Collector вызывает normalize_* и apply_batch; callback никогда не выполняет SQL.

- [ ] Написать fake-сценарий subscribe → SUBACK → MQTT A → REST B → watermark → MQTT C → commit prefix → batch C. Проверить ни пропуска C, ни ожидания пустой очереди.
- [ ] Проверить лимиты gzip/network/body/message/queue/depth/features, обрыв gzip, malformed JSON, empty snapshot, all-invalid/all-expired snapshot, HTTP429 с Retry-After в секундах и HTTP-date; invalid header использует обычный backoff.
- [ ] Проверить retained-only, duplicate-live, no-push60s, heartbeat15s, reconnect, late callback, DB timeout, failed commit, overflow. После failed epoch очередь целиком сбрасывается; проекция остаётся последней committed.
- [ ] Реализовать lifecycle; обновление heartbeat не зависит от наличия новых позиций; backoff использует monotonic, sleep прерывается stop_event.
- [ ] Graceful stop: прекратить приём, закрыть transport, завершить/откатить активную транзакцию в пределах её timeout, закрыть writer; не оставлять статус live намеренно. После kill health устаревает по heartbeat.
- [ ] Синтетический прогон100msg/s60s: измерить peak queue, RSS, failures, applied keys. Тест clock/fakes не требует реального ожидания60s; отдельный benchmark измеряет реальные ресурсы.
- [ ] `.venv/bin/python -m pytest tests/test_transport.py tests/test_collector.py -q`; регрессии задач1–3. Добавить CLI collect. Никакой бесконечной live-пробы по умолчанию.

## Задача 5. Read API

**Depends:** 3; финальная health-проверка после4. **Files:** api.py, tests/integration/test_api.py, docs/api/v1.md, __main__.py.
**Interfaces:** `create_app(settings: Settings) -> FastAPI`; два GET маршрута из контракта. `read_positions(bbox: BBox, *, as_of: datetime, limit: int = 2000) -> PositionPage` и `read_position(source_id: str, mmsi: str, *, as_of: datetime) -> PositionDetail | None` в store read-only части; API контролирует единый snapshot для каждого ответа.

- [ ] Добавить integration tests normal/empty/bad bbox/NaN/Inf/unknown MMSI/DB offline, ±180/fullworld/zero width, TTL/future clock skew, 2001+rows/truncated, устойчивую сортировку, consistent snapshot при concurrent writer.
- [ ] Проверить исходный отсутствующий source_state: вернуть starting и null времена с200 для seeded source; не отвечать500 из-за пустой таблицы.
- [ ] Реализовать ошибки400/404/503, no-store, единый as_of, source attribution, computed health; schema JSON точно соответствует системному дизайну. Не отдавать fingerprint/DSN/raw payload наружу.
- [ ] API-role реально не может писать; query параметризованы; DB outage возвращает503 в ограниченный срок (предложение connection timeout3s, query5s).
- [ ] `.venv/bin/python -m pytest tests/integration/test_api.py -q`. Опубликовать OpenAPI в локальном приложении, зафиксировать контракт docs/api/v1.md.
- [ ] Benchmark100 прогретых запросов/5000synthetic positions/1client, p95≤300ms как цель. Сохранить команду, машину, размеры ответов; при провале показать результат и причину, не ослаблять цель молча.

## Задача 6. Минимальный браузерный клиент

**Depends:** 5. **Files:** web/*, docs/run-local.md, THIRD_PARTY_NOTICES.md.
**Interfaces:** `fetchPositions(bbox: BBox, signal: AbortSignal): Promise<PositionPage>`; `fetchPosition(source: string, mmsi: string, signal: AbortSignal): Promise<PositionDetail>` в api.ts. `renderPositions(page: PositionPage): void` в map.ts. `renderDetails(detail: PositionDetail): void` в details.ts. main.ts владеет lifecycle, request_id, polling и cleanup.

- [ ] Vite+TS strict; закрепить совместимый Node LTS и точные npm зависимости/lock. npm scripts: dev, build, typecheck, test:e2e. Никаких React/state-store/UI-kit без новой причины.
- [ ] Синтетические Playwright routes: success,empty,slow older response,503,truncated,clock_skew,stale,live→degraded→live,details404. Тесты не обращаются к Fintraffic.
- [ ] Создать один экран: viewport, источник/состояние, счётчик/ограничение, доступный выбор, карточка. GeoJSON layer и нейтральная подложка из контракта. Обновлять source, не пересоздавать map каждые5s.
- [ ] Проверить AbortController + request_id, polling один in-flight, завершение cleanup при закрытии, отсутствие дублированных listeners. Статус сети отделён от stale отдельных точек.
- [ ] Проверить клавиатуру, пустые/ошибочные состояния и viewport360px/1440px; сохранить screenshots только с synthetic data. Дизайн спокойный и минимальный, без выдуманного «финального бренда».
- [ ] В web выполнить `npm run typecheck`, `npm run build`, `npm run test:e2e`. Все PASS; успешная сборка не заменяет browser tests.

## Задача 7. Сквозная приёмка и документация

**Depends:** 1–6. **Files:** docs/run-local.md, docs/development/acceptance.md, THIRD_PARTY_NOTICES.md, README.md; только необходимые исправления приложения.

- [ ] Запустить с чистого отдельного тестового окружения по инструкции; записать OS/runtime/версии и команды. Инициализация не должна зависеть от личных путей /Users/bek.
- [ ] Синтетический сценарий: snapshot → push → duplicate → conflict → disconnect → DB failure → restart → expired removal → stale UI recovery. Подтвердить R01–R08.
- [ ] Проверить offline unit tests, реальную PostgreSQL integration suite, browser tests, lint/typecheck/build. Таблица результатов не смешивает PASS/BLOCKED/NOT RUN.
- [ ] Проверить секреты, сырые данные, .env/volumes в ignore, лицензии/notice конкретных зависимостей, собственный LICENSE остаётся undecided. Не публиковать synthetic screenshots как live data.
- [ ] При отдельном разрешении на реальную пробу: один collector максимум120s, один bootstrap REST плюс reconnect только при сбое, максимум3attempts; сохранить только aggregate counters/тайминги. Пробу явно отделить от тестов и от SLA. При429 выполнять Retry-After, по deadline завершить, не форсировать запрос.
- [ ] Итоговый отчёт: что работает локально, что проверено фактически, known limitations, инструкции остановки/удаления только тестового окружения. Признать v0.1 локальным срезом, не завершённым Shadow Fleet Detector.

## Связь требований с задачами

| Требование | Задачи | Свидетельство |
|---|---|---|
| R01 карта/bbox | 5,6 | API boundary cases + browser map |
| R02 карточка/время/источник | 1,5,6 | canonical fixtures + JSON + selected detail |
| R03 snapshot/stream | 2,3,4 | permutation, atomicity, watermark |
| R04 health/freshness | 4,5,6 | fake clock + stale/degraded browser |
| R05 attribution | 3,5,6,7 | seed, JSON, видимый credit, notices |
| R06 normalizer/sentinel | 1,2 | table-driven fixtures |
| R07 recovery | 3,4,7 | failed writer/rollback/restart |
| R08 отсутствие ложных меток | 5,6,7 | review schema, текста UI и README |

## Что проверять более сильной моделью

Рекомендуемые точки независимого ревью: после merge/БД (задача3), после collector (4), перед признанием всего среза рабочим (7). Передавать diff, контракты и реальные test logs. Это рекомендация для контроля качества, не обещание безошибочности и не требование покупать определённую модель. Исправления делать в рамках той же задачи, не переходить дальше с критической ошибкой.
