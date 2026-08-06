#!/usr/bin/env node
/**
 * 采集 keji 全部关键页面的真实运行截图（虚构数据）。
 * 用法：node scripts/capture_screenshots.mjs [--pilot]
 *   --pilot 只截 desktop-home + mobile-home，用于 CJK 渲染抽查
 * 输出：docs/screenshots/{desktop|mobile}-*.png
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8000';
const OUT = path.resolve(process.cwd(), 'docs/screenshots');
const AUTH = path.resolve(process.cwd(), 'tests/e2e/.auth/admin.json');
const USERNAME = 'admin';
const PASSWORD = 'Admin!234';

fs.mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

async function loginIfNeeded(page) {
  if (!page.url().includes('/accounts/login/')) return false;
  await page.locator('input[name="username"]').fill(USERNAME);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState('networkidle');
  if (page.url().includes('/accounts/login/')) throw new Error('登录失败');
  return true;
}

async function firstUuid(page, listUrl, hrefPrefix) {
  await page.goto(BASE + listUrl, { waitUntil: 'networkidle', timeout: 30000 });
  const hrefs = await page
    .locator(`a[href^="${hrefPrefix}"]`)
    .evaluateAll((els, re) =>
      els
        .map((e) => e.getAttribute('href') || '')
        .map((h) => h.match(re))
        .filter(Boolean)
        .map((m) => m[0]),
      UUID_RE,
    );
  if (!hrefs.length) throw new Error(`在 ${listUrl} 未找到 ${hrefPrefix} 的详情链接`);
  return hrefs[0];
}

async function captureViewport(browser, viewport, isMobile, pages) {
  const ctx = await browser.newContext({
    storageState: AUTH,
    viewport,
    isMobile,
    hasTouch: isMobile,
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  let lastNavStatus = 0;
  page.on('response', (r) => {
    if (r.request().isNavigationRequest()) lastNavStatus = r.status();
  });
  const results = [];
  for (const p of pages) {
    const t0 = Date.now();
    await page.goto(BASE + p.url, { waitUntil: 'networkidle', timeout: 30000 });
    if (await loginIfNeeded(page)) console.log('    [登录] 会话失效，已用 admin 重新登录');
    for (const sel of p.wait ?? []) {
      await page.locator(sel).first().waitFor({ state: 'visible', timeout: 10000 });
    }
    await sleep(p.sleep ?? 600);
    const file = `${p.name}.png`;
    await page.screenshot({ path: path.join(OUT, file) });
    const size = fs.statSync(path.join(OUT, file)).size;
    results.push({ name: file, size, status: lastNavStatus, url: page.url() });
    console.log(`    ✓ ${file}  ${size}B  http=${lastNavStatus}  ${Date.now() - t0}ms`);
  }
  await ctx.close();
  return results;
}

const pilot = process.argv.includes('--pilot');

const browser = await chromium.launch();

let custUuid = null;
let docUuid = null;
let claimUuid = null;
if (!pilot) {
  const probe = await browser.newContext({ storageState: AUTH, viewport: { width: 1440, height: 900 } });
  const p = await probe.newPage();
  custUuid = await firstUuid(p, '/customers/', '/customers/');
  console.log(`客户详情 UUID: ${custUuid}`);
  docUuid = await firstUuid(p, '/documents/', '/documents/');
  console.log(`文档详情 UUID: ${docUuid}`);
  claimUuid = await firstUuid(p, '/claims/', '/claims/');
  console.log(`理赔详情 UUID: ${claimUuid}`);
  await probe.close();
}

const desktopPages = pilot
  ? [{ name: 'desktop-home', url: '/' }]
  : [
  { name: 'desktop-home', url: '/' },
  { name: 'desktop-customers', url: '/customers/' },
  { name: 'desktop-customer-detail', url: `/customers/${custUuid}/`, wait: ['main', 'h1'] },
  { name: 'desktop-documents', url: '/documents/' },
  { name: 'desktop-document-viewer', url: `/documents/${docUuid}/`, wait: ['main'], sleep: 800 },
  { name: 'desktop-upload', url: '/documents/upload/' },
  { name: 'desktop-albums', url: '/documents/albums/' },
  { name: 'desktop-policies', url: '/policies/' },
  { name: 'desktop-claims', url: '/claims/' },
  { name: 'desktop-claim-detail', url: `/claims/${claimUuid}/` },
  { name: 'desktop-tasks', url: '/tasks/' },
  { name: 'desktop-activities', url: '/activities/' },
  { name: 'desktop-search', url: '/search/?q=演示' },
  // 关系图需选有关系数据的客户（3 个关系）才能渲染出图
  { name: 'desktop-graph', url: `/customers/3326f17e-a20d-4a26-8d70-533a5e0de456/graph-page/`, wait: ['canvas, #relation-graph, main'], sleep: 1500 },
];

const mobilePages = pilot
  ? [{ name: 'mobile-home', url: '/', sleep: 800 }]
  : [
  { name: 'mobile-home', url: '/', sleep: 800 },
  { name: 'mobile-customers', url: '/customers/' },
  { name: 'mobile-customer-detail', url: `/customers/${custUuid}/` },
  { name: 'mobile-upload', url: '/documents/upload/', sleep: 800 },
  { name: 'mobile-tasks', url: '/tasks/' },
  { name: 'mobile-claim-materials', url: `/claims/${claimUuid}/` },
];

console.log('\n=== 桌面 1440x900 ===');
const desktop = await captureViewport(browser, { width: 1440, height: 900 }, false, desktopPages);
console.log('\n=== 手机 390x844 ===');
const mobile = await captureViewport(browser, { width: 390, height: 844 }, true, mobilePages);

await browser.close();

const all = [...desktop, ...mobile];
console.log(`\n共 ${all.length} 张截图 -> ${OUT}`);
const bad = all.filter((r) => r.status >= 400 || r.url.includes('/accounts/login/'));
if (bad.length) {
  console.error('异常截图（HTTP>=400 或登录重定向）:', bad);
  process.exit(1);
}
