# localhost GUI·파이프라인 연결 검증

2026-10-09 당일 구현한 로컬 API 연결 제안이다. [계약 제안](../contracts/ai-generated-local-coach-v1.md)과 이슈 #2·#3의 공동 검토를 함께 확인한다. 기존 파이프라인 폴더는 이동하지 않는다. 공개 배포·최종 공동 합의·실제 분석 정확도 검증은 별도 작업이다.

## mock 실행

프로젝트 루트에서 Pillow를 사용할 수 있는 Python으로 실행한다. 현재 환경에 패키지가 없다면 별도 가상환경에서 아래처럼 준비한다. 가상환경과 로컬 설정은 Git에 포함하지 않는다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install Pillow==12.3.0
.venv/bin/python -B -m backend.app.server --mode mock --port 8000
```

이미 Pillow가 설치된 환경에서는 `python3 -B -m backend.app.server --mode mock --port 8000`으로 시작할 수 있다. 다른 터미널에서 GUI를 실행한다.

```sh
cd frontend
npm ci
npm run dev
```

`http://127.0.0.1:5173/`에서 연결 방식의 localhost 파이프라인 API를 선택한다. 실제 파일이 8000 포트의 독립 서버로 전송되고 mock JSON과 별도 PNG를 받아 표시된다. 사진 분석은 실행하지 않는다. 브라우저 화면 예시와 기존 Vite HTTP fixture도 비교할 수 있다.

Vite 개발 서버는 `/api/coach`를 `http://127.0.0.1:8000`으로 프록시한다. 브라우저는 같은 origin만 요청한다. 서버는 loopback에 바인딩하고 기본 GUI origin 두 개(`http://127.0.0.1:5173`, `http://localhost:5173`)를 허용한다. 배포용 CORS·인증은 포함하지 않는다. Vite build/preview는 개발 프록시나 독립 서버를 자동 제공하지 않는다.

로컬 호스팅에는 GUI를 빌드한 뒤 API 실행에 `--frontend-dir frontend/dist`를 추가하여 웹페이지와 API를 같은 8000 포트에서 제공할 수 있다. 구체적인 실행 순서·파일 접근 경계·보안 정책·검증 범위는 [localhost 호스팅 안내](ai-generated-localhost-security-guide.md)를 따른다.

## 기존 실제 파이프라인을 실행하는 설정

먼저 [파이프라인 안내](ai-generated-chopstick-pipeline.md)에 따라 별도 환경·MediaPipe 모델·기준사진 카탈로그를 준비한다. 카탈로그의 `basic_grip` 항목에는 실제 사진과 reference ID·버전이 있어야 한다. 예시 카탈로그만 복사하면 사진이 확보된 것은 아니다. API 키는 서버 환경에만 설정하며 GUI나 명령 인자에 넣지 않는다.

아래 환경 변수는 사용자가 준비한 실제 파일·환경을 가리키도록 치환해야 하는 자리표시자다. 다른 컴퓨터에서 자동으로 준비되거나 인증이 이전되는 경로가 아니다.

| 변수 | 사용자가 지정할 값 |
| --- | --- |
| `COACH_CATALOG` | 실제 기준사진을 해석하는 카탈로그 파일 경로 |
| `COACH_LANDMARKER_MODEL` | 이미 준비한 MediaPipe hand landmarker 모델 파일 경로 |
| `COACH_PIPELINE_PYTHON` | 파이프라인 의존성이 설치된 환경의 Python 실행 파일 |

```sh
python3 -B -m backend.app.server --mode analysis --port 8000 \
  --catalog "$COACH_CATALOG" \
  --landmarker-model "$COACH_LANDMARKER_MODEL" \
  --pipeline-python "$COACH_PIPELINE_PYTHON"
```

이 모드에서는 서버가 기존 `scripts/chopstick_pipeline/coach_pipeline.py`를 실행한다. GUI의 모의 시나리오 선택으로 실제 분석 결과를 지정하지 않는다. 최초 분석에는 외부 모델 호출이 포함될 수 있다. 요청마다 별도 임시 디렉터리를 사용하며 API 응답에는 로컬 경로·중간 자료·키를 포함하지 않는다.

현재 연결 검증의 기본값은 mock이다. 실제 query/reference/correction 사진·MediaPipe/GPT 실행 결과는 별도 검증 전이며, mock 통과를 분석 정확도나 오른손 식별 검증으로 표현하지 않는다.

## 검증 실행

프로젝트 루트:

```sh
python3 -B -m unittest discover -s backend/tests -p 'test_*.py' -v
python3 -B -m unittest discover -s scripts/chopstick_pipeline -p 'test_*.py' -v
```

GUI:

```sh
cd frontend
npm run build
npm exec -- playwright install chromium --only-shell
npm test
```

Playwright는 독립 mock API를 8000 포트에 시작하고 사용 중인 API를 재사용하지 않는다. 수동 실행한 API가 있다면 시험 전에 해당 프로세스를 종료한다. GUI 개발 서버는 기존 localhost 서버를 재사용할 수 있다. 프로젝트의 별도 Playwright 브라우저 저장소를 사용한다면 `PLAYWRIGHT_BROWSERS_PATH`를 그 위치로 지정한다. 이 변수는 환경별 실제 설치 경로이며 자동 이전되지 않는다.

시험은 실제 multipart 업로드·디코딩 검사·JSON 상태 변환·PNG URL·GUI 표시·요청 교체 및 잘못된 응답 거절을 확인한다. subprocess 경계·시간 제한 시험에서는 외부 모델을 호출하지 않는다. 브라우저 취소는 결과 표시를 중단하지만 이미 실행된 서버 작업의 즉시 종료를 보장하지 않는다.

2026-10-09 구현 환경에서 타입 검사·빌드, 실제 Chromium 33개(기존 18개와 신규 15개), backend HTTP·subprocess 시험 21개, 기존 pipeline mock 13개가 통과했다. mock 서버 시험은 Python 3.13.12·Pillow 12.2.0에서 수행했다. 위 가상환경 설치 예시는 파이프라인의 Pillow 12.3.0 pin을 사용하며, 그 환경을 새로 설치한 결과를 뜻하지 않는다. 실제 분석·전처리 응답의 GUI 변형 시험은 계약 stub이며 외부 분석 호출 증거가 아니다.
