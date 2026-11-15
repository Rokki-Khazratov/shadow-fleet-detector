import { test, expect } from '@playwright/test';

const item = {source_id:'fintraffic', mmsi:'123456789', lon:25, lat:60,
  provider_time:'2026-01-01T00:00:00Z', received_at:'2026-01-01T00:00:00Z',
  time_precision:'second', transport:'mqtt', age_seconds:0, stale:false,
  time_conflict:false, clock_skew:false, sog_kn:0, cog_deg:null, heading_deg:null};
const source = {id:'fintraffic', attribution:'Fintraffic / Digitraffic',
  license_url:'https://creativecommons.org/licenses/by/4.0/', sync_state:'live',
  last_mqtt_at:'2026-01-01T00:00:00Z',last_snapshot_at:'2026-01-01T00:00:00Z'};

test('a selected card follows updates and expires with a confirmed 404', async ({page}) => {
  const as_of = '2026-01-01T00:00:00Z';
  let latest = item;
  let expired = false;
  await page.route('**/v1/positions/**', r => expired ? r.fulfill({status:404})
    : r.fulfill({json:{as_of,source,item:latest}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of,source,items:expired ? [] : [latest],truncated:false}}));
  await page.goto('/');
  await page.getByRole('button',{name:item.mmsi,exact:true}).click();
  await expect(page.getByText('Координаты: 60.0000, 25.0000')).toBeVisible();
  const history = await page.getByRole('button',{name:'Показать наблюдения за час'}).elementHandle();
  latest = {...item, lat:60.1, time_conflict:true};
  await expect(page.getByText('Координаты: 60.1000, 25.0000')).toBeVisible({timeout:10000});
  await expect(page.getByText('Конфликт наблюдений за одну секунду')).toBeVisible();
  expect(await history!.evaluate(node => node.isConnected)).toBe(true);
  expired = true;
  await expect(page.getByText('Наблюдение больше недоступно.')).toBeVisible({timeout:10000});
  await expect(page.locator('#detail').getByText('Координаты:',{exact:true})).toHaveCount(0);
  await expect(page.locator('.reticle')).toHaveCount(0);
});

test('an outage marks cached observations stale and advances their age', async ({page}) => {
  const as_of = '2026-01-01T00:00:22Z';
  const observed = {...item, age_seconds:22};
  let up = true;
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of,source,item:observed}}));
  await page.route('**/v1/positions?**', r => up ? r.fulfill({json:{as_of,source,items:[observed],truncated:false}})
    : r.fulfill({status:503}));
  await page.goto('/');
  const row = page.getByRole('button',{name:item.mmsi,exact:true});
  await row.click();
  await expect(page.locator('.detail-meta')).toContainText('Свежая точка · 22 с');
  up = false;
  await expect(page.getByRole('status')).toContainText('Нет соединения',{timeout:10000});
  await expect(row).toHaveAttribute('data-freshness','old');
  await expect(row).not.toContainText('22 с');
  await expect(page.locator('.detail-meta')).toContainText('Устарела');
  await expect(page.locator('.detail-meta')).not.toContainText('22 с');
});

test('accessible observation selection opens details', async ({page}) => {
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}}));
  await page.goto('/');
  await expect(page.getByRole('link',{name:'Берега: Natural Earth'})).toBeVisible();
  await page.getByRole('button',{name:'123456789'}).click();
  await expect(page.getByText('Скорость: 0 уз.')).toBeVisible();
});

test('empty result is explicit on mobile', async ({page}) => {
  await page.setViewportSize({width:360,height:800});
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[],truncated:false}}));
  await page.goto('/');
  await expect(page.getByText('Это не означает отсутствие судов.',{exact:false})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('failed API displays disconnected state', async ({page}) => {
  await page.route('**/v1/positions?**', r => r.fulfill({status:503,body:'unavailable'}));
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('Нет соединения');
  await expect(page.getByText('API недоступен.',{exact:false})).toBeVisible();
});

test('truncation and degraded source are visible', async ({page}) => {
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source:{...source,sync_state:'degraded'},items:[{...item,stale:true}],truncated:true}}));
  await page.goto('/');
  await expect(page.getByText('Показаны первые 2 000 наблюдений; приблизьте карту.')).toBeVisible();
  await expect(page.getByText(/Источник: поток недоступен/)).toBeVisible();
  await expect(page.getByRole('button',{name:'123456789'})).toHaveAttribute('title','Устаревшее наблюдение');
});

test('synthetic desktop layout', async ({page}) => {
  await page.setViewportSize({width:1440,height:900});
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}}));
  await page.goto('/');
  await expect(page.getByRole('button',{name:'123456789'})).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({path:'test-results/synthetic-desktop.png'});
});

test('disconnected view recovers on the next poll', async ({page}) => {
  let calls = 0;
  await page.route('**/v1/positions?**', route => {
    calls++;
    return calls === 1 ? route.fulfill({status:503,body:'unavailable'}) :
      route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}});
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('Нет соединения');
  await expect(page.getByRole('status')).toContainText('Соединение активно', {timeout:10000});
  await expect(page.getByRole('button',{name:'123456789'})).toBeVisible();
});

