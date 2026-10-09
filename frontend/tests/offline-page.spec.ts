import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const artifact = fileURLToPath(new URL('../../etc/offline-demo/ai-generated-chopcoach-offline.html', import.meta.url));
const offlineURL = pathToFileURL(artifact).href;
const audits = new WeakMap<Page, { requests: string[]; errors: string[] }>();

async function picture(page: Page) {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 96; canvas.height = 64;
    canvas.getContext('2d')!.fillRect(0, 0, 96, 64);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name: 'offline-photo.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

async function selectPhoto(page: Page) {
  const file = await picture(page);
  const chosen = page.waitForEvent('filechooser');
  await page.locator('#replace-photo').click();
  await (await chosen).setFiles(file);
  await expect(page.locator('#status-message')).toHaveAttribute('data-state', 'success');
  await expect(page.locator('#preview-image')).toBeVisible();
  await expect(page.locator('#file-name')).toHaveText(file.name);
  await expect(page.locator('#show-result')).toBeEnabled();
}

test.beforeEach(async ({ page, context }) => {
  await context.setOffline(true);
  const audit = { requests: [] as string[], errors: [] as string[] };
  audits.set(page, audit);
  page.on('request', request => { if (/^https?:/.test(request.url())) audit.requests.push(request.url()); });
  page.on('pageerror', error => audit.errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && /Content Security Policy|Refused to|violates/i.test(message.text())) audit.errors.push(message.text());
  });
  await page.addInitScript(() => {
    Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: undefined });
    const original = crypto.getRandomValues.bind(crypto);
    let calls = 0;
    Object.defineProperty(crypto, 'getRandomValues', { configurable: true, value: (array: Uint8Array) => {
      document.documentElement.dataset.randomFallbackCalls = String(++calls);
      return original(array);
    } });
  });
  await page.goto(offlineURL);
});

test.afterEach(async ({ page }) => {
  expect(audits.get(page)!.requests).toEqual([]);
  expect(audits.get(page)!.errors).toEqual([]);
});

test('standalone file shows the offline mode and embedded guide images at phone width', async ({ page }) => {
  await expect(page.locator('.local-pill')).toHaveText('OFFLINE DEMO');
  await expect(page.locator('#transport-notice')).toHaveText('오프라인 화면 예시 · 사진 전송 없음');
  await expect(page.locator('#transport-control')).toBeHidden();
  await expect(page.locator('#demo-transport option')).toHaveCount(1);
  await expect(page.locator('#demo-transport')).toHaveValue('browser');
  await expect(page.locator('.footer')).toContainText('실제 사진 분석 없음');
  for (const id of ['guide-hold-open', 'guide-hold-closed']) {
    const image = page.locator(`#${id}`);
    await expect(image).toBeVisible();
    expect(await image.getAttribute('src')).toMatch(/^data:image\/png;base64,/);
    await image.evaluate((element: HTMLImageElement) => element.decode());
    expect(await image.evaluate((element: HTMLImageElement) => [element.naturalWidth, element.naturalHeight])).toEqual([1254, 1254]);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('photo picker and manual mock feedback work without randomUUID or network access', async ({ page }) => {
  expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe('undefined');
  await selectPhoto(page);
  await expect(page.locator('#status-message')).toContainText('서버로 전송하지 않습니다');
  await expect(page.locator('#result-content')).toBeHidden();
  // Even a forged transport option must not activate an API in the offline build.
  await page.evaluate(() => {
    const select = document.querySelector<HTMLSelectElement>('#demo-transport')!;
    select.append(new Option('forged pipeline', 'pipeline'));
    select.value = 'pipeline';
  });
  await page.locator('#show-result').click();
  await expect(page.locator('#feedback-title')).toHaveText('교정 안내 화면 예시');
  await expect(page.locator('#result-notice')).toContainText('선택한 사진을 분석한 결과가 아닌');
  await expect(page.locator('#result-image-placeholder')).toContainText('실제 교정 이미지를 생성하지 않습니다');
  expect(await page.locator('html').getAttribute('data-random-fallback-calls')).toBe('1');
});

test('retake and error examples remain explicit mock states', async ({ page }) => {
  await selectPhoto(page);
  for (const [scenario, title] of [['retake', '재촬영 안내 화면 예시'], ['error', '오류 안내 화면 예시']]) {
    await page.locator('#demo-scenario').selectOption(scenario);
    await page.locator('#show-result').click();
    await expect(page.locator('#feedback-title')).toHaveText(title);
    await expect(page.locator('#outcome-badge')).toHaveText('모의 응답');
    await expect(page.locator('#correction-image')).toBeHidden();
    await expect(page.locator('#show-result')).toBeEnabled();
  }
});

test('cancel and clear stop pending mock results and release the photo preview', async ({ page }) => {
  await selectPhoto(page);
  await page.clock.install();
  await page.locator('#show-result').click();
  await page.locator('#cancel-request').click();
  await page.clock.fastForward(1000);
  await expect(page.locator('#status-message')).toContainText('취소');
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await page.locator('#clear-photo').click();
  await page.clock.fastForward(1000);
  await expect(page.locator('#preview-image')).toBeHidden();
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeDisabled();
  await expect(page.locator('#clear-photo')).toBeDisabled();
});

test('missing browser crypto is a handled error and does not leave controls stuck', async ({ page }) => {
  await selectPhoto(page);
  await page.evaluate(() => Object.defineProperty(window, 'crypto', { configurable: true, value: undefined }));
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toHaveAttribute('data-state', 'error');
  await expect(page.locator('#status-message')).toContainText('모의 화면을 표시하지 못했습니다');
  await expect(page.locator('#show-result')).toBeEnabled();
  await expect(page.locator('#cancel-request')).toBeHidden();
  await expect(page.locator('#result-content')).toBeHidden();
});
