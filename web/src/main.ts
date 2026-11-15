import {setWorkerUrl} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles.css';
import {demoMode, request} from './api';
import {createChart, type Theme} from './chart';
import {dossierPanel} from './dossier';
import {historyPanel} from './history';
import {historyLayer} from './history-layer';
import type {Detail, Page, Position} from './types';
import {element, emptyState, icons, mountWorkspace} from './workspace';

const initialTheme = (): Theme => {
  try { return localStorage.getItem('sfd-theme') === 'light' ? 'light' : 'dark'; }
  catch { return 'dark'; }
};
let theme = initialTheme();
document.documentElement.dataset.theme = theme;
setWorkerUrl(workerUrl);
mountWorkspace(document.querySelector<HTMLDivElement>('#app')!);
const el = (id: string) => document.getElementById(id)!;
const search = document.querySelector<HTMLInputElement>('#mmsi-search')!;
const network = el('network');
const list = el('list');
const box = el('detail');
const themeButton = el('theme');
const chart = createChart(theme);
const {map} = chart;
const number = new Intl.NumberFormat('ru-RU');
const clock = new Intl.DateTimeFormat('ru-RU', {timeZone:'UTC', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'});
const sourceNames = {starting:'ожидает запуска', syncing:'сверяет снимок', live:'поток активен', degraded:'поток недоступен'};
const key = (p: Position) => `${p.source_id}/${p.mmsi}`;
const ageLabel = (seconds: number) => seconds < 60 ? `${Math.floor(seconds)} с`
  : seconds < 3600 ? `${Math.floor(seconds / 60)} мин` : `${Math.floor(seconds / 3600)} ч`;
let last: Page | undefined;
let lastReceivedAt = 0;
let disconnected = false;
let selectedKey: string | undefined;
let selectedPoint: Position | undefined;
let listRequest: AbortController | undefined;
let detailRequest: AbortController | undefined;
let selection: AbortController | undefined;
let detailState: {data: Detail; receivedAt: number} | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
let ready = false;
let drawHistory: ReturnType<typeof historyLayer> = () => {};

function showConnection(message: string, tone: string) {
  network.textContent = message;
  network.dataset.tone = tone;
}
function resetDetail() {
  box.replaceChildren(element('h2','Карточка сигнала'),
    element('p','Выберите точку на карте или MMSI в списке. Здесь появятся время наблюдения, координаты и история.','placeholder-copy'));
}
function syncTheme() {
  document.documentElement.dataset.theme = theme;
  const label = theme === 'dark' ? 'Светлая тема' : 'Тёмная тема';
  themeButton.setAttribute('aria-label',label);
  themeButton.title = label;
  themeButton.innerHTML = theme === 'dark' ? icons.light : icons.dark;
  chart.applyTheme(theme);
}
syncTheme();
themeButton.addEventListener('click', () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('sfd-theme', theme); } catch { /* Preference is optional. */ }
  syncTheme();
});
el('reset-view').addEventListener('click', () => map.easeTo({center:[25,60], zoom:6}));

function centreReadout() {
  const c = map.getCenter().wrap();
  el('map-centre').textContent = `${Math.abs(c.lat).toFixed(4)}° ${c.lat < 0 ? 'S' : 'N'} · ${Math.abs(c.lng).toFixed(4)}° ${c.lng < 0 ? 'W' : 'E'}`;
}
function setSelectedButtons() {
  for (const row of list.querySelectorAll<HTMLButtonElement>('button[data-key]')) {
    row.setAttribute('aria-pressed',String(row.dataset.key === selectedKey));
  }
}
function closeDetail(restoreFocus: boolean) {
  const old = selectedKey;
  detailRequest?.abort();
  selection?.abort();
  detailState = undefined;
  selectedKey = undefined;
  selectedPoint = undefined;
  drawHistory([]);
  setSelectedButtons();
  chart.positions(filtered(), undefined);
  resetDetail();
  if (restoreFocus) {
    const row = Array.from(list.querySelectorAll<HTMLButtonElement>('button')).find(row => row.dataset.key === old);
    (row ?? search).focus({preventScroll:true});
  }
}

function cached(position: Position, asOf: string, receivedAt: number): Position {
  const elapsed = Math.max(0, performance.now() - receivedAt);
  const age = (Date.parse(asOf) + elapsed - Date.parse(position.provider_time)) / 1000;
  return {...position, stale:true, age_seconds:Math.max(position.age_seconds, age)};
}

function detailHead(label: string, titleClass?: string) {
  const head = element('div','','detail-head');
  const title = element('h2',label,titleClass);
  const close = element('button','','icon-button detail-close');
  close.type = 'button';
  close.innerHTML = icons.close;
  close.setAttribute('aria-label','Закрыть карточку');
  close.addEventListener('click', () => closeDetail(true));
  head.append(title, close);
  return head;
}

