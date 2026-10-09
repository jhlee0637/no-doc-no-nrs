# localhost GUI 프로토타입 검증

2026-10-09 당일 구현한 웹 화면 프로토타입이다. TypeScript·HTML/CSS·Vite를 사용하며,
JPEG/PNG 파일 선택·미리보기·교체·삭제와 모의 교정·재촬영·서비스 오류 화면을 제공한다.
기본 모드는 브라우저 내부 모의 처리다. 추가 HTTP 모의 모드에서는 localhost 개발 서버로
실제 파일을 전송하고 모의 JSON·별도 합성 PNG를 조회한다. 실제 분석 파이프라인은 연결하지 않았다.
모의 데이터 타입은 공개 API 계약이 아니다. I/O 계약은 이슈 #2, 폴더·담당 경계는 이슈 #3에서 합의한다.

## 실행

아래 명령은 저장소 루트에서 시작한다. Vite의 Node 요구사항은 `^20.19.0 || >=22.12.0`이며,
작성 환경에서 Node 24.15.0·npm 11.12.1로 확인했다. 다른 환경의 설치·실행은 별도 재검증한다.

```bash
cd frontend
npm ci
npm run dev
```

브라우저에서 `http://127.0.0.1:5173/`를 연다. 서버는 localhost에만 바인딩하며
포트가 사용 중이면 다른 포트로 자동 이동하지 않고 종료한다. 서버 종료는 해당 터미널의 Ctrl+C다.
웹 배포는 이 프로토타입의 검증 범위에 포함하지 않는다.

## 검증

다음 명령은 `frontend/`에서 실행한다. 브라우저 다운로드는 각 컴퓨터에서 한 번 필요하며,
인증·실행 프로세스·로컬 브라우저 캐시는 저장소 복사만으로 이전되지 않는다.

```bash
npm run build
PLAYWRIGHT_BROWSERS_PATH=../etc/gui-prototype/browsers npm exec -- playwright install chromium --only-shell
PLAYWRIGHT_BROWSERS_PATH=../etc/gui-prototype/browsers npm test
```

브라우저 명령은 Linux·macOS·WSL 셸 형식이다. 호스트에 Playwright 실행용 시스템 라이브러리가
필요할 수 있다. 테스트는 포트 5173의 기존 개발 서버를 재사용하거나 서버를 시작한다.
해당 포트가 이 프로젝트의 개발 서버인지 확인한다. 테스트 출력은 Git 제외 `etc/gui-prototype/test-results/`에 저장한다.

작성 환경에서 타입 검사·Vite 빌드와 실제 Chromium 테스트 18개가 통과했다.
테스트 사진은 브라우저 canvas로 생성한 고정 색상 이미지로, 실제 손 자세나 분석 정확도 검증 자료가 아니다.

- 실제 파일 디코딩·미리보기, 모의 안내와 서버 전송 없음
- 손상된 이미지 거부 및 이전 결과 제거
- 요청 취소·재시도와 사진 교체 시 늦은 결과 차단
- 디코딩 순서 역전, 같은 파일 재선택, object URL 해제
- 재촬영·서비스 오류 화면 구분
- 모바일 화면 너비와 키보드 파일 선택

데스크톱·모바일 화면에서 한글 표시도 로컬 확인했다. JPEG/PNG 헤더·브라우저 디코딩 검사는
현재 화면 입력 검증이며 향후 서버 업로드 제한·정규화·좌표 계약을 대신하지 않는다.

## 실제 HTTP 모의 연결

`npm run dev`로 실행한 화면에서 **모의 연결 방식 → localhost HTTP 모의 서버**를 선택한다.
사진 선택 후 결과 보기를 누르면 같은 개발 서버의 `/__prototype__/analyze`로 실제 multipart를
전송하고, 모의 JSON을 받은 뒤 `/__prototype__/assets/correction.png`를 별도 조회·표시한다.
이는 색상 패턴으로 생성한 32×24 PNG이며 업로드한 사진의 교정 결과가 아니다.
기본 브라우저 모드는 기존처럼 사진을 전송하지 않는다.

