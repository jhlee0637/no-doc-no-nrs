import { expect, test, type Page } from '@playwright/test';

async function picture(page: Page) {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 96; canvas.height = 64;
    canvas.getContext('2d')!.fillRect(0, 0, 96, 64);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name: 'my-photo.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

async function guideImages(page: Page) {
  const guide = page.locator('#photo-guide');
  await expect(guide.getByRole('heading', { name: '사진을 이렇게 찍어 주세요' })).toBeVisible();
  await expect(guide).toContainText('현재 모습의 사진 한 장을 올려 주세요.');
  await expect(guide.getByText('젓가락을 벌린 모습', { exact: true })).toBeVisible();
  await expect(guide.getByText('젓가락을 모은 모습', { exact: true })).toBeVisible();
  for (const id of ['guide-hold-open', 'guide-hold-closed']) {
    const image = page.locator(`#${id}`);
    await expect(image).toBeVisible();
    await image.evaluate((element: HTMLImageElement) => element.decode());
    expect(await image.evaluate((element: HTMLImageElement) => [element.naturalWidth, element.naturalHeight])).toEqual([1254, 1254]);
    const source = new URL(await image.getAttribute('src') ?? '', page.url());
    expect(source.origin).toBe(new URL(page.url()).origin);
    expect(source.pathname).not.toContain('/etc/');
    const bounds = await image.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.width).toBeGreaterThan(100);
    expect(bounds!.height).toBeGreaterThan(100);
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 375, height: 812 }]) {
  test(`capture examples decode at ${viewport.width}px and keep the original photo picker`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await guideImages(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    let chooserCount = 0;
    page.on('filechooser', () => { chooserCount++; });
    await page.locator('#guide-hold-open').click();
    await page.locator('#guide-hold-closed').click();
    expect(chooserCount).toBe(0);
    await expect(page.locator('#preview-image')).toBeHidden();
    await expect(page.locator('#show-result')).toBeDisabled();
    const file = await picture(page);
    const chosen = page.waitForEvent('filechooser');
    await page.locator('#replace-photo').click();
    await (await chosen).setFiles(file);
    await expect(page.locator('#file-name')).toHaveText(file.name);
    await expect(page.locator('#preview-image')).toBeVisible();
    await page.locator('#show-result').click();
    await expect(page.locator('#feedback-title')).toHaveText('교정 안내 화면 예시');
    await expect(page.locator('#photo-guide')).toBeVisible();
    await page.locator('#clear-photo').click();
    await expect(page.locator('#result-content')).toBeHidden();
    await expect(page.locator('#show-result')).toBeDisabled();
    await guideImages(page);
  });
}

test('capture examples remain separate from the pipeline upload and retake result', async ({ page }) => {
  const config = {
    schema_version: 'local-coach-v1', mode: 'mock', exercise: 'basic_grip', handedness: 'right',
    reference: { id: 'photo-guide-mock', version: '0' }, deadline_seconds: 180, asset_ttl_seconds: 600,
  };
  // Shape-only mock response avoids invoking a model or contending for the backend slot.
  await page.route('**/api/coach/config', route => route.fulfill({ json: config }));
  await page.route('**/api/coach/analyze', async route => {
    const request = route.request();
    expect(request.method()).toBe('POST');
    expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=');
    const requestId = /name="request_id"\r\n\r\n([^\r\n]+)/.exec(request.postData() ?? '')?.[1];
    expect(requestId).toBeTruthy();
    await route.fulfill({ json: {
      schema_version: config.schema_version, request_id: requestId, exercise: config.exercise,
      handedness: config.handedness, reference: config.reference, source: 'mock', outcome: 'retake',
      feedback: null, retake: { reason: 'no_hand_detected', message: '손과 젓가락을 함께 촬영해 주세요.' }, error: null,
    } });
  });
  await page.goto('/');
  await page.locator('#demo-transport').selectOption('pipeline');
  await page.locator('#photo-input').setInputFiles(await picture(page));
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await expect(page.locator('#feedback-title')).toContainText('재촬영');
  await expect(page.locator('#result-body')).toContainText('손과 젓가락을 함께 촬영');
  await expect(page.locator('#file-name')).toHaveText('my-photo.png');
  await expect(page.locator('#correction-image')).toBeHidden();
  await guideImages(page);
});