function unavailable(message: string) {
  box.replaceChildren(detailHead('Карточка недоступна'),element('p',message,'placeholder-copy'));
}

function renderDetail(offline: boolean) {
  if (!detailState || !selection) return;
  const {data, receivedAt} = detailState;
  const {as_of, source} = data;
  const p = offline ? cached(data.item, as_of, receivedAt) : data.item;
  let summary = box.querySelector<HTMLElement>('.detail-summary');
  if (!summary) {
    summary = element('div','','detail-summary');
    const signal = selection.signal;
    box.replaceChildren(detailHead(p.mmsi,'data'),summary,
      historyPanel(p.source_id,p.mmsi,() => detailState?.data.as_of ?? as_of,signal,drawHistory),
      dossierPanel(p.source_id,p.mmsi,() => detailState?.data.item.provider_time ?? p.provider_time,signal));
  }
  const meta = element('p',`${p.stale ? 'Устарела' : 'Свежая точка'} · ${ageLabel(p.age_seconds)} назад · ${p.transport.toUpperCase()}`,'detail-meta');
  const motion = (value:number|null, unit:string) => value === null ? 'нет данных' : `${value}${unit}`;
  const facts = element('dl','','facts');
  for (const [label,value] of [
    ['Координаты',`${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`],
    ['Время источника',p.provider_time], ['Получено',p.received_at], ['Источник',source.attribution],
    ['Скорость',motion(p.sog_kn,' уз.')], ['Курс',motion(p.cog_deg,'°')], ['Направление',motion(p.heading_deg,'°')],
  ]) {
    const row = element('div','','fact');
    row.append(element('dt',`${label}:`),' ',element('dd',value));
    facts.append(row);
  }
  summary.replaceChildren(meta,facts);
  if (offline) summary.append(element('p','Последняя сохранённая позиция','warning'));
  if (p.clock_skew) summary.append(element('p','Сдвиг времени источника','warning'));
  if (p.time_conflict) summary.append(element('p','Конфликт наблюдений за одну секунду','warning'));
}

async function refreshDetail(p: Position, reveal = false) {
  detailRequest?.abort();
  const ac = detailRequest = new AbortController();
  try {
    const response = await request(`/v1/positions/${encodeURIComponent(p.source_id)}/${encodeURIComponent(p.mmsi)}`,{signal:ac.signal});
    if (ac.signal.aborted) return;
    if (response.status === 404) {
      closeDetail(false);
      unavailable('Наблюдение больше недоступно.');
      return;
    }
    if (!response.ok) throw Error('position');
    const detail: Detail = await response.json();
    if (ac.signal.aborted) return;
    detailState = {data:detail, receivedAt:performance.now()};
    renderDetail(disconnected);
    if (reveal && window.matchMedia('(max-width: 760px)').matches) box.scrollIntoView({block:'nearest'});
  } catch {
    if (ac.signal.aborted) return;
    if (detailState) renderDetail(true);
    else unavailable('Не удалось загрузить наблюдение. Повторим запрос автоматически.');
  }
}

function select(p: Position) {
  selection?.abort();
  selection = new AbortController();
  detailState = undefined;
  drawHistory([]);
  selectedKey = key(p);
  selectedPoint = p;
  setSelectedButtons();
  const items = filtered();
  chart.positions(items,items.find(item => key(item) === selectedKey));
  box.replaceChildren(element('p','Загрузка карточки…','placeholder-copy'));
  void refreshDetail(p,true);
}

