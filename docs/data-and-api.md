# Данные и API: исследовательский реестр

Обновлено 2026-11-14. [План исследования](research/source-foundation-plan.md) определяет критерии готовности источников. Успешный запрос относится к конкретному интерфейсу и времени, без обещания SLA или глобальной полноты.

| Источник | Роль | Что подтверждено пробой | Права и ограничения | Следующая проверка |
|---|---|---|---|---|
| Digitraffic / Fintraffic | Региональные текущие позиции и метаданные | REST без ключа, gzip; MQTT подтверждён в двух 30-секундных окнах через /location | [CC BY 4.0 и атрибуция](https://www.digitraffic.fi/en/terms-of-service/); покрытие выборочное | Проверить reconnect/SLA на нескольких временных окнах; сравнить с другими регионами |
| Kystdatahuset / Kystverket | Региональные текущие и исторические позиции | HTTP GeoJSON 200, измерена свежесть; три коротких исторических окна, производные точки | [NLOD и ограничения интерфейса](https://kystdatahuset.kystverket.no/ws/swagger/index.html); разные правила покрытия и выборки для API и HAIS | Повторить профиль вне вечернего окна; сверить ограничения интерфейсов и правила объединения |
| Kystverket TCP | Поток NMEA/IEC | Ранее тайм-аут из этой среды; HTTP результат не меняет статус TCP | [Открытая часть под NLOD с ограничениями по судам](https://www.kystverket.no/en/sea-transport-and-ports/ais/access-to-ais-data/) | Повторить из другого сетевого маршрута |
| AISstream | Потенциальный поток текущих позиций и статических AIS | Прочитана [документация](https://www.aisstream.io/documentation/); WebSocket с ключом не проверен | Без SLA и durable replay; хранение и публичная трансляция не подтверждены | Проверить права и доступ; сравнить несколько ограниченных регионов |
| NOAA Marine Cadastre | История США | CSV.zst Range 206; подтверждены 17 полей и 1 239 строк из префикса | [Условия конкретного экспорта](https://www.fisheries.noaa.gov/inport/item/73064); не предполагаем CC0 | Подтвердить семантику времени и репрезентативный срез |
| Danish DMA | История | Официальная страница доступна; архивный хост не ответил из этой среды | [Политика](https://www.dma.dk/safety-at-sea/navigational-information/ais-data/ais-data-management-policy); права на перепубликацию bulk требуют проверки | Проверить точный файл и условия с другого маршрута |
| Global Fishing Watch | Производные события и vessel identity | 401 без токена; реальный набор событий не получен | [Условия API](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits); отдельно проверять dataset | Один запрос с токеном и limit=1 |
| OpenSanctions | Внешние сведения и сопоставление судов | Каталог 200; версионированный CSV с 59 Vessel, только проверка формата | [Условия некоммерческого использования](https://www.opensanctions.org/docs/commercial/exemption/); первичный список в примере исторический | Разобрать FTM и проверить связь с датированным первичным источником |

Артефакты: [первая волна](research/api-probes.md), [профиль текущих AIS](research/ais-source-profile.md), [архивы и evidence](research/archive-and-evidence.md). Контракты будущего API остаются черновиками.

Следующая волна: [сопоставление REST/MQTT и Kystverket](research/ais-transport-comparison.md), [матрица готовности](research/development-readiness.md).
