import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

// Development-only transport fixture. No analysis, reference lookup, or disk upload storage.
const endpoint = '/__prototype__/analyze';
const assetPath = '/__prototype__/assets/correction.png';
const maxBodyBytes = 6 * 1024 * 1024; // Fixture cap, not the agreed API limit.
const metadata = {
  schema_version: 'prototype-http-v1',
  exercise: 'chopsticks',
  handedness: 'right',
  reference_id: 'prototype-reference',
  reference_version: '0',
};

function json(response, code, body) {
  response.statusCode = code;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  response.end(JSON.stringify(body));
}

async function analyze(request, response) {
  let bytes = 0;
  const chunks = [];
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > maxBodyBytes) {
      json(response, 413, { message: '모의 서버의 테스트용 업로드 한도를 초과했습니다.' });
      return;
    }
    chunks.push(chunk);
  }
  const form = await new Request('http://localhost' + endpoint, {
    method: 'POST',
    headers: { 'content-type': request.headers['content-type'] ?? '' },
    body: Buffer.concat(chunks),
  }).formData();
  const expected = ['image', 'request_id', ...Object.keys(metadata)];
  const keys = [...form.keys()];
  if (keys.length !== expected.length || expected.some(key => form.getAll(key).length !== 1) || keys.some(key => !expected.includes(key))) {
    json(response, 400, { message: '모의 서버는 이미지 1개와 메타데이터 6개만 받습니다.' });
    return;
  }
  const file = form.get('image');
  const id = form.get('request_id');
  if (!(file instanceof File) || !file.size || typeof id !== 'string' || !id.trim() || Object.entries(metadata).some(([key, value]) => form.get(key) !== value)) {
    json(response, 400, { message: '모의 서버용 입력 필드가 올바르지 않습니다.' });
    return;
  }
  const header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const jpeg = header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff;
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((value, index) => header[index] === value);
  if (!jpeg && !png) {
    json(response, 400, { message: '모의 서버용 JPEG 또는 PNG 파일이 필요합니다.' });
    return;
  }
  const scenario = request.headers['x-prototype-scenario'] ?? 'feedback';
  if (!['feedback', 'retake', 'error'].includes(scenario)) {
    json(response, 400, { message: '알 수 없는 모의 화면입니다.' });
    return;
  }
  await new Promise(resolve => setTimeout(resolve, 150));
  if (response.destroyed) return;
  // Verification receipt is fixture-only, never part of the shared API contract.
  const receipt = {
    fields: keys,
    imageName: file.name,
    imageBytes: file.size,
    imageSha256: createHash('sha256').update(Buffer.from(await file.arrayBuffer())).digest('hex'),
    schemaVersion: form.get('schema_version'),
  };
  const common = { requestId: id, source: 'mock', receipt };
  if (scenario === 'feedback') {
    json(response, 200, {
      ...common, kind: 'feedback', title: '교정 안내 화면 예시',
      summary: 'HTTP 업로드와 결과 이미지 표시를 확인하기 위한 모의 응답입니다.',
      details: [{ label: '테스트 이미지 안내', text: '색상 패턴은 합성 fixture이며 선택한 손 사진의 교정 결과가 아닙니다.' }],
      correctionImage: { kind: 'provided', url: assetPath, mimeType: 'image/png', width: 32, height: 24 },
    });
  } else {
    json(response, 200, {
      ...common, kind: scenario,
      title: scenario === 'retake' ? '재촬영 안내 화면 예시' : '오류 안내 화면 예시',
      message: 'localhost 모의 서버의 화면 예시입니다. 실제 분석이나 서버 장애 판단이 아닙니다.',
    });
  }
}

export function prototypeServer() {
  return {
    name: 'chopcoach-prototype-http',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0];
        if (path !== endpoint && path !== assetPath) { next(); return; }
        // The Vite dev server binds to 127.0.0.1; this fixture never runs in build/preview.
        if (path === assetPath) {
          if (request.method !== 'GET') { json(response, 405, { message: 'GET만 지원합니다.' }); return; }
          readFile(new URL('./ai-generated-http-fixture.png', import.meta.url)).then(data => {
            if (response.destroyed) return;
            response.setHeader('Content-Type', 'image/png');
            response.setHeader('Cache-Control', 'no-store');
            response.end(data);
          }).catch(() => { if (!response.destroyed) json(response, 500, { message: '테스트 이미지를 열 수 없습니다.' }); });
          return;
        }
        if (request.method !== 'POST') { json(response, 405, { message: 'POST만 지원합니다.' }); return; }
        analyze(request, response).catch(() => {
          if (!response.destroyed && !response.writableEnded) json(response, 400, { message: '모의 업로드를 해석할 수 없습니다.' });
        });
      });
    },
  };
}
