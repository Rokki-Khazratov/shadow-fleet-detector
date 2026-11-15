import { defineConfig } from '@playwright/test';

const port = process.env.SFD_TEST_WEB_PORT ?? '5174';
if (!/^[0-9]{1,5}$/.test(port) || Number(port) < 1024 || Number(port) > 65535) {
  throw new Error('SFD_TEST_WEB_PORT must be a port between 1024 and 65535');
}
const url = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir:'./tests',
  use:{baseURL:url, channel:'chrome', launchOptions:{args:['--use-angle=swiftshader']}},
  webServer:{command:`npm run dev -- --port ${port} --strictPort`, url, reuseExistingServer:false, timeout:30000},
});
