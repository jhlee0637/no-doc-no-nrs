import { expect, test, type Page } from '@playwright/test';

// Independent Python mock API has a single analysis slot.
test.describe.configure({ mode: 'serial' });

async function photo(page: Page, name = 'local-upload.png') {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 96; canvas.height = 64;
    canvas.getContext('2d')!.fillRect(0, 0, 96, 64);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  return { name, mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64') };
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.locator('#demo-transport').selectOption('pipeline');
  await page.locator('#photo-input').setInputFiles(await photo(page));
  await expect(page.locator('#show-result')).toBeEnabled();
});

test('uses independent local API configuration, uploads multipart and displays a mock PNG', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/coach/')) calls.push(`${request.method()} ${new URL(request.url()).pathname}`); });
  const configured = page.waitForResponse('**/api/coach/config');
  const uploaded = page.waitForRequest('**/api/coach/analyze');
  const result = page.waitForResponse('**/api/coach/analyze');
  await page.locator('#show-result').click();
  const config = await (await configured).json();
  const request = await uploaded;
  expect(request.method()).toBe('POST');
  expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=');
  expect(request.headers()['x-local-coach-scenario']).toBe('feedback');
  const body = await (await result).json();
  expect(body.reference).toEqual(config.reference);
  expect(body.exercise).toBe(config.exercise);
  expect(body.handedness).toBe(config.handedness);
  expect(body.source).toBe('mock');
  expect(calls.slice(0, 2)).toEqual(['GET /api/coach/config', 'POST /api/coach/analyze']);
  await expect(page.locator('#correction-image')).toBeVisible();
  expect(await page.locator('#correction-image').evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([body.feedback.image.width, body.feedback.image.height]);
  await expect(page.locator('#outcome-badge')).toContainText('모의 응답');
  await expect(page.locator('#transport-notice')).toContainText('실제 분석 없음');
});

test('rejects a decodable image over 5 MiB before any local API request', async ({ page }) => {
  const file = await photo(page, 'oversized.png');
  const buffer = Buffer.alloc(5 * 1024 * 1024 + 1);
  file.buffer.copy(buffer);
  const requests: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/coach/')) requests.push(request.url()); });
  await page.locator('#photo-input').setInputFiles({ ...file, buffer });
  await expect(page.locator('#preview-image')).toBeVisible();
  await expect(page.locator('#show-result')).toBeEnabled();
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toContainText('5 MiB 이하');
  await expect(page.locator('#result-content')).toBeHidden();
  await expect(page.locator('#show-result')).toBeEnabled();
  await expect(page.locator('#clear-photo')).toBeEnabled();
  expect(requests).toEqual([]);
});

test('renders local API retake and HTTP error envelopes without stale images', async ({ page }) => {
  for (const scenario of ['retake', 'error']) {
    await expect(page.locator('#demo-scenario')).toBeEnabled();
    await page.locator('#demo-scenario').selectOption(scenario);
    const response = page.waitForResponse('**/api/coach/analyze');
    await page.locator('#show-result').click();
    expect((await response).status()).toBe(scenario === 'retake' ? 200 : 503);
    await expect(page.locator('#feedback-title')).toContainText(scenario === 'retake' ? '재촬영' : '오류');
    await expect(page.locator('#correction-image')).toBeHidden();
    await expect(page.locator('#show-result')).toBeEnabled();
  }
});

test('cancel and replace discard late local API responses', async ({ page }) => {
  await page.route('**/api/coach/analyze', async route => {
    const response = await route.fetch();
    await new Promise(resolve => setTimeout(resolve, 500));
    await route.fulfill({ response }).catch(() => {});
  });
  const sent = page.waitForRequest('**/api/coach/analyze');
  await page.locator('#show-result').click();
  await sent;
  await page.locator('#cancel-request').click();
  await expect(page.locator('#status-message')).toContainText('즉시 종료되지');
  await page.waitForTimeout(650);
  await expect(page.locator('#result-content')).toBeHidden();
  const second = page.waitForRequest('**/api/coach/analyze');
  await page.locator('#show-result').click();
  await second;
  await page.locator('#photo-input').setInputFiles(await photo(page, 'replacement.png'));
  await expect(page.locator('#file-name')).toHaveText('replacement.png');
  await page.waitForTimeout(650);
  await expect(page.locator('#result-content')).toBeHidden();
});

