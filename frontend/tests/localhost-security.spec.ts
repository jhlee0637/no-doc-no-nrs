import { expect, test } from '@playwright/test';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { request as httpRequest } from 'node:http';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const origin = 'http://127.0.0.1:5173';
const canary = 'NONSECRET-LOCAL-SECURITY-CANARY';
let outside = '';
let inside = '';

test.beforeAll(async () => {
  // Only synthetic files are requested; never request existing secrets or credentials.
  const privateRoot = join(frontendRoot, '..', 'etc', 'gui-prototype');
  await mkdir(privateRoot, { recursive: true });
  outside = await mkdtemp(join(privateRoot, 'ai-generated-security-'));
  inside = await mkdtemp(join(frontendRoot, 'dev', '.ai-generated-security-'));
  await mkdir(join(inside, '.git'));
  await mkdir(join(inside, 'etc'));
  await Promise.all([
    writeFile(join(outside, 'nonsecret-canary.txt'), canary),
    writeFile(join(inside, '.env'), canary),
    writeFile(join(inside, '.git', 'HEAD'), canary),
    writeFile(join(inside, 'etc', 'nonsecret-canary.txt'), canary),
    writeFile(join(inside, 'nonsecret.key'), canary),
    writeFile(join(inside, 'nonsecret.js.map'), canary),
  ]);
});

test.afterAll(async () => {
  await Promise.all([outside, inside].filter(Boolean).map(path => rm(path, { recursive: true, force: true })));
});

test('permits local navigation, same-origin HEAD and serves security headers', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.locator('#photo-input')).toBeAttached();
  const response = await request.head('/', { headers: { Origin: origin, 'Sec-Fetch-Site': 'same-origin' } });
  expect(response.status()).toBe(200);
  expect(await response.body()).toHaveLength(0);
  expect(response.headers()['x-content-type-options']).toBe('nosniff');
  expect(response.headers()['referrer-policy']).toBe('no-referrer');
  expect(response.headers()['x-frame-options']).toBe('DENY');
  expect(response.headers()['content-security-policy']).toContain("frame-ancestors 'none'");
  expect(response.headers()['access-control-allow-origin']).toBeUndefined();
  const localhost = await request.get('/', { headers: { Host: 'localhost:5173', Origin: 'http://localhost:5173' } });
  expect(localhost.status()).toBe(200);
});

test('rejects foreign origins before static, fixture and API proxy handlers', async ({ request }) => {
  for (const path of ['/', '/__prototype__/assets/correction.png', '/api/coach/config']) {
    for (const value of ['https://example.com', 'http://localhost:5174', 'null', 'http://localhost:5173']) {
      const response = await request.get(path, { headers: { Origin: value } });
      expect(response.status(), `${path}: ${value}`).toBe(403);
    }
  }
  const post = await request.post('/__prototype__/analyze', { headers: { Origin: 'https://example.com' }, data: 'not-a-form' });
  expect(post.status()).toBe(403);
  const site = await request.get('/api/coach/config', { headers: { 'Sec-Fetch-Site': 'cross-site' } });
  expect(site.status()).toBe(403);
});

test('rejects unknown hosts, alternate loopback hosts and wrong ports', async ({ request }) => {
  for (const host of ['example.com:5173', 'child.localhost:5173', '127.0.0.2:5173', 'localhost:5174', '127.0.0.1', 'localhost:5173,example.com:5173']) {
    const response = await request.get('/api/coach/config', { headers: { Host: host } });
    expect(response.status(), host).toBe(403);
  }
});

test('rejects duplicate Host headers instead of trusting the first one', async () => {
  const status = await new Promise<number>((resolveStatus, reject) => {
    const request = httpRequest(origin, { headers: ['Host', '127.0.0.1:5173', 'Host', 'localhost:5173'] }, response => {
      response.resume();
      response.on('end', () => resolveStatus(response.statusCode!));
    });
    request.on('error', reject);
    request.end();
  });
  expect([400, 403]).toContain(status);
});

test('blocks synthetic private files inside and outside the frontend root', async ({ request }) => {
  const files = [
    join(outside, 'nonsecret-canary.txt'), join(inside, '.env'), join(inside, '.git', 'HEAD'),
    join(inside, 'etc', 'nonsecret-canary.txt'), join(inside, 'nonsecret.key'), join(inside, 'nonsecret.js.map'),
  ];
  for (const file of files) {
    const response = await request.get(`/@fs/${file.replaceAll('\\', '/')}`);
    expect([403, 404], file).toContain(response.status());
    expect(await response.text()).not.toContain(canary);
  }
});

test('preserves the local HTTP fixture and Python API proxy', async ({ request }) => {
  const fixture = await request.get('/__prototype__/assets/correction.png', { headers: { Origin: origin } });
  expect(fixture.status()).toBe(200);
  expect(fixture.headers()['content-type']).toBe('image/png');
  const upload = await request.post('/__prototype__/analyze', {
    headers: { Origin: origin },
    multipart: {
      image: { name: 'nonsecret.png', mimeType: 'image/png', buffer: await readFile(join(frontendRoot, 'dev', 'ai-generated-http-fixture.png')) },
      request_id: 'localhost-security-fixture', schema_version: 'prototype-http-v1', exercise: 'chopsticks',
      handedness: 'right', reference_id: 'prototype-reference', reference_version: '0',
    },
  });
  expect(upload.status()).toBe(200);
  expect((await upload.json()).kind).toBe('feedback');
  const configured = await request.get('/api/coach/config', { headers: { Origin: origin } });
  expect(configured.status()).toBe(200);
  expect((await configured.json()).mode).toBe('mock');
});
