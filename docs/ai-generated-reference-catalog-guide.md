# 기준 이미지의 localhost 연결안

기준 원본을 기존 CLI와 localhost API에 연결하는 검토용 카탈로그다. 이미지 용도, reference ID/version, input_type의 공동 확정은 이슈 #2, 담당 범위는 #3에서 진행한다. 기본 API 실행은 계속 mock이며 이 파일 추가로 실제 분석을 시작하지 않는다.

## 두 개의 독립 카탈로그

| 카탈로그 | `basic_grip`의 임시 ID | 버전 | 같은 폴더의 기준 원본 |
| --- | --- | --- | --- |
| `assets/references/ai-generated-catalog-bul.example.json` | `reference-bul-draft` | `draft-1` | `reference_bul.png` |
| `assets/references/ai-generated-catalog-zip.example.json` | `reference-zip-draft` | `draft-1` | `reference_zip.png` |

현재 API는 `basic_grip` 하나와 서버가 선택한 기준 하나를 지원한다. 두 카탈로그는 각각 실행해 비교할 대안이며 bul·zip을 새로운 운동 종류로 확정하거나 화면에서 동시에 선택하는 기능이 아니다. 어느 원본을 어떤 사용자 자세와 비교할지 확인한 뒤 실제 서비스 매핑을 정한다. 카탈로그를 바꿀 때 서버를 재시작하고 GUI가 새 config를 조회하도록 한다.

카탈로그의 `schema_version="1"`은 기존 CLI 목록 형식이다. GUI↔API의 잠정 계약 `local-coach-v1`과 구분한다. 기준 파일은 카탈로그 폴더 안의 상대 경로여야 한다. 예시 JSON을 다른 폴더에 단독 복사하면 이미지가 함께 옮겨지지 않아 실행되지 않는다. 원본과 JSON을 함께 준비하거나 저장소 안의 예시 경로를 직접 지정한다.

이미지를 교체할 때 버전도 변경하는 안을 제안한다. 아래 SHA-256은 검토한 원본 바이트의 식별 근거이며, 현재 CLI가 해시를 자동 검증한다는 의미는 아니다.

| 원본 | SHA-256 |
| --- | --- |
| `reference_bul.png` | `2bc1404cb52477b28ef476072997aac6b0bf4a6365c93c77ff0d0ee6b1c9cc7d` |
| `reference_zip.png` | `69423a20175a5e1ea20a70022334909bda61069e33b88fe5d8954c396c214f8d` |

## 전처리부터 확인

[파이프라인 안내](ai-generated-chopstick-pipeline.md)에 따라 Python 환경과 MediaPipe 모델을 먼저 준비한다. 다음 환경 변수는 각 컴퓨터에서 사용자가 실제로 준비한 값을 가리킨다. 인증·모델·사진은 저장소 복사만으로 이전되지 않는다.

| 변수 | 치환할 값 |
| --- | --- |
| `COACH_PIPELINE_PYTHON` | 파이프라인 의존성이 설치된 Python 실행 파일 |
| `COACH_LANDMARKER_MODEL` | 준비한 hand landmarker `.task` 모델의 경로 |
| `COACH_QUERY` | 사용자가 분석하려는 JPEG/PNG 사진 경로 |
| `COACH_OUTPUT` | 아직 존재하지 않는 비공개 결과 디렉터리 경로 |

저장소 루트에서 bul 예시를 전처리한다. zip은 catalog 인자만 해당 예시로 바꾸고 새로운 output 경로를 사용한다.

```sh
"$COACH_PIPELINE_PYTHON" scripts/chopstick_pipeline/coach_pipeline.py "$COACH_QUERY" \
  --input-type basic_grip \
  --catalog assets/references/ai-generated-catalog-bul.example.json \
  --landmarker-model "$COACH_LANDMARKER_MODEL" \
  --output-dir "$COACH_OUTPUT" --prepare-only
```

`--prepare-only`는 GPT 호출 없이 실제 관절 검출을 수행한다. 성공 시 `source=preparation`, `status=prepared`이며 교정 결과가 아니다. 손 없는 query는 retake, 손 없는 reference는 error다. 실제 사용자 사진이 없다면 기준 원본을 query에도 사용해 검출 경로만 시험할 수 있으나 사용자 사진·자세 교정 검증으로 기록하지 않는다.

