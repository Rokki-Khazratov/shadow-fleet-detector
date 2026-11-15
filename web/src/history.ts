import { qualityDetails, type QualityReport } from './quality';

export interface HistoryPoint {provider_time: string; lat: number; lon: number; time_conflict: boolean}

interface HistoryPage {
  items: HistoryPoint[];
  truncated: boolean;
  quality?: QualityReport;
}

export function historyPanel(sourceId: string, mmsi: string, asOf: string, signal: AbortSignal, onPoints: (points: HistoryPoint[]) => void) {
  const panel = document.createElement('div');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'history-button';
  button.textContent = 'Показать наблюдения за час';
  const output = document.createElement('div');
  panel.append(button, output);

  const show = (message: string) => {
    const text = document.createElement('p');
    text.textContent = message;
    output.replaceChildren(text);
  };

  button.addEventListener('click', async () => {
    button.disabled = true;
    show('Загрузка истории…');
    onPoints([]);
    try {
      const end = new Date(asOf);
      const query = new URLSearchParams({from: new Date(end.getTime() - 3_600_000).toISOString(),
        to: end.toISOString(), limit: '100'});
      const url = `/v1/history/${encodeURIComponent(sourceId)}/${encodeURIComponent(mmsi)}?${query}`;
      const response = await fetch(url, {signal});
      if (!response.ok) throw new Error('history request failed');
      const page: HistoryPage = await response.json();
      if (signal.aborted) return;
      onPoints(page.items);
      if (!page.items.length) {
        show('За этот час нет сохранённых наблюдений.');
        return;
      }
      show(page.truncated ? 'Показаны первые 100 наблюдений за этот час.' : 'Сохранённые наблюдения за час, UTC.');
      const list = document.createElement('ul');
      list.setAttribute('aria-label', 'История наблюдений');
      list.className = 'history-list';
      for (const point of page.items) {
        const li = document.createElement('li');
        const time = document.createElement('time');
        time.dateTime = point.provider_time;
        time.textContent = `${new Date(point.provider_time).toISOString().slice(11, 23)} UTC`;
        li.append(time, ` · ${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`);
        if (point.time_conflict) li.append(' · конфликт');
        list.append(li);
      }
      output.append(list);
      if (page.quality) output.append(qualityDetails(page.quality));
    } catch {
      if (!signal.aborted) show('История временно недоступна.');
    } finally {
      button.disabled = false;
    }
  });
  return panel;
}