이 fixture는 [Vite configureServer](https://vite.dev/guide/api-plugin.html#configureserver)로
개발 서버에만 연결했다. 빌드·preview에서는 HTTP fixture가 제공되지 않으므로 브라우저 모드를 사용한다.
업로드는 메모리에서 해석하고 디스크·로그에 보관하지 않는다. 테스트용 전체 multipart 한도는 6MiB이며,
실제 API 업로드 제한이나 이미지 정규화·디코딩 검증 규칙을 확정한 값이 아니다.

아래 값은 **공동 합의 전 테스트 전용 값**이다. 응답은 GUI 내부 `DemoOutcome` 형식이며
공개 API의 snake_case envelope·버전 정책을 구현하거나 확정한 것이 아니다.

| multipart 필드 | 테스트 값 |
| --- | --- |
| `image` | 선택한 JPEG/PNG 파일 1개 |
| `schema_version` | `prototype-http-v1` |
| `request_id` | 요청마다 생성한 ID |
| `exercise` | `chopsticks` |
| `handedness` | `right` |
| `reference_id` | `prototype-reference` |
| `reference_version` | `0` |

모의 화면 선택은 테스트용 `X-Prototype-Scenario` 헤더로 전달한다. 기준 이미지를 조회하거나
모델을 호출하지 않는다. 응답의 테스트 전용 `receipt`는 서버가 실제 수신한 필드·파일 크기·SHA-256을
반환해 업로드 바이트 전달을 검증하며 공개 계약의 필드가 아니다.

추가 HTTP 시험 10개는 실제 수신 파일 크기·해시, 별도 PNG 조회·크기, 취소·교체,
잘못된 요청 ID·출처·외부 이미지 URL 거부, 이미지 실패, HTTP 오류·재시도,
모의 재촬영·오류 상태, 중복 필드 거부를 확인한다.
브라우저 취소 검증은 서버 분석 중단이나 결과 파일 정리까지 보장한다는 뜻이 아니다.

## 파일과 외부 자산

| 위치 | 역할 |
| --- | --- |
| `frontend/src/main.ts` | 화면·사진 선택·요청 상태·모의 결과 표시 |
| `frontend/src/prototype.ts` | GUI 내부 모의 응답 타입·취소 가능한 모의 처리 |
| `frontend/src/api/prototype-http.ts` | localhost fixture 업로드·응답 검증 |
| `frontend/dev/` | 개발 서버 전용 mock·합성 PNG |
| `frontend/src/styles.css` | 반응형 화면·로컬 글꼴 |
| `frontend/tests/prototype.spec.ts` | 브라우저 동작 검증 |
| `frontend/public/fonts/` | Noto Sans KR 원본 글꼴·OFL 라이선스·출처 |

TypeScript 7.0.2·Vite 8.3.4·Playwright 1.64.0은 개발 의존성으로 고정하고 lockfile을 포함했다.
Noto Sans KR은 [Google Fonts 원본](https://github.com/google/fonts/tree/main/ofl/notosanskr)을
SIL Open Font License 1.1에 따라 포함했다. 원본 글꼴 데이터는 수정하지 않았고
`OFL.txt`와 `ai-generated-source.json`에 라이선스·출처·사용 범위를 기록했다.
이 외부 자산을 팀이 만든 글꼴로 표시하지 않는다.

## 다음 연결 단계

이슈 #2에서 실제 JSON·공유 이미지·기준 ID/version·결과 URL·제한·시간 예산·취소 의미를 확정한 뒤
테스트 전용 HTTP 어댑터를 실제 공개 계약에 맞춰 연결한다.
HTTP fixture 검증과 실제 파이프라인 통합·분석 정확도 검증은 구분한다.
실제 교정 이미지 자산은 제공 대기 상태다.
