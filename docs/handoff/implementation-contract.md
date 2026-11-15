# Контракт реализации первого среза

**Draft, 2026-11-14.** Числа и правила ниже — конкретизация для будущего исполнителя, не выполненная реализация. При противоречии с новыми указаниями владельца остановить только затронутую задачу и записать расхождение.

## 1. Границы продукта

Название Shadow Fleet Detector. Цель проекта — глобальная карта морских наблюдений и объяснимые материалы для исследования теневого флота. v0.1 проверяет инфраструктуру одного источника, а не решает всю цель.

Первый срез: локальная карта Финского залива, все доступные позиции Fintraffic без фильтра по типу, карточка наблюдаемого MMSI, время записи, возраст, источник, свежесть и здоровье доставки. MMSI — ключ наблюдаемого сигнала, не гарантированная личность судна. AIS-аномалия не является доказательством нарушения.

Не включать: регистрацию, платежи, SaaS, глобальную агрегацию, историю, треки, IMO resolution, санкционный scoring, ML/LLM, спутниковые снимки, Kafka, Redis, Kubernetes, production deployment. Не копировать исследовательские скрипты целиком в production-модули.

## 2. Канонические типы

Будущий `model.py` определяет immutable dataclass `NormalizedPosition`:

| Поле | Python-тип | Правило |
|---|---|---|
| source_id | str | fintraffic |
| mmsi | str | 9 ASCII-цифр; числовое целое входное значение преобразовать через zfill(9), отрицательные/длиннее 9/boolean отклонить; строка должна уже иметь 9 цифр |
| lon, lat | float | конечные; вход lon [-180,180], lat [-90,90]; +180 → -180; -0.0 → +0.0 |
| provider_time | datetime | timezone-aware UTC |
| provider_bucket | int | floor Unix seconds, не округление |
| time_precision | Literal[second,millisecond] | MQTT second, REST millisecond |
| received_at | datetime | UTC, передаётся адаптером на вход; не читать часы внутри normalizer |
| transport | Literal[rest,mqtt] | канал доставки |
| sog_kn, cog_deg, heading_deg | float или None | правила ниже |
| fingerprint | bytes | SHA-256, ровно 32 байта |
| clock_skew | bool | provider_time > received_at |

`ProjectedPosition` содержит `position: NormalizedPosition` и `time_conflict: bool`. Epoch — свойство сеанса/пачки, не доказательство времени судна.

`Reject` содержит `code: RejectCode` без исходного payload. `NormalizeResult = NormalizedPosition | Reject`. Перечень причин: invalid_shape, invalid_id, id_mismatch, invalid_coordinate, invalid_time, future_time, expired. Неизвестные причины не подменять пустой успешной записью.

Необязательные повреждённые speed/angles превращаются в None, не уничтожают валидную позицию. Числа boolean не являются числами для этого контракта. NaN/Infinity недопустимы.

## 3. Источник и нормализация

REST: `https://meri.digitraffic.fi/api/ais/v1/locations`, GeoJSON FeatureCollection; заголовки Accept-Encoding: gzip и идентификатор приложения Digitraffic-User. MQTT: TLS WebSockets, host meri.digitraffic.fi, port 443, path /mqtt, topic `vessels-v2/+/location`. На официальной странице встречаются location/locations; рабочая проба подтвердила singular location. Не менять топик без проверки.

