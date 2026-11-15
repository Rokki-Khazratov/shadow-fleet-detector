import { test, expect } from '@playwright/test';

const item = {source_id:'fintraffic', mmsi:'123456789', lon:25, lat:60,
  provider_time:'2026-01-01T00:00:00Z', received_at:'2026-01-01T00:00:00Z',
  time_precision:'second', transport:'mqtt', age_seconds:0, stale:false,
  time_conflict:false, clock_skew:false, sog_kn:0, cog_deg:null, heading_deg:null};
const source = {id:'fintraffic', attribution:'Fintraffic / Digitraffic',
  license_url:'https://creativecommons.org/licenses/by/4.0/', sync_state:'live',
  last_mqtt_at:'2026-01-01T00:00:00Z',last_snapshot_at:'2026-01-01T00:00:00Z'};

test('accessible observation selection opens details', async ({page}) => {
  await page.route('**/v1/positions/**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,item}}));
  await page.route('**/v1/positions?**', r => r.fulfill({json:{as_of:'2026-01-01T00:00:00Z',source,items:[item],truncated:false}}));
  await page.goto('/');
  await expect(page.getByText('Техническая подложка')).toBeVisible();
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
  await expect(page.getByText(/Источник: degraded/)).toBeVisible();
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
