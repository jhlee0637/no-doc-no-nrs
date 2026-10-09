import "./styles.css";
import { runMock, type DemoOutcome, type DemoScenario, type SelectedPhoto } from "./prototype";
import { runPrototypeHttp } from "./api/prototype-http";
import { runLocalCoach } from "./api/local-coach";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("화면을 표시할 영역이 없습니다.");

app.innerHTML = `
  <main class="page-shell">
    <header class="topbar">
      <a class="brand" href="#" aria-label="ChopCoach 첫 화면"><span class="brand-icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M6 20 16 4M11 20 20 4" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" /></svg></span> ChopCoach</a>
      <span class="local-pill">LOCAL PROTOTYPE</span>
    </header>
    <section class="hero" aria-labelledby="page-title">
      <p class="eyebrow">사진 한 장으로 시작하는 젓가락 코칭</p>
      <h1 id="page-title">나의 젓가락 자세,<br />사진으로 확인해요.</h1>
      <p class="muted">젓가락을 잡은 손 사진을 선택하고 교정 안내 화면을 미리 살펴보세요.</p>
      <p id="transport-notice" class="notice">화면 검증용 모의 응답 · 서버 전송 없음</p>
    </section>
    <div class="workspace">
      <section class="card" aria-labelledby="photo-heading">
        <div class="card-heading"><span class="step-number">01</span><div><p class="small-label">YOUR PHOTO</p><h2 id="photo-heading">손 사진 선택</h2></div></div>
        <input id="photo-input" class="file-picker" type="file" accept="image/jpeg,image/png" hidden />
        <div id="drop-zone" class="drop-zone" tabindex="0" role="button" aria-label="JPEG 또는 PNG 손 사진 선택. 사진을 끌어 놓아도 됩니다.">
          <div id="upload-empty" class="upload-empty"><span aria-hidden="true">＋</span><strong>사진을 선택해 주세요</strong><p>클릭하거나 사진 한 장을 끌어 놓으세요</p><p class="muted">JPEG · PNG</p></div>
          <img id="preview-image" class="preview-image" alt="선택한 손 사진 미리보기" hidden />
        </div>
        <div id="photo-meta" class="photo-meta" hidden><strong id="file-name"></strong><span id="file-details" class="muted"></span><span class="preview-caption">선택한 원본의 브라우저 미리보기</span></div>
        <div class="actions"><button id="replace-photo" class="button button-secondary" type="button">사진 선택</button><button id="clear-photo" class="button button-secondary" type="button" disabled>사진 지우기</button></div>
        <p class="muted">손과 젓가락이 함께 보이도록 촬영하면 좋아요.</p>
        <div class="scenario-control"><label for="demo-transport">연결 방식</label><select id="demo-transport"><option value="browser">브라우저 화면 예시 · 전송 없음</option><option value="http">localhost HTTP 모의 서버</option><option value="pipeline">localhost 파이프라인 API</option></select></div>
        <div class="scenario-control"><label for="demo-scenario">살펴볼 모의 화면</label><select id="demo-scenario"><option value="feedback">교정 안내</option><option value="retake">재촬영 안내</option><option value="error">서비스 오류</option></select></div>
        <div class="actions"><button id="show-result" class="button button-primary" type="button" disabled>모의 결과 보기 <span aria-hidden="true">→</span></button><button id="cancel-request" class="button button-secondary" type="button" hidden>취소</button></div>
        <p id="status-message" class="status" role="status" aria-live="polite" aria-atomic="true">사진을 선택하면 미리보기를 확인할 수 있습니다.</p>
      </section>
      <section id="result-panel" class="card" aria-labelledby="result-heading" aria-busy="false">
        <div class="card-heading"><span class="step-number">02</span><div><p class="small-label">YOUR FEEDBACK</p><h2 id="result-heading">교정 안내</h2></div></div>
        <div id="result-empty" class="result-empty"><span aria-hidden="true">↗</span><h3>다음 자세를 위한 작은 힌트</h3><p class="muted">사진을 선택하고 모의 결과를 확인해 보세요.<br />교정 이미지와 안내가 들어갈 화면입니다.</p></div>
        <div id="result-content" class="result-content" hidden>
          <p id="outcome-badge" class="outcome-badge">모의 응답</p>
          <h3 id="feedback-title" class="feedback-title"></h3>
          <p id="result-body" class="result-body"></p>
          <div id="result-image-placeholder" class="image-placeholder" hidden><strong>교정 이미지 제공 대기</strong><p class="muted">실제 결과 이미지가 연결되면 이곳에 표시됩니다.</p></div>
          <div id="result-image-container" class="image-placeholder" hidden><img id="correction-image" class="preview-image" alt="HTTP 연결 검증용 합성 이미지. 실제 교정 결과가 아닙니다." hidden /><p id="result-image-status" class="muted" role="status" aria-live="polite"></p></div>
          <details id="feedback-details" class="details" hidden><summary id="detail-summary">관절별 안내 예시 펼치기</summary><div id="detail-list"></div></details>
          <p id="result-notice" class="notice">선택한 사진을 분석한 결과가 아닌 화면 예시입니다.</p>
        </div>
      </section>
    </div>
    <footer class="footer"><span>ChopCoach · 작은 움직임, 편안한 한 끼</span><span class="muted">로컬 화면 검증용 프로토타입</span></footer>
  </main>`;

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`화면 요소를 찾을 수 없습니다: ${id}`);
  return found as T;
}

