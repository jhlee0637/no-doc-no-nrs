import { expect, test, type Page } from '@playwright/test';

async function picture(page: Page, name = 'hand.png') {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    const context = canvas.getContext('2d')!;
    context.fillStyle = '#e8ecdf';
    context.fillRect(0, 0, 640, 480);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name, mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('real file preview, explicit mock result, details and no server upload', async ({ page }) => {
  const uploads: string[] = [];
  page.on('request', request => {
    if (request.method() !== 'GET' && request.method() !== 'HEAD') uploads.push(request.url());
  });
  await expect(page.locator('#show-result')).toBeDisabled();
  await page.locator('#photo-input').setInputFiles(await picture(page));
  await expect(page.locator('#file-name')).toHaveText('hand.png');
  await expect(page.locator('#file-details')).toContainText('640 × 480');
  await expect(page.locator('#preview-image')).toBeVisible();
  await page.locator('#show-result').click();
  await expect(page.locator('#feedback-title')).toHaveText('교정 안내 화면 예시');
  await expect(page.locator('#result-image-placeholder')).toContainText('교정 이미지 제공 대기');
  await page.locator('#feedback-details summary').click();
  await expect(page.locator('#detail-list')).toBeVisible();
  await expect(page.getByText('화면 검증용 모의 응답 · 서버 전송 없음')).toBeVisible();
  expect(uploads).toEqual([]);
});

test('rejects corrupt images and does not retain an earlier result', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await picture(page));
  await page.locator('#show-result').click();
  await expect(page.locator('#result-content')).toBeVisible();
  await page.locator('#photo-input').setInputFiles({
    name: 'broken.png', mimeType: 'image/png',
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]),
  });
  await expect(page.locator('#status-message')).toContainText('사진을 열 수 없습니다');
  await expect(page.locator('#show-result')).toBeDisabled();
  await expect(page.locator('#preview-image')).toBeHidden();
  await expect(page.locator('#result-content')).toBeHidden();
});

test('cancellation prevents a delayed result and permits retry', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await picture(page));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await page.locator('#cancel-request').click();
  await expect(page.locator('#status-message')).toContainText('취소');
  await page.waitForTimeout(1100);
  await expect(page.locator('#result-content')).toBeHidden();
  await page.locator('#show-result').click();
  await expect(page.locator('#result-content')).toBeVisible();
});

test('replacing a photo invalidates its pending request', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await picture(page, 'first.png'));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await page.locator('#photo-input').setInputFiles(await picture(page, 'second.png'));
  await expect(page.locator('#file-name')).toHaveText('second.png');
  await page.waitForTimeout(1100);
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
});

test('out-of-order image decoding preserves the latest choice', async ({ page }) => {
  await page.evaluate(() => {
    const original = HTMLImageElement.prototype.decode;
    let count = 0;
    HTMLImageElement.prototype.decode = async function () {
      const current = ++count;
      document.documentElement.dataset.decodeCalls = String(current);
      await original.call(this);
      if (current === 1) await new Promise(resolve => setTimeout(resolve, 350));
    };
  });
  const first = await picture(page, 'first.png');
  const second = await picture(page, 'latest.png');
  await page.locator('#photo-input').setInputFiles(first);
  await expect(page.locator('html')).toHaveAttribute('data-decode-calls', '1');
  await page.locator('#photo-input').setInputFiles(second);
  await expect(page.locator('#file-name')).toHaveText('latest.png');
  await page.waitForTimeout(400);
  await expect(page.locator('#file-name')).toHaveText('latest.png');
});

test('same file can be reselected and clearing releases owned URLs', async ({ page }) => {
  await page.evaluate(() => {
    const live = new Set<string>();
    const create = URL.createObjectURL;
    const revoke = URL.revokeObjectURL;
    URL.createObjectURL = value => {
      const url = create(value);
      live.add(url);
      document.documentElement.dataset.liveUrls = String(live.size);
      return url;
    };
    URL.revokeObjectURL = url => {
      revoke(url);
      live.delete(url);
      document.documentElement.dataset.liveUrls = String(live.size);
    };
  });
  const file = await picture(page);
  await page.locator('#photo-input').setInputFiles(file);
  await expect(page.locator('#file-name')).toHaveText('hand.png');
  await expect(page.locator('html')).toHaveAttribute('data-live-urls', '1');
  await page.locator('#photo-input').setInputFiles(file);
  await expect(page.locator('#file-name')).toHaveText('hand.png');
  await expect(page.locator('html')).toHaveAttribute('data-live-urls', '1');
  await page.locator('#clear-photo').click();
  await expect(page.locator('html')).toHaveAttribute('data-live-urls', '0');
  await expect(page.locator('#show-result')).toBeDisabled();
});

test('retake and service-error examples are separate selectable states', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await picture(page));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#demo-scenario').selectOption('retake');
  await page.locator('#show-result').click();
  await expect(page.locator('#feedback-title')).toHaveText('재촬영 안내 화면 예시');
  await expect(page.locator('#result-image-placeholder')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#demo-scenario').selectOption('error');
  await page.locator('#show-result').click();
  await expect(page.locator('#feedback-title')).toHaveText('오류 안내 화면 예시');
  await expect(page.locator('#feedback-details')).toBeHidden();
});

test('mobile layout fits and photo picker supports the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('#drop-zone')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.locator('#drop-zone').focus();
  const chooser = page.waitForEvent('filechooser');
  await page.keyboard.press('Enter');
  await (await chooser).setFiles(await picture(page));
  await expect(page.locator('#file-name')).toHaveText('hand.png');
});