기존 CLI와 API 어댑터의 검출 임계값은 기본 0.5다. 반입된 표시본의 0.3과 다르다. 표시본의 손 검출 보고를 기본값 0.5의 통과 근거로 재사용하지 않는다. CLI에서 `--confidence 0.3`을 별도로 시험하면 그 설정을 기록한다. API 어댑터는 이 옵션을 현재 전달하지 않으므로 CLI의 0.3 결과를 API 실행 결과로 주장하지 않는다.

## 실제 GUI 연결

전처리 통과, 사용자 query 및 기준 용도 확인, 서버 환경의 `OPENAI_API_KEY` 준비 후 [localhost API 안내](ai-generated-local-coach-guide.md)의 analysis 모드를 사용한다. 실제 분석은 외부 API 호출을 포함한다. 키 값을 GUI·JSON·명령 인수·공개 기록에 넣지 않는다.

```sh
python3 -B -m backend.app.server --mode analysis --port 8000 \
  --catalog assets/references/ai-generated-catalog-bul.example.json \
  --landmarker-model "$COACH_LANDMARKER_MODEL" \
  --pipeline-python "$COACH_PIPELINE_PYTHON"
```

8000 포트의 기존 mock 서버를 종료한 뒤 시작한다. GUI는 `http://127.0.0.1:5173/`에서 localhost 파이프라인 API를 선택한다. config의 임시 기준 ID/version을 받아 사진을 전송하며, 실제 피드백 또는 재촬영·오류를 표시한다. 개인 사진·중간 이미지·좌표·원본 로그·실행 결과는 Git 제외 경로에서 관리한다.

## 자료 출처와 검증 범위

원본 두 PNG의 C2PA 메타데이터에는 ChatGPT/gpt-image 생성 출처가 기록되어 있다. 사용자가 선택해 반입한 생성 이미지이며 카메라 촬영 원본 또는 검증된 정답 자세로 간주하지 않는다. C2PA의 암호 서명은 검증하지 않았다. 파일 역할과 표시본 처리 정보는 [기준 이미지 문서](ai-generated-reference-images.md)를 참고한다.

카탈로그 파일·원본 디코딩·기존 두 loader의 ID/version 일치는 외부 모델 없이 확인할 수 있다. 이러한 연결 확인은 실제 MediaPipe 실행, GPT 응답, 사용자 사진 왕복 또는 자세 교정 정확도 검증과 구분해서 기록한다.

### 2026-10-09 실행 확인

- 두 예시의 원본 해시·전체 PNG 디코딩·용량·해상도와 CLI/API loader의 ID/version 일치 확인.
- 별도 Python 3.12.3 환경에 저장소의 고정 요구 패키지 설치, `pip check` 및 실제 import 통과. MediaPipe 0.10.35, NumPy 2.5.3, Pillow 12.3.0과 시스템 GLES/EGL 로드 확인.
- 공식 hand landmarker 모델로 두 원본 각각을 query와 reference에 사용해 `--prepare-only` 실행. 기본 confidence 0.5에서 각각 손 하나 검출, `source=preparation`, `status=prepared` 확인. 사용자 촬영 사진 검증은 아님.
- 실제 Chromium에서 합성 손 없는 PNG를 GUI → Vite 프록시 → analysis 모드 API → 실제 MediaPipe에 전송. HTTP 200, `source=preparation`, `outcome=retake`, `reason=no_hand_detected` 및 GUI 전처리·재촬영 안내 확인. 요청/응답 라우트 모의 없이 수행했고 GPT 호출은 없음.
- 새 Python 환경에서 기존 pipeline mock 13개 통과. GUI 실행 코드는 변경하지 않았으므로 앞선 Chromium 33개 결과와 이번 실제 전처리 연결 확인을 구분함.

전처리 검증 뒤 API는 mock으로 복귀했다. API 키·사용자 query 준비와 기준 용도 합의가 남아 있어 실제 GPT 교정 결과까지의 왕복은 미수행이다. 관절 검출과 재촬영 안내의 실행 성공을 자세 교정 정확도로 해석하지 않는다.
