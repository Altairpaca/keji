import { test, expect, Page } from '@playwright/test';

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

/** 本地日期 YYYY-MM-DD（今天 ± offset 天） */
function localDate(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

async function createTask(page: Page, title: string, dueDate: string): Promise<void> {
  await page.goto('/tasks/new/');
  await page.fill('#id_title', title);
  await page.selectOption('#id_task_type', { label: '打电话' });
  await page.fill('#id_due_date', dueDate);
  await page.getByRole('button', { name: '保存' }).click();
  await page.waitForURL('**/tasks/');
}

test.describe('待办工作流', () => {
  test('待办列表可见：seed 数据与统计栏', async ({ page }) => {
    await page.goto('/tasks/');
    await expect(page.locator('main')).toBeVisible();
    // seed 演示待办存在
    const cards = page.locator('[data-testid="task-card"]');
    expect(await cards.count()).toBeGreaterThan(0);
    // 统计栏（右栏摘要 dl）包含三类计数标签
    const summary = page.locator('aside dl');
    await expect(summary.getByText('未完成')).toBeVisible();
    await expect(summary.getByText('已完成')).toBeVisible();
    await expect(summary.getByText('已逾期')).toBeVisible();
  });

  test('新建待办（过去截止日）→ 列表出现且逾期标红', async ({ page }) => {
    const title = unique('E2E待办');
    await createTask(page, title, localDate(-1));
    const card = page.locator('[data-testid="task-card"]', { hasText: title });
    await expect(card).toBeVisible();
    // 逾期标记红字「逾期 ·」
    await expect(card.getByText(/逾期 ·/)).toBeVisible();
    const red = card.locator('.text-red-600');
    await expect(red.first()).toBeVisible();
  });

  test('完成勾选 → 状态变已完成', async ({ page }) => {
    const title = unique('E2E完成待办');
    // 截止今天：任务列表按 due_date 升序，今天的任务在首页可见
    await createTask(page, title, localDate(0));
    const card = page.locator('[data-testid="task-card"]', { hasText: title });
    await expect(card).toBeVisible();
    // 点击完成（HTMX 局部刷新卡片）
    await card.getByRole('button', { name: '完成', exact: true }).click();
    await expect(card.getByText('已完成')).toBeVisible();
    await expect(card.getByRole('button', { name: '完成' })).toHaveCount(0);
  });
});
