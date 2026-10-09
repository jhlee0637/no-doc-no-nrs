import type { DemoInput, DemoOutcome } from "../prototype";

/** Local test values only. They do not establish the shared pipeline contract. */
const prototypeMetadata = {
  schema_version: "prototype-http-v1",
  exercise: "chopsticks",
  handedness: "right",
  reference_id: "prototype-reference",
  reference_version: "0",
};

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function invalidResponse(): Error {
  return new Error("localhost 모의 서버의 응답 형식이 올바르지 않습니다. 다시 시도해 주세요.");
}

function assetUrl(value: unknown): string {
  if (!text(value)) throw invalidResponse();
  let parsed: URL;
  try {
    parsed = new URL(value, window.location.origin);
  } catch {
    throw invalidResponse();
  }
  if (
    parsed.origin !== window.location.origin ||
    !parsed.pathname.startsWith("/__prototype__/assets/") ||
    parsed.username || parsed.password || parsed.hash
  ) throw invalidResponse();
  return parsed.href;
}

function dimension(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function validateOutcome(value: unknown, requestId: string): DemoOutcome {
  if (!record(value) || value.requestId !== requestId || value.source !== "mock" || !text(value.title)) {
    throw invalidResponse();
  }
  const common = { requestId, source: "mock" as const, title: value.title };
  if (value.kind === "retake" || value.kind === "error") {
    if (!text(value.message)) throw invalidResponse();
    return { ...common, kind: value.kind, message: value.message };
  }
  if (value.kind !== "feedback" || !text(value.summary) || !Array.isArray(value.details) || !record(value.correctionImage)) {
    throw invalidResponse();
  }
  const details = value.details.map((detail: unknown) => {
    if (!record(detail) || !text(detail.label) || !text(detail.text)) throw invalidResponse();
    return { label: detail.label, text: detail.text };
  });
  const image = value.correctionImage;
  if (image.kind === "not-provided") {
    return { ...common, kind: "feedback", summary: value.summary, details, correctionImage: { kind: "not-provided" } };
  }
  if (image.kind !== "provided" || image.mimeType !== "image/png" || !dimension(image.width) || !dimension(image.height)) {
    throw invalidResponse();
  }
  return {
    ...common,
    kind: "feedback",
    summary: value.summary,
    details,
    correctionImage: {
      kind: "provided",
      url: assetUrl(image.url),
      mimeType: "image/png",
      width: image.width,
      height: image.height,
    },
  };
}

/** Sends a real multipart upload to the loopback fixture, never to a model. */
export async function runPrototypeHttp(input: DemoInput): Promise<DemoOutcome> {
  if (!["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname)) {
    throw new Error("HTTP 모의 연결은 localhost에서만 사용할 수 있습니다.");
  }
  const form = new FormData();
  form.append("image", input.file);
  for (const [key, value] of Object.entries(prototypeMetadata)) form.append(key, value);
  form.append("request_id", input.requestId);

  let response: Response;
  try {
    response = await fetch("/__prototype__/analyze", {
      method: "POST",
      body: form,
      headers: { "X-Prototype-Scenario": input.scenario },
      signal: input.signal,
      credentials: "omit",
      mode: "same-origin",
      redirect: "error",
    });
  } catch (error) {
    if (input.signal.aborted) throw error;
    throw new Error("localhost 모의 서버에 연결할 수 없습니다. 개발 서버를 확인해 주세요.");
  }
  if (!response.ok) {
    throw new Error(`localhost 모의 서버 요청이 실패했습니다 (HTTP ${response.status}). 다시 시도해 주세요.`);
  }
  if (!response.headers.get("content-type")?.toLowerCase().includes("application/json")) throw invalidResponse();
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (input.signal.aborted) throw error;
    throw invalidResponse();
  }
  return validateOutcome(value, input.requestId);
}