function filtered() {
  const query = search.value.trim();
  if (!last) return [];
  const {items, as_of} = last;
  const show = items.filter(row => row.mmsi.includes(query));
  return disconnected ? show.map(row => cached(row,as_of,lastReceivedAt)) : show;
}
function renderList() {
  const items = filtered();
  const active = document.activeElement;
  const focused = active instanceof HTMLButtonElement && list.contains(active) ? active.dataset.key : null;
  const fragment = document.createDocumentFragment();
  let restore: HTMLButtonElement | undefined;
  for (const p of items) {
    const row = element('button','','observation');
    row.type = 'button';
    row.dataset.key = key(p);
    row.dataset.freshness = p.stale ? 'old' : 'current';
    row.title = p.stale ? 'Устаревшее наблюдение' : 'Свежее наблюдение';
    row.setAttribute('aria-label', p.mmsi);
    row.setAttribute('aria-description',`${row.title} · ${ageLabel(p.age_seconds)} назад`);
    row.setAttribute('aria-pressed',String(key(p) === selectedKey));
    const symbol = element('span','','ship-symbol');
    const direction = p.heading_deg ?? p.cog_deg;
    symbol.innerHTML = direction === null ? icons.observation : icons.ship;
    if (direction !== null) symbol.style.setProperty('--heading',`${direction}deg`);
    const info = element('span','','observation-info');
    info.append(element('strong',p.mmsi,'data'), element('small',p.sog_kn === null ? 'Скорость неизвестна' : `${p.sog_kn} уз. · ${p.transport.toUpperCase()}`));
    const age = element('span','','observation-age');
    age.append(element('strong',ageLabel(p.age_seconds),'data'), element('small',p.stale ? 'Устарела' : 'Свежая'));
    row.append(symbol,info,age);
    row.addEventListener('click',() => void select(p));
    if (row.dataset.key === focused) restore = row;
    fragment.append(row);
  }
  if (!items.length) fragment.append(search.value.trim() && last?.items.length
    ? emptyState('Совпадений нет','Проверьте MMSI или очистите поиск.')
    : emptyState('Нет наблюдений в области','Сместите карту или измените масштаб. Это не означает отсутствие судов.'));
  list.replaceChildren(fragment);
  list.setAttribute('aria-busy','false');
  restore?.focus({preventScroll:true});
  el('count').textContent = number.format(items.length);
  const visibleSelection = items.find(p => key(p) === selectedKey);
  selectedPoint = visibleSelection ?? selectedPoint;
  chart.positions(items, visibleSelection);
}

function bounds() {
  const b = map.getBounds(), w = b.getWest(), e = b.getEast();
  const norm = (x: number) => ((x + 180) % 360 + 360) % 360 - 180;
  return new URLSearchParams({west:String(e-w >= 360 ? -180 : norm(w)),east:String(e-w >= 360 ? 180 : norm(e)),
    south:String(Math.max(-90,b.getSouth())),north:String(Math.min(90,b.getNorth()))});
}
async function refresh() {
  if (!ready) return;
  listRequest?.abort();
  if (timer) clearTimeout(timer);
  const ac = listRequest = new AbortController();
  try {
    const response = await request(`/v1/positions?${bounds()}`,{signal:ac.signal});
    if (!response.ok) throw Error('positions');
    const page: Page = await response.json();
    if (ac.signal.aborted) return;
    disconnected = false;
    lastReceivedAt = performance.now();
    last = page;
    renderList();
    el('truncated').hidden = !page.truncated;
    el('source').textContent = demoMode ? 'Пример данных для Финского залива'
      : `Источник: ${sourceNames[page.source.sync_state]} · ${clock.format(new Date(page.as_of))} UTC`;
    showConnection(demoMode ? 'Синтетические данные' : 'Соединение активно', demoMode ? 'demo' : 'ok');
    if (!demoMode && selectedPoint) void refreshDetail(selectedPoint);
  } catch {
    if (ac.signal.aborted) return;
    disconnected = true;
    detailRequest?.abort();
    showConnection('Нет соединения · данные устарели','warning');
    list.setAttribute('aria-busy','false');
    if (!last) {
      el('source').textContent = 'Ответ источника пока не получен';
      list.replaceChildren(emptyState('API недоступен.','Проверьте запуск локального сервера. Повторим запрос автоматически.'));
    } else {
      renderList();
      if (detailState) renderDetail(true);
      else if (selectedKey) unavailable('Не удалось загрузить наблюдение. Повторим запрос автоматически.');
    }
  } finally {
    if (!ac.signal.aborted && !demoMode) timer = setTimeout(() => void refresh(),5000);
  }
}
search.addEventListener('input',() => { if (last) renderList(); });
box.addEventListener('keydown',event => {
  if (event.key === 'Escape' && (selectedKey || box.querySelector('.detail-close'))) closeDetail(true);
});
resetDetail();
list.replaceChildren(element('p','Загрузка наблюдений…','placeholder-copy'));
map.on('load',() => {
  drawHistory = historyLayer(map,el('history-legend'));
  map.on('click','points',event => {
    const feature = event.features?.[0]?.properties;
    const position = filtered().find(p => p.mmsi === feature?.mmsi && p.source_id === feature.source_id);
    if (position) void select(position);
  });
  map.on('mouseenter','points',() => {map.getCanvas().style.cursor = 'pointer';});
  map.on('mouseleave','points',() => {map.getCanvas().style.cursor = '';});
  ready = true;
  syncTheme();
  void refresh();
});
map.on('moveend',() => {centreReadout(); void refresh();});
window.addEventListener('pagehide',event => {
  if (event.persisted) return;
  ready = false;
  listRequest?.abort();
  detailRequest?.abort();
  selection?.abort();
  if (timer) clearTimeout(timer);
  chart.cleanup();
},{once:true});
