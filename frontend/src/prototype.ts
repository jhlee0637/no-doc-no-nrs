/** Frontend-only demonstration types. These are not the public API contract. */
export type DemoScenario = "feedback" | "retake" | "error";

export interface SelectedPhoto {
  selectionId: number;
  file: File;
  previewUrl: string;
  width: number;
  height: number;
}

export type DemoOutcome =
  | {
      kind: "feedback";
      requestId: string;
      source: "mock" | "analysis";
      assessmentStatus?: "assessable" | "uncertain";
      title: string;
      summary: string;
      details: Array<{ label: string; text: string }>;
      correctionImage:
        | { kind: "not-provided" }
        | { kind: "provided"; url: string; mimeType: "image/png"; width: number; height: number };
    }
  | { kind: "retake" | "error"; requestId: string; source: "mock" | "analysis" | "preparation"; title: string; message: string };

export interface DemoInput {
  file: File;
  requestId: string;
  scenario: DemoScenario;
  signal: AbortSignal;
}

/** No upload, image analysis, or other network request occurs here. */
export function runMock(input: DemoInput): Promise<DemoOutcome> {
  return new Promise((resolve, reject) => {
    if (input.signal.aborted) {
      reject(new DOMException("모의 요청 취소", "AbortError"));
      return;
    }

    const abort = () => {
      window.clearTimeout(timer);
      input.signal.removeEventListener("abort", abort);
      reject(new DOMException("모의 요청 취소", "AbortError"));
    };

    const timer = window.setTimeout(() => {
      input.signal.removeEventListener("abort", abort);
      const common = { requestId: input.requestId, source: "mock" as const };
      if (input.scenario === "feedback") {
        resolve({
          ...common,
          kind: "feedback",
          title: "교정 안내 화면 예시",
          summary: "실제 분석이 연결되면 가장 먼저 확인할 교정 행동을 이곳에 보여드립니다.",
          details: [
            { label: "관절별 안내 예시", text: "관절별 교정 설명을 펼쳐서 확인할 수 있는 영역입니다." },
            { label: "사진 위 방향 안내", text: "교정 이미지는 서버에서 제공된 뒤 표시합니다. 현재 사진에는 화살표를 그리지 않습니다." },
          ],
          correctionImage: { kind: "not-provided" },
        });
      } else if (input.scenario === "retake") {
        resolve({
          ...common,
          kind: "retake",
          title: "재촬영 안내 화면 예시",
          message: "손이 잘 보이는 사진을 다시 선택하도록 안내하는 화면입니다. 선택한 사진의 품질을 판단한 결과는 아닙니다.",
        });
      } else {
        resolve({
          ...common,
          kind: "error",
          title: "오류 안내 화면 예시",
          message: "서비스에 문제가 생겼을 때 다시 시도를 안내하는 화면입니다. 실제 서버 오류가 발생한 것은 아닙니다.",
        });
      }
    }, 900);

    input.signal.addEventListener("abort", abort, { once: true });
  });
}
