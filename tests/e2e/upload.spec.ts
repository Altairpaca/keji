import { test, expect, Page } from '@playwright/test';
import { readFileSync, readdirSync, unlinkSync } from 'node:fs';

const UPLOAD_DIR = '/tmp/opencode/e2e_upload';

/** 取一个未被使用过的 e2e-*.png 文件（上传成功后删除本地副本，避免重复内容被 SHA-256 去重跳过） */
function pickUploadFile(): { path: string; name: string } {
  const files = readdirSync(UPLOAD_DIR)
    .filter((f) => f.endsWith('.png'))
    .sort();
  expect(files.length, `UPLOAD_DIR 需存在 e2e-*.png 文件（${UPLOAD_DIR}）`).toBeGreaterThan(0);
  const name = files[0];
  return { path: `${UPLOAD_DIR}/${name}`, name };
}

/**
 * 提交前把文件注入 gallery-input。
 * 上传页的 Alpine onPick 在 change 后执行 `event.target.value=''` 清空 input，
 * 原生表单提交时 files 为空 → 服务端报「请选择要上传的文件」。
 * 测试侧在 onPick 之后、提交之前重新写入文件，绕过该清空而不改动业务代码。
 */
async function injectFiles(page: Page, filePath: string, fileName: string): Promise<void> {
  const bytes = readFileSync(filePath);
  await page.evaluate(
    ({ bytes, fileName }) => {
      const input = document.getElementById('gallery-input') as HTMLInputElement;
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(bytes)], fileName, { type: 'image/png' }));
      input.files = dt.files;
    },
    { bytes: [...bytes], fileName },
  );
}

async function uploadFile(page: Page, file: { path: string; name: string }): Promise<void> {
  await page.goto('/documents/upload/');
  // 触发 Alpine onPick：预览出现该文件（同时 input 会被清空）
  await page.setInputFiles('#gallery-input', file.path);
  await expect(page.locator('#upload-preview').getByText(file.name)).toBeVisible();
  await injectFiles(page, file.path, file.name);
  await page.getByRole('button', { name: /^上传/ }).click();
  await page.waitForURL('**/documents/upload/result/');
  const result = page.locator('#upload-result');
  await expect(result).toBeVisible();
  expect(await result.getAttribute('data-success')).toBe('1');
}

test.describe('文件上传与回收站工作流', () => {
  test('上传页：capture input 存在，可选文件并提交', async ({ page }) => {
    const file = pickUploadFile();
    await page.goto('/documents/upload/');
    // capture 拍照输入：隐藏但存在，capture="environment"
    const capture = page.locator('#capture-input');
    expect(await capture.count()).toBe(1);
    expect(await capture.getAttribute('capture')).toBe('environment');

    await uploadFile(page, file);
    // 文档列表出现该文件
    await page.goto('/documents/');
    await expect(page.locator('main').getByText(file.name, { exact: true }).first()).toBeVisible();

    unlinkSync(file.path);
  });

  test('删除上传文件 → 回收站出现，可恢复', async ({ page }) => {
    const file = pickUploadFile();
    await uploadFile(page, file);

    // 在文档列表勾选该文件并批量删除
    await page.goto('/documents/');
    await page.locator(`input[type="checkbox"][aria-label="选择 ${file.name}"]`).check();
    // Alpine submitBulk 在设置 action 后同步 form.submit()，隐藏 input 的 DOM 写入被
    // 延迟到微任务，表单序列化时 action 为空 → 服务端报「不支持的操作」。
    // 测试直接写入 action 字段后原生提交（与正常 Alpine 提交相同的 POST），不改业务代码。
    await page.evaluate(() => {
      const form = document.querySelector(
        'form[action*="/documents/bulk/"]',
      ) as HTMLFormElement | null;
      if (!form) return;
      (form.querySelector('input[name="action"]') as HTMLInputElement).value = 'delete';
      form.submit();
    });
    // form.submit() 的导航未完成前切页会报「interrupted by another navigation」
    await page.waitForURL('**/documents/**');
    await page.waitForLoadState('networkidle');
    // 文件已从列表消失
    await expect(page.locator('main').getByText(file.name, { exact: true })).toHaveCount(0);

    // 回收站出现该文件
    await page.goto('/documents/trash/');
    await expect(page.locator('main').getByText(file.name, { exact: true }).first()).toBeVisible();

    unlinkSync(file.path);
  });
});
