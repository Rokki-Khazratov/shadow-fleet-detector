import { expect, test } from '@playwright/test';

test('demo is isolated from the live API and supports keyboard selection', async ({page}) => {
  let apiCalls = 0;
  await page.route('**/v1/**', route => {apiCalls++; return route.abort();});
  await page.goto('/?demo=1');
  await expect(page.getByRole('status')).toContainText('Синтетические данные');
  const search = page.getByRole('searchbox', {name:'Поиск по MMSI'});
  await search.fill('900000002');
  await expect(page.getByRole('button', {name:'900000001', exact:true})).toHaveCount(0);
  await search.press('Tab');
  await expect(page.getByRole('button', {name:'900000002', exact:true})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', {name:'900000002', exact:true})).toBeVisible();
  await page.getByRole('button', {name:'Показать наблюдения за час'}).click();
  await expect(page.getByRole('list', {name:'История наблюдений'})).toBeVisible();
  expect(apiCalls).toBe(0);
});

test('appearance can switch without reloading the map', async ({page}) => {
  await page.goto('/?demo=1');
  const map = page.locator('#map canvas');
  await expect(map).toBeVisible();
  const canvas = await map.elementHandle();
  await page.getByRole('button', {name:'Светлая тема'}).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  expect(await canvas!.evaluate(el => el.isConnected)).toBe(true);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
});

test('mobile history brings the chart and selected point into view', async ({page}, info) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/?demo=1');
  await page.getByRole('button',{name:'900000002',exact:true}).click();
  await page.getByRole('combobox',{name:'Период истории'}).selectOption('24');
  await page.getByRole('button',{name:'Показать наблюдения за 24 часа'}).click();
  const row = page.getByRole('list',{name:'История наблюдений'}).getByRole('button').first();
  await row.focus();
  await page.screenshot({path:info.outputPath('history-mobile-list.png')});
  await page.keyboard.press('Enter');
  await expect(page.locator('#map canvas')).toBeFocused();
  await expect(page.locator('.history-popup')).toBeInViewport();
  await expect(row).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({path:info.outputPath('history-mobile-map.png')});
  await page.keyboard.press('Escape');
  await expect(page.locator('.history-popup')).toHaveCount(0);
  await expect(row).toBeFocused();
  await expect(row).toBeInViewport();
  await expect(row).toHaveAttribute('aria-pressed','false');
});

test('chart workspace fits wide, medium, and narrow layouts', async ({page}, info) => {
  await page.goto('/?demo=1');
  await expect(page.getByRole('status')).toContainText('Синтетические данные');
  for (const [width, height] of [[1440,900],[1024,768],[768,1024],[390,844],[320,740]]) {
    await page.setViewportSize({width,height});
    await expect(page.getByRole('heading',{name:'Морская карта'})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    if (width === 1440 || width === 390) await page.screenshot({path:info.outputPath(`workspace-${width}-dark.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('button',{name:'Светлая тема'}).click();
  await page.getByRole('button',{name:'900000002',exact:true}).click();
  await expect(page.getByRole('heading',{name:'900000002',exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('workspace-1440-light.png')});
});
