# 이미지 입력부터 교정 결과까지 실행하는 로컬 파이프라인

`scripts/chopstick_pipeline/coach_pipeline.py`는 원본 query를 정규화하고 MediaPipe로 관절을 표시한 후, input_type별 reference를 선택하고 같은 전처리를 적용하여 GPT Responses API에 이미지 두 개와 좌표를 전송한다. GPT가 반환한 구조화된 교정 정보를 검증하고 쿼리 위에 화살표·번호를 그려 교정 이미지와 한국어 코멘트를 생성한다. GPT 이미지 생성 API를 사용하지 않으며, 사진 속 손의 외형을 새로 생성하지 않는다.

지원 실행 진입점은 `coach_pipeline.py`이다. `hand_landmarks.py`와 `evaluate_chopsticks.py`는 재사용한 하위 모듈이며, 기존 개별 CLI의 출력은 공개 GUI 응답 계약으로 사용하지 않는다. 특히 기존 개별 평가 함수는 내부 상태를 기록하는 로컬 도구이며 재촬영 분기와 안전한 manifest는 통합 진입점에서 적용한다.

기존 로컬 MediaPipe/GPT 분석 코드를 재사용한 통합 구현이다. 기존 코드의 사전 작업 구분은 준비 공개 문서 및 실제 개발 이력에 따른다. 이 문서는 HTTP API나 GUI의 최종 합의 계약이 아니다.

## 실행

검증 환경은 Python 3.12 (실제 실행 버전 3.12.15), Linux x86_64이다. `requirements.txt`에 직접 의존성 3개와 검증 환경의 하위 의존성 버전을 고정했다. Python·conda·OS 라이브러리는 pip 목록에 포함하지 않는다.

저장소 루트에서 다음과 같이 환경을 준비한다.

```bash
conda create -n hand-landmarks python=3.12 pip -y
conda activate hand-landmarks
python -m pip install -r scripts/chopstick_pipeline/requirements.txt
python -m pip check
```

실제 Linux 실행에서는 MediaPipe 공유 라이브러리가 요구하는 `libGLESv2.so.2`가 없어 별도로 준비해야 했다. 이 파일은 OS의 GLES 라이브러리이며 pip로 설치할 수 없다. 기존 로컬 실행은 해당 라이브러리 디렉터리를 `LD_LIBRARY_PATH`에 추가해 해결했다. 다른 컴퓨터에서는 OS 라이브러리 제공 여부를 확인하고, 별도 디렉터리에 설치했다면 그 디렉터리를 검색 경로에 추가한다. `.runtime-libs` 다운로드 파일과 개인 경로를 공유 저장소에 포함하지 않는다. 버전 고정은 이 환경의 기록이며 다른 OS에서의 실행 검증을 의미하지 않는다.

GPT 호출은 Python 표준 라이브러리 `urllib.request`를 사용하므로 `openai` SDK 패키지는 필요하지 않다. MediaPipe 모델은 공식 Hand Landmarker 모델이며 지정 경로에 없으면 다운로드한다.

`references.example.json`을 이미지가 있는 비공개 디렉터리에 복사한다. reference 경로는 해당 JSON 디렉터리 기준 상대 경로이며 디렉터리 외부 경로는 허용하지 않는다. 초기 예시는 `basic_grip` → `test_3.jpg`이다. 다른 유형은 references 항목에 추가한다. ID/version은 로컬 예시 값이며 공유 API 카탈로그 확정값이 아니다.

```bash
python scripts/chopstick_pipeline/coach_pipeline.py <TEST_ROOT>/test_camera_1.jpg \
  --input-type basic_grip \
  --catalog <TEST_ROOT>/references.json \
  --landmarker-model <TEST_ROOT>/models/hand_landmarker.task \
  --output-dir <OUTPUT_ROOT>/camera-1-run \
  --api-key-file <PRIVATE_KEY_FILE>
```

자리표시자는 각 컴퓨터의 실제 경로로 치환한다. API 키는 OPENAI_API_KEY 환경 변수로도 설정할 수 있다. 키를 명령 인수에 직접 쓰지 않는다. `--prepare-only`는 API 없이 이미지 전처리만 수행한다. `--query-mirrored`는 입력 파일 자체가 좌우 반전된 경우에만 지정한다. 기본 모델은 기존 프로토타입과 같은 gpt-4.1이며 `--model`로 변경할 수 있다.

## 결과

