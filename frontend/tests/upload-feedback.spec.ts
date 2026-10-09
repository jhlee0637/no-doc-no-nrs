import { expect, test, type Locator, type Page } from '@playwright/test';

async function image(page: Page) {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 96; canvas.height = 64;
    canvas.getContext('2d')!.fillRect(0, 0, 96, 64);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name: 'selected-photo.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

async function inViewport(element: Locator, page: Page) {
  const bounds = await element.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.y).toBeGreaterThanOrEqual(-1);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
}

for (const viewport of [{ width: 1280, height: 720 }, { width: 375, height: 812 }]) {
  test(`photo selection gives visible feedback and a next action at ${viewport.width}px without uploading`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    const calls: string[] = [];
    page.on('request', request => {
      if (request.url().includes('/api/coach/') || request.url().includes('/__prototype__/')) calls.push(request.url());
    });
    for (const transport of ['browser', 'http', 'pipeline']) {
      await page.locator('#demo-transport').selectOption(transport);
      const file = await image(page);
      const selected = page.waitForEvent('filechooser');
      await page.locator('#replace-photo').click();
      await (await selected).setFiles(file);
      const status = page.locator('#status-message');
      await expect(status).toHaveAttribute('data-state', 'success');
      await expect(status).toContainText('사진을 선택했습니다.');
      await expect(status).toContainText(transport === 'pipeline' ? '로컬 API 결과 보기' : '모의 결과 보기');
      await expect(status).toContainText(transport === 'browser' ? '서버로 전송하지 않습니다' : transport === 'http' ? 'localhost 모의 서버로 전송' : '로컬 서버로 전송');
      await expect(page.locator('#preview-image')).toBeVisible();
      await expect(page.locator('#show-result')).toBeEnabled();
      await inViewport(page.locator('#preview-image'), page);
      await inViewport(status, page);
      await inViewport(page.locator('#show-result'), page);
      await expect(page.locator('#result-content')).toBeHidden();
    }
    expect(calls).toEqual([]);
  });

  test(`an invalid replacement gives a visible error and clears the old preview at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.locator('#photo-input').setInputFiles(await image(page));
    await expect(page.locator('#preview-image')).toBeVisible();
    const selected = page.waitForEvent('filechooser');
    await page.locator('#replace-photo').click();
    await (await selected).setFiles({
      name: 'broken.png', mimeType: 'image/png',
      buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]),
    });
    const status = page.locator('#status-message');
    await expect(status).toHaveAttribute('data-state', 'error');
    await expect(status).toHaveClass(/\berror\b/);
    await expect(status).toContainText('사진을 열 수 없습니다.');
    await inViewport(status, page);
    await inViewport(page.locator('#show-result'), page);
    await expect(page.locator('#preview-image')).toBeHidden();
    await expect(page.locator('#photo-meta')).toBeHidden();
    await expect(page.locator('#show-result')).toBeDisabled();
    await expect(page.locator('#result-content')).toBeHidden();
  });
}
