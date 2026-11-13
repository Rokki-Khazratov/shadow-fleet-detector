# Database design — концептуальный draft

Предлагается PostgreSQL/PostGIS после подтверждения объёма. Таблицы ниже — логическая модель; физическая схема, типы и индексы уточняются по пробам и лицензиям.

| Сущность | Ключ | Важные поля | Правило |
|---|---|---|---|
| source | source_id | owner, URL, license_url, checked_at, redistribution_policy, coverage_claim | Версионировать условия |
| ingest_batch | batch_id | source_id, fetched_at, status, error, schema_version, payload_hash | Повторяемая диагностика |
| raw_message_ref | message_id | batch_id, external_id, hash, storage_ref, retention_until | Хранить тело лишь если разрешено |
| position_observation | observation_id | source_id, mmsi, observed_at, received_at, lon, lat, sog, cog, heading, quality_flags, source_message_id | Один факт наблюдения с provenance |
| vessel_identity | identity_id | imo, names, vessel_type, confidence, valid_from/to | Временная сущность, не MMSI |
| identity_link | link_id | identity_id, identifier_type/value, valid_from/to, source_id, evidence_ref, confidence | Конфликты допустимы |
| latest_position | source_id + mmsi | observation_id, observed_at, updated_at, freshness_state | Проекция, не первичная история |
| anomaly_event | event_id | kind, vessel_ref, start/end, detector_version, parameters, explanation, status | Версионированный расчёт |
| event_observation | event_id + observation_id | role | Проверяемая связь с точками |
| external_claim | claim_id | subject, predicate, object, source_url, published_at, observed_at, retrieved_at, quote_ref, status | Факт о том, что источник утверждал, не истина автоматически |
| claim_identity_link | claim_id + identity_id | basis, confidence, reviewed_at | Отдельная проверка совпадения |
| coverage_snapshot | source_id + captured_at + area_id | last_message_at, expected_scope, observed_count, health | Показывать пределы покрытия |

Уникальность позиции: source_id + source_message_id, если поставщик даёт ID; иначе устойчивый хеш нормализованных source_id, MMSI, observed_at, координат и типа сообщения с сохранением исходного payload hash. Это предложение, требует теста коллизий и повторов. Внешний claim не изменяет поле identity напрямую. История append-only; исправления через новую версию и supersedes_id. На карте индекс geometry + observed_at, в истории индекс (mmsi, observed_at DESC); частичное индексирование/партиции только после замеров.

Неизвестный IMO, например 0 в Digitraffic, переводится в NULL с quality flag; исходное значение остаётся в provenance, если разрешено. Координаты проверяются в диапазонах, [lon,lat] GeoJSON не переставляются. Нужны тестовые случаи для анти-меридиана, late arrival, MMSI reuse, конфликтов имён, отсутствия timestamp и источников с запретом хранения.