Перед реализацией adapter сверить точные поля с [официальным OpenAPI](https://meri.digitraffic.fi/swagger/openapi.json), [описанием MQTT](https://www.digitraffic.fi/en/marine-traffic/) и существующими пробами. Сохранить компактную таблицу отображения полей в будущем `docs/api/fintraffic-mapping.md`, не копию всего удалённого документа. Несовпадение формы — блокер адаптера, а не повод выдумывать поля. До этого чистые canonical tests работают без сети.

Предполагаемое отображение, подлежащее сверке: REST geometry.coordinates = [lon,lat], properties.mmsi и feature.id при наличии, properties.timestampExternal — Unix milliseconds; MQTT MMSI из topic, lon/lat/time — Unix seconds. Если payload тоже содержит MMSI, он должен совпасть с topic. REST `timestamp` не заменяет timestampExternal: это AIS-секунда, а не полная дата.

Скорость sog=102.3, COG=360, heading=511 — отсутствующее значение. Скорость допустима 0 ≤ sog <102.3; COG 0 ≤ cog <360; heading — целое 0..359. Вне диапазона, не число или отсутствует → None. Значения 0 сохранять; не применять `value or None`. Единицы: узлы и градусы, без неявной конвертации.

Время: целое Unix seconds для MQTT, целое Unix milliseconds для REST; неполная дата/float/boolean отклоняются. При provider_time − received_at >60 s Reject(future_time); (0,60] принять с clock_skew. received_at − provider_time >24 h → Reject(expired), ровно 24 h включено. Перед записью TTL проверить ещё раз относительно текущего времени пачки. Вход received_at без timezone — ошибка вызывающего кода, не угадывать часовой пояс.

Канонический fingerprint: JSON-массив `[lon,lat,sog_kn,cog_deg,heading_deg]`, каждое ненулевое числовое значение float, нули +0.0, отсутствующие None; `json.dumps(..., separators=(',', ':'), allow_nan=False).encode('utf-8')`; SHA-256 этих байтов. MMSI/source/time/transport/received_at в hash не входят: они участвуют в ключе/версии отдельно. Фикстура для неподвижной точки: байты `[25.0,60.0,0.0,null,null]`. Не заменять это округлением координат.

## 4. Merge — чистая функция до SQL

`merge_position(current: ProjectedPosition | None, incoming: NormalizedPosition) -> ProjectedPosition`.

1. При отсутствии current создать строку, conflict=false.
2. Другой source_id/mmsi — ошибка вызывающего кода: нельзя сливать разные ключи.
3. Новый bucket больше — заменить полностью, conflict=false. Меньше — оставить current.
4. Равный bucket: conflict = прежний conflict OR различие fingerprint.
5. Выбрать максимум ключа `(transport_rank, rest_millis_or_zero, fingerprint)`: mqtt rank=1, rest rank=0; второй элемент у REST — точное целое Unix milliseconds, у MQTT=0; hash сравнивается как bytes.
6. При равном ключе взять минимальный received_at, пересчитать clock_skew. Поля transport/time_precision/provider_time принадлежат выбранному кандидату, не смешиваются из разных записей.

Проверять перестановки пачек и повторную доставку. Это воспроизводимая политика, не установление физического порядка движения внутри секунды.

## 5. БД и единый writer

Модель таблиц и индексов: [database-design](../architecture/database-design.md). Только source, source_state, latest_position плюс технический журнал schema_migrations(version, applied_at, checksum). Журнал не является таблицей истории AIS.

Писатель получает session advisory lock на выделенном соединении и через него выполняет все записи. Второй collector завершается понятной ошибкой writer_already_running; не ждёт бесконечно. Потеря соединения немедленно закрывает epoch и отменяет callbacks. Новый epoch увеличивается атомарно в source_state. Проверка epoch и запись позиции/state — одна транзакция. API не получает write-права.

Для v0.1 допустим простой batch: агрегировать по ключу чистой merge-функцией, загрузить текущие строки одной выборкой, вычислить merge и записать результаты в одной транзакции при удерживаемом writer lock. Не дублировать разные алгоритмы merge в Python и SQL. Если лимиты производительности не выполняются, оптимизировать после измерения с сохранением этих контрактов.

## 6. Сборщик и ограничения

Порядок: lock → новый epoch → connect → subscribe → SUBACK → REST snapshot → watermark очереди → atomic merge snapshot + prefix → live при валидном non-retained push → обычные batches. Callback только проверяет размер и кладёт envelope в bounded queue; не пишет БД. На входе фиксируются UTC received_at и порядковый номер.

| Параметр | Draft-значение |
|---|---|
| Коннект / SUBACK | по 10 s |
| REST целиком | 15 s |
| Сетевое и распакованное тело REST | каждое ≤8 MiB; читать ограниченно, не сначала целиком |
| MQTT payload | ≤64 KiB |
| Очередь + неподтверждённая пачка | ≤10 000 сообщений и ≤8 MiB payload |
| Batch | ≤250 сообщений или 500 ms |
| DB statement / bootstrap transaction | 5 s / 15 s |
| Heartbeat | каждые 5 s между транзакциями |
| Heartbeat stale / push stale | >15 s / >60 s |
| Reconnect | exponential backoff с jitter 2–60 s; Retry-After — нижняя граница |
| JSON parser | максимальная глубина 16, до 20 000 REST features; дополнительные неизвестные поля игнорировать после лимитов |
| TTL | 24 h по provider_time; очистка каждые 15 min, ≤1000 строк за batch, ≤2 s цикл |

Лимиты глубины/числа объектов проверяются без предположения, что они ограничивают RSS. Защитить декодер от рекурсивных ошибок; ошибки parsing не должны убивать процесс молча.

Некорректный top-level REST/обрыв gzip → весь snapshot не принят, rollback, retry. Валидная коллекция с отдельными невалидными features → счётчики отказов, принятие остальных. Непустая коллекция с нулём валидных кандидатов по причинам schema/id/coordinate/time → snapshot_invalid; все записи просто expired — допустимый нулевой набор. Пустая валидная коллекция не очищает БД.

Retained записи можно merge, но они не подтверждают live. Свежий non-retained валидный дубль подтверждает доставку. Историческая отметка другого epoch не даёт live. После сверки без push оставаться syncing, через 60 s от SUBACK — degraded/reconnect. На overflow закрыть весь epoch, не продолжать с дырявой очередью под видом live. При недоступной БД API отдаёт 503; при недоступном источнике и доступной БД — 200 с degraded и сохранёнными данными.

## 7. API и карта

Полные поля ответа и пример: [system-design](../architecture/system-design.md). `GET /v1/positions` требует четыре bbox параметра; диапазоны и шов ±180 — по системному дизайну. Лимит 2000, сортировка provider_bucket DESC/source_id ASC/mmsi ASC, выбрать 2001 для truncated. Детали `GET /v1/positions/{source}/{mmsi}`: неизвестный source или отсутствующая/expired позиция →404; синтаксически невалидный MMSI →400. Ошибка ответа единообразна: `{"error":{"code":"invalid_bbox","message":"..."}}`; другие codes invalid_mmsi, not_found, database_unavailable. Не возвращать SQL, DSN, traceback.

Один read-only repeatable-read snapshot, as_of берётся один раз. На ответах Cache-Control: no-store. Для production режимов нет скрытых обещаний. FastAPI default 422 преобразовать в 400 только для неверных параметров этих маршрутов. API bind 127.0.0.1:8000. Vite bind 127.0.0.1:5173; dev proxy `/v1` → локальный API, без wildcard CORS. Порты должны быть настраиваемыми.

Карта: MapLibre GeoJSON source и circle layer, без тысяч DOM markers. Старт центр lon=25,lat=60,zoom=6 как draft. Нейтральный background style без сторонних тайлов/шрифтов; пустая подложка честно называется технической сеткой/областью, не географической картой с берегами. Берега добавить лишь после выбора лицензированного набора.

Polling каждые 5 s после завершения прошлого запроса, один активный запрос. Смена viewport по moveend: AbortController + монотонный request_id, старый ответ игнорируется даже если отмена не успела. Ошибка не очищает последнее успешное изображение: показать disconnected, время ответа, возраст данных. Fresh ≤300 s, stale >300 s. Возраст в браузере можно увеличивать по монотонно прошедшему времени от as_of, но после ошибки обязательно помечать весь ответ устаревшим. Truncated показывать текстом «Показаны первые 2 000 наблюдений; приблизьте карту».

Карточка не выдумывает vessel name/flag/type. Показывает MMSI, координаты, provider_time, возраст, Fintraffic, transport, clock_skew/time_conflict при наличии. Клавиатурный список наблюдений или доступный выбор нужен для открытия карточки без мыши. Цвет не единственный носитель stale/degraded.

## 8. Лицензирование и публикация

У проекта нет выбранной собственной лицензии и файла LICENSE. Не добавлять MIT/Apache/GPL по умолчанию, не объявлять проект лицензированным open source, не менять копирайт владельца. До релиза владелец выбирает лицензию кода и документации отдельно. Локальная разработка не требует выдуманного решения за него.

Проверено 2026-11-14: [официальные условия Fintraffic](https://www.digitraffic.fi/en/terms-of-service/) указывают CC BY 4.0, атрибуцию и обозначение изменений. Для нашего отображения предложено: источник Fintraffic / Digitraffic со ссылкой, ссылка на CC BY 4.0, пояснение «Данные нормализованы и отфильтрованы; отображается последняя доступная позиция». Сохранять применимые уведомления исходного материала. Это лицензия данных, не собственного кода.

Будущий `THIRD_PARTY_NOTICES.md`: компонент, точная версия, назначение, SPDX из проверенного LICENSE пакета, URL первоисточника, необходимые notices, дата проверки. Включить прямые и распространяемые транзитивные зависимости, БД/контейнерные образы при распространении, шрифты, тайлы, датасеты. Нельзя выводить лицензию библиотеки из лицензии GitHub-аналога. Автоматический отчёт дополняется проверкой unknown/custom/dual license. Сам факт permissive-лицензии не освобождает от notices.

Сырые датасеты, live payload, токены, DSN с паролями, .env, дампы БД, volume и браузерные traces с реальными данными вне Git. В Git — синтетические fixtures и агрегированные отчёты. .env.example содержит только placeholders. Никаких внешних сервисов, аналитики и платных API автоматически.
