import {demoMode} from './api';

const icon = (path: string, size = 18) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
export const icons = {
  brand: icon('<path d="M12 2.5 21.5 12 12 21.5 2.5 12Z"/><path d="m5 12 7 2 7-2M12 7v7"/>',24),
  light: icon('<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M19 5l-1.5 1.5m-11 11L5 19"/>'),
  dark: icon('<path d="M20.6 14.2A8.5 8.5 0 0 1 9.8 3.4 8.6 8.6 0 1 0 20.6 14.2Z"/>'),
  search: icon('<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4"/>'),
  reset: icon('<circle cx="12" cy="12" r="6.5"/><path d="M12 2v5m0 10v5M2 12h5m10 0h5"/>',16),
  ship: icon('<path d="m12 3 6 16-6-3-6 3Z"/>',18),
  observation: icon('<circle cx="12" cy="12" r="4"/>',18),
  next: icon('<path d="m9 6 6 6-6 6"/>',14),
  close: icon('<path d="m6 6 12 12M18 6 6 18"/>',16),
  empty: icon('<path d="M3.5 8V3.5H8m8 0h4.5V8m0 8v4.5H16m-8 0H3.5V16"/><circle cx="12" cy="12" r="3"/>',24),
};

export function mountWorkspace(el: HTMLElement) {
  el.innerHTML = `
    <a class="skip" href="#observations">К наблюдениям</a>
    <header class="topbar">
      <div class="brand"><span class="brand-symbol">${icons.brand}</span><span>Shadow Fleet Detector</span></div>
      <div class="header-actions">
        <a class="mode-link" href="${demoMode ? './' : '?demo=1'}">${demoMode ? 'К рабочей карте' : 'Демо'}</a>
        <button class="icon-button" id="theme" type="button" aria-label="Светлая тема" title="Светлая тема">${icons.light}</button>
      </div>
    </header>
    <main class="workspace">
      <section class="chart" aria-label="Морская карта">
        <div id="map"></div>
        <header class="chart-header">
          <div><h1>Морская карта</h1><p>${demoMode ? 'Демонстрационный режим' : 'Позиции AIS · Fintraffic'}</p></div>
          <button class="quiet-button reset-view" id="reset-view" type="button">${icons.reset}<span>Финский залив</span></button>
        </header>
        <div class="chart-key" aria-label="Обозначения карты">
          <span><i class="key-dot current"></i>Свежая точка</span><span><i class="key-dot old"></i>Устарела</span>
          <span id="history-legend" hidden><i class="key-dot historical"></i>Точки истории выбранного сигнала</span>
        </div>
        <footer class="chart-footer">
          <span id="map-centre" class="data">60.0000° N · 25.0000° E</span>
          <a href="https://www.naturalearthdata.com/about/terms-of-use/">Берега: Natural Earth</a>
        </footer>
      </section>
      <aside id="observations" class="inspector" aria-labelledby="observations-title" tabindex="-1">
        <div class="inspector-head">
          <div class="pane-title"><h2 id="observations-title">Наблюдения</h2><span class="count data" id="count" aria-label="Число наблюдений">—</span></div>
          <div class="status-block"><span id="network" class="status" role="status" data-tone="muted">Подключение…</span><p id="source" class="source-line">Ожидание данных</p></div>
          <label class="search" for="mmsi-search">${icons.search}<input type="search" inputmode="numeric" autocomplete="off" maxlength="9" id="mmsi-search" aria-label="Поиск по MMSI" placeholder="Поиск по MMSI"></label>
          <p id="truncated" class="warning" hidden>Показаны первые 2 000 наблюдений; приблизьте карту.</p>
        </div>
        <div class="list-section">
          <div class="list-heading" aria-hidden="true"><span>Сигнал MMSI</span><span>Получен</span></div>
          <div id="list" aria-label="Список наблюдений" aria-busy="true"></div>
        </div>
        <section id="detail" class="detail" aria-label="Карточка сигнала" aria-live="polite"></section>
        <footer class="inspector-footer">
          ${demoMode ? '<span>Синтетический набор · не реальные позиции</span>' : '<a href="https://www.digitraffic.fi/en/marine-traffic/">Fintraffic / Digitraffic</a><span aria-hidden="true"> · </span><a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a><p>Данные нормализованы и отфильтрованы.</p>'}
          <p>MMSI — идентификатор сигнала. Аномалия не доказывает нарушение.</p>
        </footer>
      </aside>
    </main>`;
}

export function element<K extends keyof HTMLElementTagNameMap>(tag: K, text: string, className?: string) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}

export function emptyState(title: string, copy: string) {
  const box = element('div', '', 'empty-state');
  const symbol = element('span', '', 'empty-symbol');
  symbol.innerHTML = icons.empty;
  box.append(symbol, element('p', title, 'empty-title'), element('p', copy));
  return box;
}