const input = element<HTMLInputElement>("photo-input");
const dropZone = element<HTMLDivElement>("drop-zone");
const preview = element<HTMLImageElement>("preview-image");
const uploadEmpty = element<HTMLDivElement>("upload-empty");
const photoMeta = element<HTMLDivElement>("photo-meta");
const fileName = element<HTMLElement>("file-name");
const fileDetails = element<HTMLElement>("file-details");
const replaceButton = element<HTMLButtonElement>("replace-photo");
const clearButton = element<HTMLButtonElement>("clear-photo");
const showButton = element<HTMLButtonElement>("show-result");
const cancelButton = element<HTMLButtonElement>("cancel-request");
const scenario = element<HTMLSelectElement>("demo-scenario");
const transport = element<HTMLSelectElement>("demo-transport");
const transportNotice = element<HTMLElement>("transport-notice");
const status = element<HTMLElement>("status-message");
const resultPanel = element<HTMLElement>("result-panel");
const resultEmpty = element<HTMLElement>("result-empty");
const resultContent = element<HTMLElement>("result-content");
const title = element<HTMLElement>("feedback-title");
const resultBody = element<HTMLElement>("result-body");
const placeholder = element<HTMLElement>("result-image-placeholder");
const imageContainer = element<HTMLElement>("result-image-container");
const correctionImage = element<HTMLImageElement>("correction-image");
const imageStatus = element<HTMLElement>("result-image-status");
const details = element<HTMLDetailsElement>("feedback-details");
const detailList = element<HTMLElement>("detail-list");
const detailSummary = element<HTMLElement>("detail-summary");
const badge = element<HTMLElement>("outcome-badge");
const resultNotice = element<HTMLElement>("result-notice");

let photo: SelectedPhoto | null = null;
let selectionId = 0;
let requestGeneration = 0;
let decoding = false;
let requestController: AbortController | null = null;
let decodingUrl: string | null = null;
let imageGeneration = 0;
let detachImageHandlers: (() => void) | null = null;
let pipelineMode: "mock" | "analysis" | null = null;

function message(text: string): void {
  status.textContent = text;
}

function updateControls(): void {
  const running = requestController !== null;
  clearButton.disabled = !photo && !decoding;
  showButton.disabled = !photo || decoding || running;
  scenario.disabled = running || (transport.value === "pipeline" && pipelineMode === "analysis");
  transport.disabled = running;
  cancelButton.hidden = !running;
  resultPanel.setAttribute("aria-busy", String(running));
  replaceButton.textContent = photo ? "사진 바꾸기" : "사진 선택";
  showButton.textContent = transport.value === "pipeline" ? "로컬 API 결과 보기 →" : "모의 결과 보기 →";
}