새 output-dir만 허용한다. 출력: query_landmarks.png/json, reference_landmarks.png/json, correction.png, comments.txt, assessment.json, result.json. 결과 manifest는 절대 경로·API 응답 ID를 포함하지 않는다. 이미지·좌표·분석 결과는 사용자 자료이므로 공개 저장소에 자동 추가하지 않는다.

query 손 미검출은 `retake / no_hand_detected`와 함께 밝은 곳·선명한 초점·깔끔한 배경·가리지 않은 손 전체를 안내한다. 모델이 카메라 시점이나 손바닥/손등 방향 차이로 비교 불가하다고 판단하면 `retake / view_mismatch`와 함께 기준 구도에 맞춰 재촬영하도록 안내하며 교정 이미지는 생성하지 않는다. 단순 위치·크기 차이와 교정 대상인 손가락 자세 차이를 구도 오류로 판단하지 않도록 프롬프트에 명시했다. 구도 판단은 GPT 기반이며 정확성을 보장하는 기하학 검사는 아니다. MediaPipe 실행 자체의 시스템 오류는 재촬영으로 바꾸지 않고 error로 처리한다. 기존 분류는 reference 손 미검출은 error로 처리한다. 모델의 not_assessable은 retake, uncertain은 불확실성을 유지한 안내 결과로 반환한다. uncertain을 신뢰 가능한 성공 판정으로 해석하면 안 된다. 실패 시 중간 자료와 안전한 error manifest를 남긴다. 입력 검사 단계 실패는 결과 디렉터리를 생성하지 않고 CLI 실패로 종료한다.

JPEG/PNG, 5 MiB, 1200만 픽셀을 로컬 기본 한도로 사용한다. GPT API socket timeout 기본값은 60초이며 `--timeout`으로 바꿀 수 있다. 전체 요청 deadline이나 GUI 취소 구현은 포함하지 않는다. 화살표는 2D 설명용 방향이며 실제 이동량·압력·동작 안정성이나 자세 정확도를 입증하지 않는다. 모델 문구의 근거성은 별도 검토가 필요하다.

## 검증

```bash
python -B -m unittest discover -s scripts/chopstick_pipeline -p 'test_*.py' -v
```

API와 MediaPipe를 모의한 통합 테스트는 처리 순서·이미지 두 개 전달·관절 anchoring·출력·손 미검출·오류·덮어쓰기 방지를 검증한다. 실제 이미지 전처리와 실제 API 호출 검증은 별도로 기록한다.

API 구현 근거: [이미지 입력](https://developers.openai.com/api/docs/guides/images-vision), [구조화된 출력](https://developers.openai.com/api/docs/guides/structured-outputs).

## 이번 구현의 실행 확인

mock 테스트 11개 통과. test_camera_1.jpg와 basic_grip → test_3.jpg 조합으로 실제 MediaPipe 전처리 및 GPT API 분석을 수행해 3000×4000 교정 이미지, 안내 5개(화살표 4개), 코멘트와 JSON 생성까지 확인했다. 손 검출·파일 생성의 실행 검증이며 자세 교정 정확도 검증은 아니다. 로컬 환경에서는 MediaPipe 로딩에 시스템 그래픽 공유 라이브러리 검색 경로 설정이 필요했다.

재촬영 처리 추가 후 테스트 13개 통과. 실제 손 없는 이미지에서 no_hand_detected 안내 반환 및 기존 예시의 실제 GPT 분석·출력 생성을 재확인했다. view_mismatch 분기의 재촬영 안내·교정 이미지 미생성은 모의 응답으로 검증했으며, 실제 구도 판정 정확도는 별도 검증 대상이다.

## GUI 저장소 반입과 코드 경계

이 변경은 GUI 프로토타입이 병합된 main을 기반으로 로컬 Python 분석 코드를 공유 저장소에 추가한다. 기존 로컬 관절 검출·두 이미지 GPT 분석·렌더링 모듈과 그 테스트를 반입하고, 유형별 카탈로그·통합 실행·재촬영 분기·환경 재현 문서를 함께 제공한다. 반입 전 존재했던 로컬 코드 전체를 이번 PR에서 처음 개발한 것으로 표시하지 않는다.

현재 파일은 `scripts/chopstick_pipeline/`의 독립 CLI 단위이며 이슈 #3의 backend 최종 구조가 확정됐다는 의미는 아니다. GUI 업로드 API·공개 feedback/retake/error 계약·결과 이미지 URL·수명·전체 deadline은 이슈 #2/#3에서 합의한 뒤 별도 연결한다. 이 PR에는 모델 가중치·개인 입력 사진·API 키·실행 결과·원본 로그를 포함하지 않는다.
