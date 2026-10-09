import { expect, test, type Page } from '@playwright/test';

async function syntheticPng(page: Page, width: number, height: number) {
  return Buffer.from(await page.evaluate(({ width, height }) => {
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext('2d')!;
    context.fillStyle = '#e0e8da'; context.fillRect(0, 0, width, height);
    context.strokeStyle = '#ce633c'; context.lineWidth = 10;
    context.beginPath(); context.moveTo(width / 3, height / 2);
    context.lineTo(width * 2 / 3, height / 3); context.stroke();
    return canvas.toDataURL('image/png').split(',')[1];
  }, { width, height }), 'base64');
}

async function feedback(page: Page, imageMode: 'valid' | 'failed' | 'wrong-size' = 'valid') {
  await page.goto('/');
  await page.locator('#demo-transport').selectOption('pipeline');
  const uploaded = await syntheticPng(page, 96, 64);
  const result = await syntheticPng(page, imageMode === 'wrong-size' ? 100 : 1200, 1600);
  await page.locator('#photo-input').setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: uploaded });
  await expect(page.locator('#show-result')).toBeEnabled();
  // Response-shape fixtures only; no image analysis or model calls.
  let config: { schema_version: string; exercise: string; handedness: string; reference: unknown };
  await page.route('**/api/coach/config', async route => {
    const response = await route.fetch();
    config = { ...await response.json(), mode: 'analysis' };
    await route.fulfill({ response, json: config });
  });
  await page.route('**/api/coach/analyze', async route => {
    const form = await new Response(route.request().postDataBuffer(), {
      headers: { 'content-type': route.request().headers()['content-type'] },
    }).formData();
    const body = { schema_version: config.schema_version, request_id: form.get('request_id'),
      exercise: config.exercise, handedness: config.handedness, reference: config.reference,
      source: 'analysis', outcome: 'feedback', retake: null, error: null,
      feedback: { status: 'assessable',
        comment: 'MIDDLE_FINGER_PIP를 0.5 cm 움직이세요. 손목은 움직이지 마세요.\n<img src=x onerror=alert(1)>는 텍스트입니다.',
        corrections: [
      { joint_name: 'MIDDLE_FINGER_PIP', instruction: '중지 가운데 관절(MIDDLE_FINGER_PIP)을 조금 굽히세요.' },
      { joint_name: 'THUMB_IP', instruction: '엄지 IP 관절을 구부리세요.' },
        ], image: { url: '/api/coach/assets/display-fixture.png', mime_type: 'image/png', width: 1200, height: 1600 } },
    };
    await route.fulfill({ status: 200, json: body });
  });
  await page.route('**/api/coach/assets/display-fixture.png', route => imageMode === 'failed'
    ? route.fulfill({ status: 404 }) : route.fulfill({ contentType: 'image/png', body: result }));
  await page.locator('#show-result').click();
  await expect(page.locator('#result-content')).toBeVisible();
  return uploaded;
}

test('shows Korean joint names and sentence bullets as safe text', async ({ page }) => {
  await feedback(page);
  const bullets = page.locator('#result-body ul li');
  await expect(bullets).toHaveCount(3);
  await expect(bullets.nth(0)).toContainText('중지 가운데 관절');
  await expect(bullets.nth(0)).toContainText('0.5 cm');
  await expect(bullets.nth(1)).toHaveText('손목은 움직이지 마세요.');
  await expect(bullets.nth(2)).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('#result-body img')).toHaveCount(0);
  await page.locator('#detail-summary').click();
  await expect(page.locator('#detail-list strong').nth(0)).toHaveText('중지 가운데 관절');
  await expect(page.locator('#detail-list')).not.toContainText('MIDDLE_FINGER_PIP');
  await expect(page.locator('#detail-list')).not.toContainText('THUMB_IP');
  await expect(page.locator('#detail-list')).not.toContainText(' IP ');
});

for (const width of [1280, 375]) {
  test(`portrait correction fills card and expands without cropping at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await feedback(page);
    const image = page.locator('#correction-image');
    await expect(image).toBeVisible();
    const size = (await image.boundingBox())!;
    expect(size.width).toBeGreaterThan(width === 375 ? 250 : 400);
    expect(size.height).toBeGreaterThan(width === 375 ? 300 : 500);
    expect(size.width / size.height).toBeCloseTo(0.75, 2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const open = page.locator('#enlarge-correction');
    await open.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.locator('#close-correction')).toBeFocused();
    await expect(page.locator('#enlarged-correction-image')).toBeVisible();
    const enlarged = (await page.locator('#enlarged-correction-image').boundingBox())!;
    expect(enlarged.width).toBeGreaterThan(size.width);
    expect(enlarged.width / enlarged.height).toBeCloseTo(0.75, 2);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(open).toBeFocused();
    await open.click();
    await page.locator('#close-correction').click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.locator('#enlarged-correction-image')).not.toHaveAttribute('src');
  });
}

test('photo replacement and clearing invalidate enlarged results', async ({ page }) => {
  const uploaded = await feedback(page);
  await expect(page.locator('#enlarge-correction')).toBeVisible();
  await page.locator('#enlarge-correction').click();
  await page.locator('#photo-input').setInputFiles({ name: 'replacement.png', mimeType: 'image/png', buffer: uploaded });
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.locator('#enlarged-correction-image')).not.toHaveAttribute('src');
  await expect(page.locator('#enlarge-correction')).toBeHidden();
  await page.locator('#show-result').click();
  await expect(page.locator('#enlarge-correction')).toBeVisible();
  await page.locator('#enlarge-correction').click();
  await page.locator('#close-correction').click();
  await page.locator('#clear-photo').click();
  await expect(page.locator('#enlarge-correction')).toBeHidden();
  await expect(page.locator('#correction-image')).toBeHidden();
});

for (const mode of ['failed', 'wrong-size'] as const) {
  test(`cannot enlarge a ${mode} result image`, async ({ page }) => {
    await feedback(page, mode);
    await expect(page.locator('#result-image-status')).toContainText(mode === 'failed' ? '불러오지 못했습니다' : '응답과 다릅니다');
    await expect(page.locator('#correction-image')).toBeHidden();
    await expect(page.locator('#enlarge-correction')).toBeHidden();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.locator('#result-body ul li')).toHaveCount(3);
  });
}
