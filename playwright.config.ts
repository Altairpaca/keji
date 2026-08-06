import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  timeout: 30_000,
  // workers=1：多个工作流 spec 都会写数据（建客户/事件/待办/保单/理赔/上传），
  // 串行执行避免并发写入互相干扰（规格 §28）。
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8000',
    storageState: 'tests/e2e/.auth/admin.json',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      // 业务工作流 + 桌面布局在 desktop 跑；mobile.spec 只归 mobile project。
      testIgnore: /mobile\.spec\.ts/,
    },
    {
      name: 'mobile',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
});