test('missing position detail is explained', async ({page}) => {
  await page.route('**/v1/positions/**', route => route.fulfill({status:404, json:{error:{code:'not_found',message:'Not found'}}}));
  await page.route('**/v1/positions?**', route => route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}}));
  await page.goto('/');
  await page.getByRole('button',{name:'123456789'}).click();
  await expect(page.getByRole('heading',{name:'Карточка недоступна'})).toBeVisible();
});

test('detail labels clock skew and time conflict', async ({page}) => {
  const detail = {...item,clock_skew:true,time_conflict:true};
  await page.route('**/v1/positions/**', route => route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,item:detail}}));
  await page.route('**/v1/positions?**', route => route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[detail],truncated:false}}));
  await page.goto('/');
  await page.getByRole('button',{name:'123456789'}).click();
  await expect(page.getByText('Сдвиг времени источника')).toBeVisible();
  await expect(page.getByText('Конфликт наблюдений за одну секунду')).toBeVisible();
});

test('late response from old viewport cannot replace new results', async ({page}) => {
  let calls = 0;
  let firstStarted!: () => void;
  const first = new Promise<void>(resolve => {firstStarted = resolve;});
  await page.route('**/v1/positions?**', async route => {
    calls++;
    if (calls === 1) {
      firstStarted();
      await new Promise(resolve => setTimeout(resolve,1500));
      await route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}}).catch(() => {});
    } else {
      await route.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[{...item,mmsi:'987654321'}],truncated:false}});
    }
  });
  await page.goto('/');
  await first;
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByRole('button',{name:'987654321'})).toBeVisible();
  await page.waitForTimeout(1700);
  await expect(page.getByRole('button',{name:'123456789'})).toHaveCount(0);
});

test('history loads only for the selected MMSI and explains truncation', async ({page}) => {
  const asOf = '2026-01-01T01:00:00Z';
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/history/fintraffic/123456789?**', r => r.fulfill({json:{
    source,mmsi:item.mmsi,items:[item],truncated:true,
  }}));
  await page.goto('/');
  await page.getByRole('button',{name:'123456789'}).click();
  const request = page.waitForRequest('**/v1/history/fintraffic/123456789?**');
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  const query = new URL((await request).url()).searchParams;
  expect(query.get('from')).toBe('2026-01-01T00:00:00.000Z');
  expect(query.get('to')).toBe('2026-01-01T01:00:00.000Z');
  await expect(page.getByRole('list',{name:'История наблюдений'})).toContainText('60.0000, 25.0000');
  await expect(page.getByText('Показаны первые 100 наблюдений за этот час.')).toBeVisible();
});

