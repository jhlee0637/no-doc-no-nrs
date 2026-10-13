# no-doc-no-nrs · ChopCoach

젓가락을 잡은 손 사진과 기준 사진을 비교해 한국어 교정 안내와 방향 표시 이미지를 제공하는 웹 프로토타입입니다. 해커톤에서는 **사진 한 장의 업로드부터 로컬 서버의 분석 결과 표시까지** 구현했습니다.

## 프로젝트 목표

- 5~10초의 젓가락 동작을 촬영하고 손의 21개 관절과 젓가락 위치를 실시간으로 추적합니다.
- 손가락–젓가락 간 거리와 프레임별 위치 변화로 아래 젓가락 안정성, 위 젓가락 독립 움직임, 손가락 지지와 교차 여부를 측정합니다.
- AI가 우선 교정할 문제를 선택하고, 사용자가 따라 할 수 있는 자연어와 시각적 안내를 제공합니다.

## 실제 구현한 범위

### 사진 분석 파이프라인

현재 입력은 JPEG/PNG **정지 사진 한 장**입니다. 서버에 설정한 기준 사진과 비교하며, 기본 업로드 한도는 5 MiB·1,200만 픽셀입니다.

| 단계 | 구현 내용 |
| --- | --- |
| 1. 입력 준비 | 사진·요청 메타데이터를 전달하고 서버 카탈로그에서 기준 사진 선택 |
| 2. 관절 검출 | EXIF 회전 정규화와 MediaPipe 손 관절 21개 검출·좌표 및 표시 이미지 생성 |
| 3. AI 비교 | 기준·사용자 이미지와 관절 좌표를 GPT에 전달해 관절별 설명·2D 목표점 제안 |
| 4. 결과 표시 | 파이프라인에서 화살표·목표점·관절 번호를 그린 PNG와 한국어 안내 생성, GUI에서 표시 |

손 미검출, 비교하기 어려운 구도·자세에는 재촬영 안내를 반환합니다. 불확실한 판단과 실행 오류도 구분합니다. 파이프라인은 교정 PNG, 관절 JSON, 분석 JSON과 코멘트 파일을 생성합니다.

### 웹 화면과 로컬 API

- 사진 선택·미리보기·교체·삭제, 젓가락을 벌린 모습과 모은 모습의 촬영 안내 이미지를 제공합니다.
- 관절 이름을 한국어로 표시하고, 분석 설명을 목록으로 정리하며 교정 이미지를 확대해 볼 수 있습니다.
- Python HTTP API가 업로드를 받아 실제 분석 파이프라인을 실행하고 JSON 결과와 교정 PNG를 제공합니다.
- 장시간 분석은 비동기 접수 후 결과를 조회합니다. 결과 조회의 일시적 네트워크 실패는 분석을 다시 실행하지 않고 조회를 재시도합니다.
- 기본 localhost 실행과 명시적으로 설정하는 LAN 호스팅을 지원합니다. 요청별 원본·결과 보관은 서버 옵션으로 제공합니다.

### 정적 화면 공유

