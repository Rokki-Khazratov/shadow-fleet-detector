interface Citation {title: string; url: string; retrieved_on: string; license_note: string}
interface Dossier {
  status: 'not_configured' | 'no_link' | 'linked' | 'ambiguous';
  on: string;
  bindings: {namespace: string; identifier: string; since: string; until: string; citation: Citation}[];
  external_claims: {statement: string; published_on: string; citation: Citation}[];
}

function text(tag: string, value: string) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}

function citationNode(citation: Citation) {
  const link = document.createElement('a');
  const url = new URL(citation.url);
  if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Invalid citation');
  link.href = url.href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = citation.title;
  const note = text('small', `Получено ${citation.retrieved_on} · ${citation.license_note}`);
  note.className = 'citation-note';
  const row = document.createElement('div');
  row.append(link, note);
  return row;
}

export function dossierPanel(source: string, mmsi: string, providerTime: string, signal: AbortSignal) {
  const section = document.createElement('section');
  section.className = 'dossier';
  section.setAttribute('aria-label', 'Досье сигнала');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'history-button';
  button.textContent = 'Открыть досье';
  const output = document.createElement('div');
  section.append(button, output);
  button.addEventListener('click', async () => {
    button.disabled = true;
    output.replaceChildren(text('p', 'Загрузка досье…'));
    try {
      const on = new Date(providerTime).toISOString().slice(0, 10);
      const url = `/v1/dossier/${encodeURIComponent(source)}/${encodeURIComponent(mmsi)}?on=${on}`;
      const response = await fetch(url, {signal});
      if (!response.ok) throw new Error('Dossier unavailable');
      const data: Dossier = await response.json();
      if (signal.aborted) return;
      if (data.status === 'no_link' || data.status === 'not_configured') {
        output.replaceChildren(text('p', data.status === 'no_link'
          ? `На ${data.on} UTC нет сохранённой связи с внешним источником.`
          : 'Локальный каталог внешних сведений не настроен.'));
        return;
      }
      output.replaceChildren(text('h3', 'Связи с внешними идентификаторами'), text('p', `Дата сигнала: ${data.on} UTC.`));
      for (const b of data.bindings) {
        output.append(text('p', `${b.namespace}: ${b.identifier} · ${b.since} — ${b.until} (конец не включён)`),
          citationNode(b.citation));
      }
      if (data.status === 'ambiguous') {
        output.append(text('p', 'Связи неоднозначны. Внешние утверждения не привязаны к сигналу.'));
        return;
      }
      output.append(text('h3', 'Внешние утверждения'));
      if (!data.external_claims.length) output.append(text('p', 'На эту дату записи не найдены.'));
      for (const claim of data.external_claims) {
        output.append(text('p', `${claim.published_on} · ${claim.statement}`), citationNode(claim.citation));
      }
      output.append(text('p', 'Приведены записи источников. Они не устанавливают текущий статус судна.'));
    } catch {
      if (!signal.aborted) output.replaceChildren(text('p', 'Досье временно недоступно.'));
    } finally {
      button.disabled = false;
    }
  });
  return section;
}
