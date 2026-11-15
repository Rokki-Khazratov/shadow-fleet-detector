import { demoMode, request } from './api';
import type { HistoryOverlay } from './history-layer';
import { qualityDetails, type QualityReport } from './quality';
import { icons } from './workspace';

export interface HistoryPoint {provider_time: string; lat: number; lon: number; time_conflict: boolean}

interface HistoryPage {
  items: HistoryPoint[];
  truncated: boolean;
  quality?: QualityReport;
}

const windows = [
  {hours:1, name:'1 час', action:'за час', context:'за этот час', empty:'За этот час'},
  {hours:6, name:'6 часов', action:'за 6 часов', context:'за 6 часов', empty:'За эти 6 часов'},
  {hours:24, name:'24 часа', action:'за 24 часа', context:'за 24 часа', empty:'За эти 24 часа'},
] as const;
const limit = 100;
const utc = new Intl.DateTimeFormat('ru-RU', {
  timeZone:'UTC', day:'2-digit', month:'2-digit', year:'numeric',
  hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23',
});
export const historyTime = (value: string) => `${utc.format(new Date(value))} UTC`;

export function historyPanel(sourceId: string, mmsi: string, asOf: () => string, signal: AbortSignal, overlay: HistoryOverlay) {
  const panel = document.createElement('section');
  panel.className = 'history';
  panel.setAttribute('aria-label','История сигнала');
  const controls = document.createElement('div');
  controls.className = 'history-controls';
  const label = document.createElement('label');
  label.textContent = 'Период истории';
  const period = document.createElement('select');
  for (const window of windows) period.add(new Option(window.name,String(window.hours)));
  label.append(period);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'history-button';
  controls.append(label,button);
  const output = document.createElement('div');
  output.className = 'history-output';
  panel.append(controls,output);

  const windowLabel = () => windows[period.selectedIndex] ?? windows[0];
  const updateLabel = () => {button.textContent = `Показать наблюдения ${windowLabel().action}`;};
  updateLabel();
  let active: AbortController | undefined;
  signal.addEventListener('abort',() => active?.abort(),{once:true});
  period.addEventListener('change',() => {
    active?.abort();
    active = undefined;
    button.disabled = false;
    updateLabel();
    output.replaceChildren();
    overlay.replace([]);
  });
  const show = (message: string) => {
    const text = document.createElement('p');
    text.textContent = message;
    output.replaceChildren(text);
  };

  button.addEventListener('click', async () => {
    if (signal.aborted) return;
    const window = windowLabel();
    const controller = active = new AbortController();
    button.disabled = true;
    show('Загрузка истории…');
    overlay.replace([]);
    try {
      const end = new Date(asOf());
      const start = new Date(end.getTime() - window.hours * 3_600_000);
      const query = new URLSearchParams({from:start.toISOString(), to:end.toISOString(), limit:String(limit)});
      const url = `/v1/history/${encodeURIComponent(sourceId)}/${encodeURIComponent(mmsi)}?${query}`;
      const response = await request(url,{signal:controller.signal});
      if (!response.ok) throw new Error('history request failed');
      const page: HistoryPage = await response.json();
      if (controller.signal.aborted) return;
      show(page.items.length === 0 ? `${window.empty} нет сохранённых наблюдений.`
        : page.truncated ? `Показаны первые ${limit} наблюдений ${window.context}.`
        : demoMode ? 'Синтетические наблюдения' : 'Сохранённые наблюдения');
      const range = document.createElement('p');
      range.className = 'history-range';
      range.textContent = `${utc.format(start)} — ${utc.format(end)} UTC`;
      output.append(range);
      if (!page.items.length) return;
      const list = document.createElement('ul');
      list.setAttribute('role','list');
      list.setAttribute('aria-label','История наблюдений');
      list.className = 'history-list history-observations';
      const rows = new Map<string,HTMLButtonElement>();
      for (const point of page.items) {
        const li = document.createElement('li');
        const time = document.createElement('time');
        time.dateTime = point.provider_time;
        time.textContent = historyTime(point.provider_time);
        const coordinates = document.createElement('span');
        coordinates.textContent = `${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`
          + (point.time_conflict ? ' · конфликт времени' : '');
        const label = document.createElement('span');
        label.append(time,coordinates);
        const locate = document.createElement('span');
        locate.innerHTML = icons.reset;
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'history-observation';
        row.setAttribute('aria-label',`Показать на карте: ${time.textContent}, ${coordinates.textContent}`);
        row.setAttribute('aria-pressed','false');
        row.addEventListener('click',() => overlay.inspect(point,() => {
          if (row.isConnected) row.focus();
        }));
        row.append(label,locate);
        rows.set(point.provider_time,row);
        li.append(row);
        list.append(li);
      }
      const hint = document.createElement('p');
      hint.className = 'history-hint';
      hint.textContent = 'Выберите наблюдение, чтобы показать его на карте.';
      output.append(hint,list);
      if (page.quality) output.append(qualityDetails(page.quality));
      let highlighted: HTMLButtonElement | undefined;
      overlay.replace(page.items,point => {
        highlighted?.setAttribute('aria-pressed','false');
        highlighted = point ? rows.get(point.provider_time) : undefined;
        if (highlighted) {
          highlighted.setAttribute('aria-pressed','true');
          const row = highlighted.getBoundingClientRect();
          const viewport = list.getBoundingClientRect();
          if (row.top < viewport.top) list.scrollTop -= viewport.top - row.top;
          if (row.bottom > viewport.bottom) list.scrollTop += row.bottom - viewport.bottom;
        }
      });
    } catch {
      if (!controller.signal.aborted) show('История временно недоступна.');
    } finally {
      if (active === controller) {
        active = undefined;
        button.disabled = false;
      }
    }
  });
  return panel;
}