for (const mutation of ['request-id', 'reference', 'source', 'exclusive-outcome', 'external-image', 'http-status']) {
  test(`rejects local API ${mutation} mismatch`, async ({ page }) => {
    await page.route('**/api/coach/analyze', async route => {
      const response = await route.fetch();
      const body = await response.json();
      if (mutation === 'request-id') body.request_id = 'unrelated';
      if (mutation === 'reference') body.reference.version = 'unrelated';
      if (mutation === 'source') body.source = 'analysis';
      if (mutation === 'exclusive-outcome') body.retake = { reason: 'wrong', message: 'wrong' };
      if (mutation === 'external-image') body.feedback.image.url = 'https://example.com/api/coach/assets/foreign.png';
      await route.fulfill({ response, json: body, status: mutation === 'http-status' ? 503 : response.status() });
    });
    await page.locator('#show-result').click();
    await expect(page.locator('#status-message')).toContainText('올바르지');
    await expect(page.locator('#result-content')).toBeHidden();
    await expect(page.locator('#show-result')).toBeEnabled();
  });
}

test('analysis variant shows uncertainty and ignores mock scenario selection', async ({ page }) => {
  // Shape-only stubs; no real model or analysis API is called.
  await page.route('**/api/coach/config', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), mode: 'analysis' } });
  });
  await page.route('**/api/coach/analyze', async route => {
    expect(route.request().headers()['x-local-coach-scenario']).toBeUndefined();
    const response = await route.fetch();
    const body = await response.json();
    body.source = 'analysis';
    body.feedback.status = 'uncertain';
    body.feedback.corrections = [];
    await route.fulfill({ response, json: body });
  });
  await page.locator('#demo-scenario').selectOption('error');
  await page.locator('#show-result').click();
  await expect(page.locator('#outcome-badge')).toContainText('사진 분석 안내 · 판단 불확실');
  await expect(page.locator('#result-notice')).toContainText('판단하기 어려운');
  await expect(page.locator('#demo-scenario')).toBeDisabled();
  await expect(page.locator('#result-body')).not.toContainText('올바른 자세');
});

test('preparation retake is distinct from mock and analysis feedback', async ({ page }) => {
  await page.route('**/api/coach/config', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), mode: 'analysis' } });
  });
  await page.route('**/api/coach/analyze', async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, source: 'preparation', outcome: 'retake', feedback: null,
      retake: { reason: 'no_hand_detected', message: '손이 잘 보이도록 다시 촬영해 주세요.' }, error: null } });
  });
  await page.locator('#show-result').click();
  await expect(page.locator('#outcome-badge')).toHaveText('전처리 안내');
  await expect(page.locator('#result-notice')).toContainText('손 검출 단계');
  await expect(page.locator('#correction-image')).toBeHidden();
});

test('an analysis service error is shown as a failed request rather than successful coaching', async ({ page }) => {
  await page.route('**/api/coach/config', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), mode: 'analysis' } });
  });
  await page.route('**/api/coach/analyze', async route => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, status: 502, json: { ...body, source: 'analysis', outcome: 'error', feedback: null,
      retake: null, error: { code: 'pipeline_failed', message: '분석을 완료하지 못했습니다. 다시 시도해 주세요.' } } });
  });
  await page.locator('#show-result').click();
  await expect(page.locator('#outcome-badge')).toHaveText('요청 오류');
  await expect(page.locator('#result-notice')).toContainText('완료하지 못했습니다');
  await expect(page.locator('#result-notice')).not.toContainText('기준사진과 비교한');
  await expect(page.locator('#correction-image')).toBeHidden();
  await expect(page.locator('#feedback-details')).toBeHidden();
});

test('handles a non-JSON service failure safely and retains retry controls', async ({ page }) => {
  await page.route('**/api/coach/analyze', route => route.fulfill({ status: 503, contentType: 'text/html', body: '<h1>private provider failure</h1>' }));
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toContainText('올바르지');
  await expect(page.locator('#status-message')).not.toContainText('private provider');
  await expect(page.locator('#show-result')).toBeEnabled();
});

test('times out the whole client wait and distinguishes it from server cancellation', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/coach/config', async route => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response }).catch(() => {});
  });
  await page.clock.install();
  await page.locator('#show-result').click();
  await expect(page.locator('#status-message')).toContainText('연결 모드를 확인');
  await page.clock.fastForward(195_000);
  await expect(page.locator('#status-message')).toContainText('대기 시간이 초과');
  await expect(page.locator('#status-message')).toContainText('즉시 종료되지');
  await expect(page.locator('#show-result')).toBeEnabled();
  release();
  await expect(page.locator('#result-content')).toBeHidden();
});
