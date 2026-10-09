import { expect, test, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';

async function uploadFixture(page: Page, name = 'upload.png') {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 480;
    canvas.getContext('2d')!.fillRect(0, 0, 640, 480);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name, mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.locator('#demo-transport').selectOption('http');
});

test('sends real multipart bytes to localhost and fetches a separate synthetic PNG', async ({ page }) => {
  const file = await uploadFixture(page);
  await page.locator('#photo-input').setInputFiles(file);
  await expect(page.locator('#show-result')).toBeEnabled();
  const uploaded = page.waitForResponse(response => response.url().endsWith('/__prototype__/analyze') && response.request().method() === 'POST');
  const asset = page.waitForResponse(response => response.url().endsWith('/__prototype__/assets/correction.png'));
  await page.locator('#show-result').click();
  const response = await uploaded;
  expect(response.status()).toBe(200);
  const { receipt, requestId } = await response.json();
  expect(receipt.fields.sort()).toEqual(['image', 'schema_version', 'request_id', 'exercise', 'handedness', 'reference_id', 'reference_version'].sort());
  expect(receipt.imageName).toBe('upload.png');
  expect(receipt.imageBytes).toBe(file.buffer.length);
  expect(receipt.imageSha256).toBe(createHash('sha256').update(file.buffer).digest('hex'));
  expect(receipt.schemaVersion).toBe('prototype-http-v1');
  expect(requestId).toMatch(/^[a-f0-9-]{36}$/);
  const result = await asset;
  expect(result.status()).toBe(200);
  expect(result.headers()['content-type']).toBe('image/png');
  await expect(page.locator('#correction-image')).toBeVisible();
  expect(await page.locator('#correction-image').evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([32, 24]);
  await expect(page.locator('#transport-notice')).toContainText('실제 분석 없음');
  await expect(page.locator('#result-body')).toContainText('모의 응답');
});

test('cancels an HTTP request without showing a late result and permits retry', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await page.locator('#cancel-request').click();
  await page.waitForTimeout(400);
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#correction-image')).toBeHidden();
  await page.locator('#show-result').click();
  await expect(page.locator('#correction-image')).toBeVisible();
});

test('changing the photo during upload discards the old HTTP result', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page, 'first.png'));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page, 'second.png'));
  await expect(page.locator('#file-name')).toHaveText('second.png');
  await page.waitForTimeout(400);
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#correction-image')).toBeHidden();
});

test('rejects a response belonging to another request', async ({ page }) => {
  await page.route('**/__prototype__/analyze', async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, requestId: 'another-request' } });
  });
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toContainText('올바르지');
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
});

test('reports an unavailable result image while retaining the mock explanation', async ({ page }) => {
  await page.route('**/__prototype__/assets/correction.png', route => route.fulfill({ status: 404, body: '' }));
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
  await page.locator('#show-result').click();
  await expect(page.locator('#result-content')).toBeVisible();
  await expect(page.locator('#result-image-status')).toContainText('못');
  await expect(page.locator('#correction-image')).toBeHidden();
});

test('HTTP failure leaves a retryable screen', async ({ page }) => {
  await page.route('**/__prototype__/analyze', route => route.fulfill({ status: 503, body: 'unavailable' }));
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toContainText('HTTP 503');
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.unroute('**/__prototype__/analyze');
  await page.locator('#show-result').click();
  await expect(page.locator('#correction-image')).toBeVisible();
});

for (const invalid of ['analysis-source', 'external-image']) {
  test(`rejects ${invalid} in the HTTP mock response`, async ({ page }) => {
    await page.route('**/__prototype__/analyze', async route => {
      const response = await route.fetch();
      const body = await response.json();
      const changed = invalid === 'analysis-source'
        ? { ...body, source: 'analysis' }
        : { ...body, correctionImage: { ...body.correctionImage, url: 'https://example.com/__prototype__/assets/image.png' } };
      await route.fulfill({ response, json: changed });
    });
    await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
    await page.locator('#show-result').click();
    await expect(page.locator('#status-message')).toContainText('올바르지');
    await expect(page.locator('#result-content')).toBeHidden();
  });
}

test('HTTP retake and error outcomes do not show a stale correction image', async ({ page }) => {
  await page.locator('#photo-input').setInputFiles(await uploadFixture(page));
  await page.locator('#show-result').click();
  await expect(page.locator('#correction-image')).toBeVisible();
  for (const scenario of ['retake', 'error']) {
    await expect(page.locator('#show-result')).toBeEnabled();
    await page.locator('#demo-scenario').selectOption(scenario);
    await page.locator('#show-result').click();
    await expect(page.locator('#feedback-title')).toHaveText(scenario === 'retake' ? '재촬영 안내 화면 예시' : '오류 안내 화면 예시');
    await expect(page.locator('#correction-image')).toBeHidden();
  }
});

test('mock HTTP server rejects repeated metadata fields', async ({ page }) => {
  const file = await uploadFixture(page);
  const result = await page.evaluate(async ({ base64 }) => {
    const bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0));
    const data = new FormData();
    data.set('image', new File([bytes], 'test.png', { type: 'image/png' }));
    for (const [key, value] of Object.entries({ schema_version: 'prototype-http-v1', request_id: 'test-id', exercise: 'chopsticks', handedness: 'right', reference_id: 'prototype-reference', reference_version: '0' })) data.set(key, value);
    data.append('request_id', 'second-id');
    return (await fetch('/__prototype__/analyze', { method: 'POST', body: data })).status;
  }, { base64: file.buffer.toString('base64') });
  expect(result).toBe(400);
});