test('empty history is different from an unavailable API', async ({page}) => {
  const asOf = '2026-01-01T01:00:00Z';
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/history/**', r => r.fulfill({json:{source,mmsi:item.mmsi,items:[],truncated:false}}));
  await page.goto('/');
  await page.getByRole('button',{name:'123456789'}).click();
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await expect(page.getByText('За этот час нет сохранённых наблюдений.')).toBeVisible();
  await page.route('**/v1/history/**', r => r.fulfill({status:503}));
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await expect(page.getByText('История временно недоступна.')).toBeVisible();
});

test('history uses the selected UTC window and discards the previous window', async ({page}) => {
  const asOf = '2026-01-02T01:00:00Z';
  const first = {...item, provider_time:'2026-01-02T00:09:02Z'};
  const older = {...item, provider_time:'2026-01-01T22:03:04Z'};
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/history/**', r => r.fulfill({json:{source,mmsi:item.mmsi,
    items:new URL(r.request().url()).searchParams.get('from')?.startsWith('2026-01-01') ? [older,first] : [first],
    truncated:false,
  }}));
  await page.goto('/');
  await page.getByRole('button',{name:item.mmsi}).click();
  const history = page.getByRole('list',{name:'История наблюдений'});
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await expect(history).toContainText('00:09:02');
  await page.getByRole('combobox',{name:'Период истории'}).selectOption('6');
  await expect(history).toHaveCount(0);
  await expect(page.getByText('Точки истории выбранного сигнала')).toBeHidden();
  const pending = page.waitForRequest('**/v1/history/**');
  await page.getByRole('button',{name:'Показать наблюдения за 6 часов'}).click();
  const query = new URL((await pending).url()).searchParams;
  expect(query.get('from')).toBe('2026-01-01T19:00:00.000Z');
  expect(query.get('to')).toBe('2026-01-02T01:00:00.000Z');
  await expect(history.locator('time')).toHaveText([/01\.01\.2026,? 22:03:04/, /02\.01\.2026,? 00:09:02/]);
});

test('a delayed response cannot restore the old history window', async ({page}) => {
  const asOf = '2026-01-02T01:00:00Z';
  let releaseOld!: () => void;
  let oldHandled!: () => void;
  const stalled = new Promise<void>(resolve => {releaseOld = resolve;});
  const oldFinished = new Promise<void>(resolve => {oldHandled = resolve;});
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/history/**', async r => {
    const from = new URL(r.request().url()).searchParams.get('from');
    if (from === '2026-01-02T00:00:00.000Z') {
      await stalled;
      try {
        await r.fulfill({json:{items:[{...item,provider_time:'2026-01-02T00:35:00Z'}],truncated:false}});
      } catch {
        // The browser can already have canceled the old request.
      } finally {
        oldHandled();
      }
      return;
    }
    await r.fulfill({json:{items:[{...item,provider_time:'2026-01-01T03:27:00Z'}],truncated:false}});
  });
  try {
    await page.goto('/');
    await page.getByRole('button',{name:item.mmsi}).click();
    const old = page.waitForRequest('**/v1/history/**');
    await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
    await old;
    await page.getByRole('combobox',{name:'Период истории'}).selectOption('24');
    const next = page.waitForRequest('**/v1/history/**');
    await page.getByRole('button',{name:'Показать наблюдения за 24 часа'}).click();
    expect(new URL((await next).url()).searchParams.get('from')).toBe('2026-01-01T01:00:00.000Z');
    const dates = page.getByRole('list',{name:'История наблюдений'}).locator('time');
    await expect(dates).toHaveText([/01\.01\.2026,? 03:27:00/]);
    releaseOld();
    await oldFinished;
    await expect(dates).toHaveText([/01\.01\.2026,? 03:27:00/]);
  } finally {
    releaseOld();
  }
});

test('history point can be inspected on the map and clears on selection', async ({page}) => {
  const asOf = '2026-01-01T01:00:00Z';
  const other = {...item,mmsi:'987654321'};
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item,other],truncated:false}}));
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,
    item:r.request().url().endsWith(other.mmsi) ? other : item,
  }}));
  await page.route('**/v1/history/**', r => r.fulfill({json:{source,mmsi:item.mmsi,
    items:[{...item,lon:25.5}],truncated:false,
  }}));
  await page.goto('/');
  await page.getByRole('button',{name:item.mmsi}).click();
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await expect(page.getByText('Точки истории выбранного сигнала')).toBeVisible();
  const canvas = await page.locator('#map canvas').boundingBox();
  expect(canvas).not.toBeNull();
  await expect(async () => {
    await page.mouse.click(canvas!.x + canvas!.width / 2 + 45.5, canvas!.y + canvas!.height / 2);
    await expect(page.locator('.maplibregl-popup')).toContainText('25.5000', {timeout:300});
  }).toPass({timeout:4000});
  await page.getByRole('button',{name:other.mmsi}).click();
  await expect(page.getByRole('heading',{name:other.mmsi})).toBeVisible();
  await expect(page.getByText('Точки истории выбранного сигнала')).toBeHidden();
  await expect(page.locator('.maplibregl-popup')).toHaveCount(0);
});

test('dossier separates source citations from the AIS detail', async ({page}) => {
  const asOf = '2026-01-01T01:00:00Z';
  const citation = {title:'Синтетический реестр', url:'https://example.org/register',
    retrieved_on:'2026-01-01',license_note:'Синтетика'};
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/dossier/**', r => r.fulfill({json:{status:'linked',on:'2026-01-01',
    bindings:[{namespace:'registry',identifier:'TEST-1',since:'2025-12-01',until:'2026-02-01',citation}],
    external_claims:[{statement:'Синтетическая запись',published_on:'2025-12-31',citation}],
  }}));
  await page.goto('/');
  await page.getByRole('button',{name:item.mmsi}).click();
  await page.getByRole('button',{name:'Открыть досье'}).click();
  const dossier = page.getByRole('region',{name:'Досье сигнала'});
  await expect(dossier.getByRole('heading',{name:'Внешние утверждения'})).toBeVisible();
  await expect(dossier.getByText('Синтетическая запись')).toBeVisible();
  await expect(dossier.getByRole('link',{name:citation.title}).first()).toHaveAttribute('href',citation.url);
  await expect(dossier).toContainText('registry: TEST-1');
});

test('AIS quality reports an observed interval without assigning a cause', async ({page}) => {
  const asOf = '2026-01-01T01:00:00Z';
  const later = {...item, provider_time:'2026-01-01T00:20:00Z'};
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:asOf,source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:asOf,source,items:[item],truncated:false}}));
  await page.route('**/v1/history/**', r => r.fulfill({json:{source,mmsi:item.mmsi,items:[item,later],truncated:false,
    quality:{observed_points:2,conflict_count:0,clock_skew_count:0,interval_status:'assessed',
      long_interval_threshold_seconds:900,long_interval_count:1,
      long_intervals:[{before:item.provider_time,after:later.provider_time,duration_seconds:1200}]},
  }}));
  await page.goto('/');
  await page.getByRole('button',{name:item.mmsi}).click();
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await page.getByText('Качество наблюдений AIS', {exact:true}).click();
  await expect(page.getByText('Интервалы ≥ 15 мин: 1.')).toBeVisible();
  await expect(page.getByText('Причина интервалов неизвестна.')).toBeVisible();
});