function resetResult(): void {
  imageGeneration += 1;
  detachImageHandlers?.();
  detachImageHandlers = null;
  correctionImage.hidden = true;
  correctionImage.removeAttribute("src");
  imageContainer.hidden = true;
  imageStatus.textContent = "";
  resultContent.hidden = true;
  resultEmpty.hidden = false;
  placeholder.hidden = true;
  details.hidden = true;
  details.open = false;
  detailList.replaceChildren();
  title.textContent = "";
  resultBody.textContent = "";
}

function invalidateRequest(): void {
  requestGeneration += 1;
  const previous = requestController;
  requestController = null;
  previous?.abort();
}

function releasePhoto(): void {
  preview.hidden = true;
  preview.removeAttribute("src");
  if (photo) URL.revokeObjectURL(photo.previewUrl);
  photo = null;
  if (decodingUrl) URL.revokeObjectURL(decodingUrl);
  decodingUrl = null;
  uploadEmpty.hidden = false;
  photoMeta.hidden = true;
  fileName.textContent = "";
  fileDetails.textContent = "";
}

async function selectPhoto(file: File): Promise<void> {
  const currentSelection = ++selectionId;
  invalidateRequest();
  releasePhoto();
  resetResult();
  decoding = true;
  updateControls();
  message("사진을 열고 있습니다…");
  let candidateUrl: string | null = null;
  try {
    const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer());
    if (currentSelection !== selectionId) return;
    const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
    const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((byte, index) => bytes[index] === byte);
    if (!jpeg && !png) throw new Error("JPEG 또는 PNG 이미지 한 장을 선택해 주세요.");
    candidateUrl = URL.createObjectURL(file);
    decodingUrl = candidateUrl;
    const image = new Image();
    image.src = candidateUrl;
    await image.decode();
    if (currentSelection !== selectionId) return;
    if (!image.naturalWidth || !image.naturalHeight) throw new Error("이미지 크기를 확인할 수 없습니다. 다른 사진을 선택해 주세요.");
    photo = { selectionId: currentSelection, file, previewUrl: candidateUrl, width: image.naturalWidth, height: image.naturalHeight };
    decodingUrl = null;
    candidateUrl = null;
    preview.src = photo.previewUrl;
    preview.hidden = false;
    uploadEmpty.hidden = true;
    photoMeta.hidden = false;
    fileName.textContent = file.name;
    const size = file.size >= 1024 * 1024 ? `${(file.size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(file.size / 1024))} KB`;
    fileDetails.textContent = `${size} · ${photo.width.toLocaleString()} × ${photo.height.toLocaleString()} px`;
    message("사진을 선택했습니다. 결과 보기를 눌러 주세요.");
  } catch (error) {
    if (currentSelection !== selectionId) return;
    message(error instanceof Error && error.message.startsWith("JPEG") ? error.message : "사진을 열 수 없습니다. 정상적인 JPEG 또는 PNG 파일을 다시 선택해 주세요.");
  } finally {
    if (candidateUrl) {
      URL.revokeObjectURL(candidateUrl);
      if (decodingUrl === candidateUrl) decodingUrl = null;
    }
    if (currentSelection === selectionId) {
      decoding = false;
      updateControls();
    }
  }
}

function clearPhoto(): void {
  selectionId += 1;
  invalidateRequest();
  releasePhoto();
  decoding = false;
  resetResult();
  input.value = "";
  updateControls();
  message("사진을 지웠습니다. 새 사진을 선택해 주세요.");
  replaceButton.focus();
}

