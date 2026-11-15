import {test, expect} from '@playwright/test';

test('synthetic database observation reaches the map and detail', async ({page}) => {
  test.skip(process.env.SFD_REAL_API_TEST !== '1', 'Requires isolated synthetic DB and local API');
  await page.goto('/');
  await expect(page.getByRole('button',{name:'987654321'})).toBeVisible();
  await page.getByRole('button',{name:'987654321'}).click();
  await expect(page.getByText('Координаты: 60.0000, 25.0000')).toBeVisible();
  await expect(page.getByText('Скорость: 0 уз.')).toBeVisible();
  await page.getByRole('button',{name:'Показать наблюдения за час'}).click();
  await expect(page.getByRole('list',{name:'История наблюдений'})).toContainText('60.0000, 25.0000');
  await page.getByText('Качество наблюдений AIS', {exact:true}).click();
  await expect(page.getByText('Для оценки интервала нужны хотя бы две точки.')).toBeVisible();
  if (process.env.SFD_ACCEPT_DOSSIER === '1') {
    await page.getByRole('button',{name:'Открыть досье'}).click();
    await expect(page.getByText('Синтетическая иллюстрация записи реестра.', {exact:false})).toBeVisible();
  }
});

test('synthetic failure, restart, expiration and UI recovery', async ({page}) => {
  test.skip(process.env.SFD_REAL_API_TEST !== '1', 'Requires isolated synthetic DB and local API');
  const {execFileSync} = await import('node:child_process');
  const path = await import('node:path');
  const root = path.resolve(process.cwd(), '..');
  const fixture = (action:string) => execFileSync(path.join(root,'.venv/bin/python'),
    [path.join(root,'tests/integration/lifecycle_fixture.py'), action], {env:process.env,stdio:'pipe'});
  fixture('reset');
  await page.goto('/');
  await expect(page.getByRole('button',{name:'987654321'})).toBeVisible();
  await page.getByRole('button',{name:'987654321'}).click();
  await expect(page.getByText('Конфликт наблюдений за одну секунду')).toBeVisible();
  fixture('disconnect');
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByText(/Источник: degraded/)).toBeVisible();
  fixture('failure');
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByRole('button',{name:'987654321'})).toBeVisible();
  fixture('restart');
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByText(/Источник: live/)).toBeVisible();
  let fail = true;
  await page.route('**/v1/positions?**', route => {
    if (fail) {fail = false; return route.fulfill({status:503,body:'unavailable'});}
    return route.continue();
  });
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByRole('status')).toContainText('Нет соединения');
  await expect(page.getByRole('button',{name:'987654321'})).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Соединение активно', {timeout:10000});
  fixture('expire');
  await page.getByRole('button',{name:'Zoom in'}).click();
  await expect(page.getByText('Это не означает отсутствие судов.',{exact:false})).toBeVisible();
});
