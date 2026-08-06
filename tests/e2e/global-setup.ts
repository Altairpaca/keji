import { FullConfig, chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const STORAGE = 'tests/e2e/.auth/admin.json';

export default async function globalSetup(_config: FullConfig) {
  mkdirSync(dirname(STORAGE), { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:8000/accounts/login/');
  await page.fill('input[name="username"]', 'admin');
  await page.fill('input[name="password"]', 'Admin!234');
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith('/accounts/login'));
  await page.context().storageState({ path: STORAGE });
  await browser.close();
}