function renderResult(outcome: DemoOutcome): void {
  resetResult();
  resultEmpty.hidden = true;
  resultContent.hidden = false;
  title.textContent = outcome.title;
  const mock = outcome.source === "mock";
  const uncertain = outcome.kind === "feedback" && outcome.assessmentStatus === "uncertain";
  badge.textContent = `${mock ? "모의 응답" : outcome.kind === "error" ? "요청 오류" : outcome.source === "preparation" ? "전처리 안내" : outcome.kind === "retake" ? "재촬영 안내" : "사진 분석 안내"}${uncertain ? " · 판단 불확실" : ""}`;
  resultNotice.textContent = mock ? "선택한 사진을 분석한 결과가 아닌 화면 예시입니다." :
    outcome.kind === "error" ? "요청을 완료하지 못했습니다. 다시 시도해 주세요." :
    outcome.source === "preparation" ? "손 검출 단계의 재촬영 안내입니다." :
    outcome.kind === "retake" ? "안내에 따라 손과 젓가락이 잘 보이도록 다시 촬영해 주세요." :
    uncertain ? "사진만으로 판단하기 어려운 부분이 있습니다. 손과 젓가락이 잘 보이도록 다시 촬영해 주세요." :
    "기준사진과 비교한 관절별 안내입니다.";
  detailSummary.textContent = mock ? "관절별 안내 예시 펼치기" : "관절별 안내 펼치기";
  if (outcome.kind === "feedback") {
    resultBody.textContent = outcome.summary;
    if (outcome.correctionImage.kind === "provided") {
      const asset = outcome.correctionImage;
      const token = imageGeneration;
      const selected = photo?.selectionId;
      const generation = requestGeneration;
      const current = () => token === imageGeneration && selected === photo?.selectionId && generation === requestGeneration;
      imageContainer.hidden = false;
      correctionImage.alt = mock ? "HTTP 연결 검증용 합성 이미지. 실제 교정 결과가 아닙니다." : "서버가 제공한 교정 방향 안내 이미지";
      imageStatus.textContent = mock ? "HTTP 연결 검증용 합성 이미지를 불러오고 있습니다…" : "교정 방향 안내 이미지를 불러오고 있습니다…";
      const loaded = () => {
        if (!current()) return;
        if (correctionImage.naturalWidth !== asset.width || correctionImage.naturalHeight !== asset.height) {
          correctionImage.hidden = true;
          imageStatus.textContent = "결과 이미지 크기가 서버 응답과 다릅니다. 다시 시도해 주세요.";
          return;
        }
        correctionImage.hidden = false;
        imageStatus.textContent = mock ? "HTTP 연결 검증용 합성 PNG · 선택한 사진의 교정 결과가 아닙니다." :
          "서버가 제공한 교정 방향 안내 이미지";
      };
      const failed = () => {
        if (!current()) return;
        correctionImage.hidden = true;
        imageStatus.textContent = "결과 이미지를 불러오지 못했습니다. 안내 내용은 유지되며 다시 시도할 수 있습니다.";
      };
      correctionImage.addEventListener("load", loaded);
      correctionImage.addEventListener("error", failed);
      detachImageHandlers = () => {
        correctionImage.removeEventListener("load", loaded);
        correctionImage.removeEventListener("error", failed);
      };
      correctionImage.src = asset.url;
    } else {
      placeholder.hidden = false;
    }
    details.hidden = outcome.details.length === 0;
    for (const item of outcome.details) {
      const paragraph = document.createElement("p");
      const label = document.createElement("strong");
      label.textContent = item.label;
      paragraph.append(label, document.createElement("br"), document.createTextNode(item.text));
      detailList.append(paragraph);
    }
  } else {
    resultBody.textContent = outcome.message;
  }
}