[GitHub Pages 데모](https://jhlee0637.github.io/no-doc-no-nrs/)는 사진 선택과 **모의 결과 화면**을 살펴보는 정적 페이지입니다. 공개 방문자의 사진을 실제 분석 서버로 보내는 연결은 구현하지 않았습니다. 최신 로컬 GUI와 게시된 정적 데모의 기능 범위도 다릅니다.

## 구현하지 못했거나 확정하지 못한 범위

- **영상·실시간 분석:** Web Camera API를 통한 5~10초 촬영, 프레임별 손·젓가락 추적과 연속 동작 분석.
- **정량 평가:** 젓가락 위치의 별도 추적과 아래 젓가락 안정성·위 젓가락 독립성·거리·교차 여부의 측정 및 점수화.
- **공개 실제 분석 서비스:** HTTPS API, 사용자 인증·TLS·사용량 제한과 GitHub Pages의 실제 분석 연결 ([#10](https://github.com/jhlee0637/no-doc-no-nrs/issues/10)).
- **GUI 입력·출력 계약 완성:** 운동 선택, 벌림/모음 기준 사진의 최종 ID·버전·손 방향·미러 정책 합의, 원본·분석 JSON의 GUI 다운로드 ([#2](https://github.com/jhlee0637/no-doc-no-nrs/issues/2)). 서버의 파일 생성·보관과 GUI 다운로드는 별개입니다.
- **최종 공동 작업 경계:** API·GUI·파이프라인 폴더와 담당 범위의 최종 합의 ([#3](https://github.com/jhlee0637/no-doc-no-nrs/issues/3)). 현재 구현 구조는 유지했습니다.
- **교정 효과 검증:** 2D 목표점의 정확성, 실제 3D 움직임·힘·압력, 반복 연습에 따른 자세 개선 효과와 다양한 손·기기·촬영 환경 검증.

해커톤 종료로 관련 이슈를 닫았으며, 미완료 항목을 구현 완료로 처리하지 않았습니다. 자세한 종료 상태는 [마무리 문서](docs/ai-generated-hackathon-closeout.md)에 남겨두었습니다.

## 기술 스택

| 영역 | 사용 기술 |
| --- | --- |
| 프론트엔드 | TypeScript, Vite, HTML/CSS |
| API·이미지 처리 | Python, Pillow |
| 손 관절·AI 분석 | MediaPipe Hand Landmarker, OpenAI Responses API (기본 모델 `gpt-4.1`) |
| 검증 | Python unittest, Playwright |

OpenCV·Web Camera API 기반 영상 분석은 초기 검토 대상이며, 현재 사진 분석 프로토타입의 구현 범위에 포함하지 않습니다.

## 로컬 실행 방법

먼저 [로컬 API 안내](docs/ai-generated-local-coach-guide.md)에 따라 Pillow를 사용할 수 있는 Python 환경을 준비합니다. 모의 API는 다음 명령으로 실행합니다.

```sh
python3 -B -m backend.app.server --mode mock --port 8000
```

다른 터미널에서 프론트엔드를 실행합니다.

```sh
npm --prefix frontend ci
npm --prefix frontend run dev
```

`http://127.0.0.1:5173/`에서 로컬 분석 서버 연결을 선택합니다. `mock` 모드는 사진 전송과 결과 표시를 확인하며 실제 AI 분석은 실행하지 않습니다.

실제 분석에는 MediaPipe 모델, 기준 사진 카탈로그, 파이프라인 실행 환경과 서버 측 API 키가 필요합니다. [파이프라인 안내](docs/ai-generated-chopstick-pipeline.md)와 [localhost 호스팅 안내](docs/ai-generated-localhost-security-guide.md)의 설정을 따릅니다. API 키는 서버에서만 사용합니다.

## 협업방식

### Codex

- 두 팀원이 각자의 Codex로 구현·검토하고, 독립 작업과 코드 검토에 서브에이전트를 활용했습니다.
- 사전 준비한 코드·자산과 행사 당일 개발 범위는 [사전 작업 공개 문서](docs/ai-generated-preparation-disclosure.md)에 구분했습니다.
- 기존 로컬 관절 검출·두 이미지 비교 모듈을 재사용했습니다. 반입한 코드와 새로 연결한 GUI·API·통합 파이프라인의 범위는 [파이프라인 안내](docs/ai-generated-chopstick-pipeline.md)에 기록했습니다.

### Git

- `jhlee0637/no-doc-no-nrs`의 이슈에서 GUI·파이프라인 계약과 담당 범위를 논의했습니다.
- 작업 브랜치의 변경을 PR로 공유하고 상대가 검토·반영하는 방식으로 협업했습니다.
- 해커톤 종료 후 병합된 작업 브랜치를 삭제하고 `main`과 정적 데모용 `gh-pages`를 유지했습니다.

## 검증 결과와 한계

- 사진 업로드, API 응답, 결과 PNG, 재촬영·오류 분기와 GUI 표시를 모의·회귀 테스트로 확인했습니다. 모의 테스트 통과와 실제 AI 판단의 정확도는 구분합니다.
- 분석 서버를 실행한 팀원 환경에서 실제 MediaPipe/GPT 분석과 교정 이미지·JSON 생성, 로컬 HTTP 왕복을 확인했습니다. 핫스팟 휴대폰 결과 표시는 해당 환경의 사용자 확인 보고입니다. 실행 기록은 [파이프라인 안내](docs/ai-generated-chopstick-pipeline.md)와 [호스팅 안내](docs/ai-generated-lan-analysis-host.md)에 남겼습니다.
- 모바일 비동기 변경의 기록에는 backend 35개·production build 통과와 실제 요청 접수 약 0.14초·결과 수신 약 20초가 있습니다. 특정 환경의 실행 사례이며 성능 보장이나 모든 기기의 연결 안정성 검증은 아닙니다.
- 화살표와 목표점은 정지 사진 위의 2D 연습 제안입니다. 정답 자세·실제 이동량·교정 효과를 입증한 결과는 아닙니다.
- 해커톤 이후 이 README에서 목표와 결과를 정리했습니다. 이 문서 갱신은 마감 당시 제출물에 기능을 추가했다는 의미가 아닙니다.

## 참고문헌
- 강경희·안성지·김형신, 「아동 소근육 발달을 위한 인터랙티브 젓가락 게임 제안」, _HCI Korea 2023_, 2023.
- Choji et al., “Factors influencing chopstick use and an objective identification of traditional holding techniques in children,” _PLOS ONE_, 2025.
- Choji et al., “Impact of a mobile application and assistive chopsticks on traditional chopstick manipulation,” _Disability and Rehabilitation: Assistive Technology_, 2026.
## 대회 정보

[해커톤 안내](https://luma.com/f7h7onav?tk=q7vnlt)
