import type { DemoInput, DemoOutcome } from "../prototype";
import { isLocalAnalysisHost } from "./ai-generated-local-host";

/** Runnable local proposal; this is not the final shared pipeline contract. */
export interface LocalCoachConfig {
  schema_version: "local-coach-v1";
  mode: "mock" | "analysis";
  exercise: "basic_grip";
  handedness: "right";
  reference: { id: string; version: string };
  deadline_seconds: 180;
  asset_ttl_seconds: 600;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function invalid(): Error {
  return new Error("로컬 파이프라인 API의 응답 형식이 올바르지 않습니다. 다시 시도해 주세요.");
}

function reference(value: unknown): value is LocalCoachConfig["reference"] {
  return record(value) && text(value.id) && text(value.version);
}

function parseConfig(value: unknown): LocalCoachConfig {
  if (!record(value) || value.schema_version !== "local-coach-v1" ||
      (value.mode !== "mock" && value.mode !== "analysis") ||
      value.exercise !== "basic_grip" || value.handedness !== "right" ||
      !reference(value.reference) || value.deadline_seconds !== 180 || value.asset_ttl_seconds !== 600) throw invalid();
  return {
    schema_version: value.schema_version, mode: value.mode, exercise: value.exercise,
    handedness: value.handedness, reference: { ...value.reference },
    deadline_seconds: value.deadline_seconds, asset_ttl_seconds: value.asset_ttl_seconds,
  };
}

function image(value: unknown): Extract<DemoOutcome, { kind: "feedback" }>["correctionImage"] {
  if (!record(value) || value.mime_type !== "image/png" || !text(value.url) ||
      !Number.isSafeInteger(value.width) || !Number.isSafeInteger(value.height) ||
      typeof value.width !== "number" || typeof value.height !== "number" || value.width <= 0 || value.height <= 0) throw invalid();
  let url: URL;
  try { url = new URL(value.url, window.location.origin); } catch { throw invalid(); }
  if (url.origin !== window.location.origin || url.username || url.password || url.search || url.hash ||
      !/^\/api\/coach\/assets\/[A-Za-z0-9_-]+\.png$/.test(url.pathname)) throw invalid();
  return { kind: "provided", url: url.href, mimeType: "image/png", width: value.width, height: value.height };
}

function parseOutcome(value: unknown, config: LocalCoachConfig, requestId: string): DemoOutcome {
  if (!record(value) || value.schema_version !== config.schema_version || value.request_id !== requestId ||
      value.exercise !== config.exercise || value.handedness !== config.handedness || !reference(value.reference) ||
      value.reference.id !== config.reference.id || value.reference.version !== config.reference.version) throw invalid();
  const source = value.source;
  if (config.mode === "mock" ? source !== "mock" :
      source !== "analysis" && !(source === "preparation" && value.outcome === "retake")) throw invalid();
  if (value.outcome === "feedback") {
    if (source === "preparation" || value.retake !== null || value.error !== null || !record(value.feedback)) throw invalid();
    const feedback = value.feedback;
    if ((feedback.status !== "assessable" && feedback.status !== "uncertain") || !text(feedback.comment) ||
        !Array.isArray(feedback.corrections)) throw invalid();
    const details = feedback.corrections.map((item: unknown) => {
      if (!record(item) || !text(item.joint_name) || !text(item.instruction)) throw invalid();
      return { label: item.joint_name, text: item.instruction };
    });
    return {
      kind: "feedback", requestId, source: source as "mock" | "analysis", assessmentStatus: feedback.status,
      title: feedback.status === "uncertain" ? "판단이 불확실한 안내" : source === "mock" ? "로컬 API 모의 교정 안내" : "사진 분석 안내",
      summary: feedback.comment, details, correctionImage: image(feedback.image),
    };
  }
  if (value.outcome === "retake") {
    if (value.feedback !== null || value.error !== null || !record(value.retake) || !text(value.retake.reason) || !text(value.retake.message)) throw invalid();
    return { kind: "retake", requestId, source: source as "mock" | "analysis" | "preparation",
      title: source === "mock" ? "로컬 API 모의 재촬영 안내" : "다시 촬영해 주세요", message: value.retake.message };
  }
  if (value.outcome === "error") {
    if (source === "preparation" || value.feedback !== null || value.retake !== null ||
        !record(value.error) || !text(value.error.code) || !text(value.error.message)) throw invalid();
    return { kind: "error", requestId, source: source as "mock" | "analysis",
      title: source === "mock" ? "로컬 API 모의 오류 안내" : "분석 요청 오류", message: value.error.message };
  }
  throw invalid();
}

async function json(response: Response): Promise<unknown> {
  if (response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") throw invalid();
  try { return await response.json(); } catch { throw invalid(); }
}

/** Uses server-configured metadata and bounds both config lookup and upload. */
export async function runLocalCoach(input: DemoInput, onConfig?: (config: LocalCoachConfig) => void): Promise<DemoOutcome> {
  if (input.file.size > 5 * 1024 * 1024) {
    throw new Error("사진 파일은 5 MiB 이하로 선택해 주세요. 용량을 줄이거나 다른 사진으로 다시 시도해 주세요.");
  }
  if (!isLocalAnalysisHost(window.location.hostname)) {
    throw new Error("로컬 분석 서버는 localhost 또는 사설 네트워크 IPv4 주소에서만 사용할 수 있습니다.");
  }
  const controller = new AbortController();
  const abort = () => controller.abort(input.signal.reason);
  input.signal.addEventListener("abort", abort, { once: true });
  if (input.signal.aborted) abort();
  let timedOut = false;
  const started = performance.now();
  const expire = () => { timedOut = true; controller.abort(); };
  let timer = window.setTimeout(expire, 195_000);
  const options: RequestInit = { signal: controller.signal, credentials: "omit", mode: "same-origin", redirect: "error", cache: "no-store" };
  let stage = "서버 설정 조회";
  try {
    const response = await fetch("/api/coach/config", options);
    if (!response.ok) throw new Error(`로컬 API 설정을 확인할 수 없습니다 (HTTP ${response.status}).`);
    const config = parseConfig(await json(response));
    window.clearTimeout(timer);
    const remaining = (config.deadline_seconds + 15) * 1000 - (performance.now() - started);
    if (remaining <= 0) { expire(); throw new DOMException("요청 시간 초과", "AbortError"); }
    timer = window.setTimeout(expire, remaining);
    onConfig?.(config);
    const form = new FormData();
    form.append("image", input.file);
    for (const [key, value] of Object.entries({ schema_version: config.schema_version, request_id: input.requestId,
      exercise: config.exercise, handedness: config.handedness, reference_id: config.reference.id, reference_version: config.reference.version })) form.append(key, value);
    const headers: Record<string, string> = {};
    if (config.mode === "mock") headers["X-Local-Coach-Scenario"] = input.scenario;
    stage = "사진 업로드·분석 응답 수신";
    if (config.mode === "analysis") headers["X-Coach-Async"] = "1";
    let result = await fetch("/api/coach/analyze", { ...options, method: "POST", body: form, headers });
    if (result.status === 202) {
      const accepted = await json(result);
      if (!record(accepted) || accepted.request_id !== input.requestId || !text(accepted.job_url) ||
          !/^\/api\/coach\/jobs\/[A-Za-z0-9_-]{32}$/.test(accepted.job_url)) throw invalid();
      const jobUrl = accepted.job_url;
      stage = "분석 결과 조회";
      while (true) {
        await new Promise<void>((resolve, reject) => {
          const pause = window.setTimeout(() => { controller.signal.removeEventListener("abort", cancel); resolve(); }, 1000);
          const cancel = () => { window.clearTimeout(pause); reject(new DOMException("취소", "AbortError")); };
          if (controller.signal.aborted) cancel();
          else controller.signal.addEventListener("abort", cancel, { once: true });
        });
        try { result = await fetch(jobUrl, options); }
        catch (error) { if (controller.signal.aborted) throw error; continue; }
        if (result.status !== 202) break;
        const pending = await json(result);
        if (!record(pending) || pending.request_id !== input.requestId || pending.status !== "pending") throw invalid();
      }
    }
    const outcome = parseOutcome(await json(result), config, input.requestId);
    if (outcome.kind === "error" ? result.status < 400 || result.status >= 600 : result.status !== 200) throw invalid();
    return outcome;
  } catch (error) {
    if (timedOut && !input.signal.aborted) {
      throw new Error("로컬 API 응답 대기 시간이 초과되었습니다. 화면의 대기는 중단되었으며 서버 처리는 즉시 종료되지 않을 수 있습니다.");
    }
    if (input.signal.aborted) throw error;
    if (error instanceof Error && error.name !== "TypeError") throw error;
    throw new Error(`${stage} 중 네트워크 연결이 끊겼습니다. 페이지를 새로고침하고 핫스팟 연결을 유지한 채 다시 시도해 주세요. (${error instanceof Error ? error.message : "network error"})`);
  } finally {
    window.clearTimeout(timer);
    input.signal.removeEventListener("abort", abort);
  }
}