async function showResult(): Promise<void> {
  if (!photo || decoding || requestController) return;
  const selected = photo;
  const generation = ++requestGeneration;
  const controller = new AbortController();
  const requestId = crypto.randomUUID();
  const selectedScenario = scenario.value as DemoScenario;
  const http = transport.value === "http";
  const pipeline = transport.value === "pipeline";
  requestController = controller;
  resetResult();
  updateControls();
  message(pipeline ? "로컬 API의 연결 모드를 확인하고 있습니다…" : http ? "localhost 모의 서버 전송 중 · 실제 분석 없음" : "모의 응답을 준비하고 있습니다… 사진은 서버로 전송되지 않습니다.");
  try {
    const input = { file: selected.file, requestId, scenario: selectedScenario, signal: controller.signal };
    const outcome = pipeline ? await runLocalCoach(input, config => {
      if (generation !== requestGeneration || controller.signal.aborted) return;
      pipelineMode = config.mode;
      transportNotice.textContent = config.mode === "mock" ? "로컬 파이프라인 API · 모의 모드 · 실제 분석 없음" : "로컬 파이프라인 API · 서버 분석 모드 · 사진 전송";
      message(config.mode === "mock" ? "로컬 API 모의 응답을 요청하고 있습니다. 실제 사진 분석은 없습니다." : "서버 분석을 요청하고 있습니다. 모의 화면 선택은 적용하지 않습니다.");
      updateControls();
    }) : await (http ? runPrototypeHttp : runMock)(input);
    if (generation !== requestGeneration || photo?.selectionId !== selected.selectionId || controller.signal.aborted || outcome.requestId !== requestId) return;
    renderResult(outcome);
    message(`${outcome.title}를 표시했습니다.${outcome.source === "mock" ? " 실제 사진 분석 결과는 아닙니다." : ""}`);
  } catch (error) {
    if (generation !== requestGeneration || controller.signal.aborted) return;
    message(error instanceof DOMException && error.name === "AbortError" ? "요청을 취소했습니다." : (http || pipeline) && error instanceof Error ? error.message : "모의 화면을 표시하지 못했습니다. 다시 시도해 주세요.");
  } finally {
    if (generation === requestGeneration) {
      requestController = null;
      updateControls();
    }
  }
}

input.addEventListener("change", () => {
  const file = input.files?.[0];
  input.value = "";
  if (file) void selectPhoto(file);
});
dropZone.addEventListener("click", () => input.click());
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    input.click();
  }
});
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
});
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  const files = event.dataTransfer?.files;
  if (!files?.length) return;
  if (files.length !== 1) {
    message("사진은 한 번에 한 장만 선택해 주세요.");
    return;
  }
  void selectPhoto(files[0]);
});
replaceButton.addEventListener("click", () => input.click());
clearButton.addEventListener("click", clearPhoto);
showButton.addEventListener("click", () => void showResult());
transport.addEventListener("change", () => {
  invalidateRequest();
  resetResult();
  pipelineMode = null;
  updateControls();
  const http = transport.value === "http";
  const pipeline = transport.value === "pipeline";
  transportNotice.textContent = pipeline ? "로컬 파이프라인 API · 서버 모드 확인 후 사진 전송" : http ? "localhost 모의 서버 전송 · 실제 분석 없음" : "화면 검증용 모의 응답 · 서버 전송 없음";
  message(pipeline ? "로컬 API 결과 보기에서 서버 설정을 먼저 확인한 뒤 사진을 전송합니다." : http ? "localhost 모의 연결을 선택했습니다. 결과 보기 시 실제 파일을 로컬 서버로 전송합니다." : "브라우저 모의 연결을 선택했습니다. 사진을 서버로 전송하지 않습니다.");
});
cancelButton.addEventListener("click", () => {
  invalidateRequest();
  resetResult();
  updateControls();
  message(transport.value === "pipeline" ? "화면의 요청 대기를 취소했습니다. 서버 처리는 즉시 종료되지 않을 수 있습니다." : "모의 요청을 취소했습니다. 같은 사진으로 다시 확인할 수 있습니다.");
  showButton.focus();
});

window.addEventListener("pagehide", (event) => {
  // A page kept in the back/forward cache still owns its preview URLs.
  if (event.persisted) return;
  selectionId += 1;
  invalidateRequest();
  releasePhoto();
});
