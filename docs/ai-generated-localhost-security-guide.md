# localhost 호스팅과 접근 제한

2026-10-09 당일 구현한 단일 사용자 로컬 검증 구성이다. 웹페이지의 빌드 결과와 파이프라인 API를 같은 `http://127.0.0.1:8000` 주소에서 제공한다. 인터넷·LAN 공유와 배포 인증은 포함하지 않는다.

## 실행

프로젝트 루트에서 아래 순서로 실행한다. Node.js와 Pillow를 사용할 수 있는 Python이 필요하며, 의존성 준비는 [연결 안내](ai-generated-local-coach-guide.md)를 따른다.

```sh
cd frontend
npm ci
npm run check
npm run build
cd ..
python3 -B -m backend.app.server --mode mock --port 8000 --frontend-dir frontend/dist
```

브라우저에서 `http://127.0.0.1:8000/`을 연다. 연결 방식의 **localhost 파이프라인 API**를 선택하면 실제 파일 업로드·mock 응답·합성 PNG 표시를 검증한다. 기본 브라우저 화면 예시는 서버에 전송하지 않는다. 빌드 화면에는 Vite 전용 HTTP fixture를 표시하지 않는다. 같은 포트에 기존 API가 실행 중이면 그 서버를 먼저 종료한다.

실제 분석은 연결 안내의 `--mode analysis` 설정에 `--frontend-dir frontend/dist`를 더한다. 키는 서버 환경에만 둔다. mock 실행은 외부 모델을 호출하지 않으며, analysis 실행은 이미지와 분석 자료를 외부 모델로 전송할 수 있다. 유효한 인증과 입력 이미지 검출은 별도 확인이 필요하다.

## 적용한 경계

- 서버는 `127.0.0.1`에만 바인딩한다. 요청의 Host는 해당 포트의 `127.0.0.1` 또는 `localhost`와 정확히 일치해야 한다.
- Origin과 Fetch Metadata를 검사한다. 외부 Origin, `null`, 중복 헤더와 cross-site 요청을 거부한다. API에는 개발 GUI의 두 origin도 허용한다. Origin 없는 로컬 CLI 요청은 허용한다.
- 정적 파일은 빌드 디렉터리의 `index.html`과 `assets/`·`fonts/`의 허용 확장자만 제공한다. 경로 이동·인코딩된 구분자·심볼릭 링크·디렉터리 목록·JSON·source map·개인 설정 경로는 제공하지 않는다. 빌드 폴더는 신뢰할 수 있는 빌드 결과만 보관한다.
- 빌드 서버의 CSP는 자체 스크립트·스타일·폰트·API 연결만 허용한다. 미리보기 이미지는 blob/data를 허용한다. iframe 삽입, 객체 삽입과 외부 연결을 차단한다.
- 응답에는 `no-store`, `nosniff`, `no-referrer`, `X-Frame-Options: DENY`를 적용한다. 업로드의 크기·형식·디코딩·픽셀 수를 검증하고 서버 작업에는 시간 제한을 둔다.
- API 키와 파이프라인 환경은 브라우저에 전달하지 않는다. 작업별 임시 파일은 정리하며 결과 이미지는 제한된 메모리 캐시에 보관한다. 원본 파일을 정적 경로로 재공개하지 않는다.

개발할 때는 `npm run dev`의 `127.0.0.1:5173`을 사용할 수 있다. 개발 서버도 정확한 Host/Origin 검사, 파일 접근 제한과 iframe 차단을 적용한다. HMR을 사용하는 개발 서버에는 빌드 서버의 전체 CSP를 적용하지 않는다. [Vite 공식 문서](https://vite.dev/config/server-options)는 바인딩·Host·CORS·파일 접근 설정의 의미를 설명한다.

## 보장 범위와 검증

이 설정은 다른 웹사이트와 실수로 열린 파일 경로로부터 로컬 서비스를 보호하는 경계다. 같은 컴퓨터의 프로세스·브라우저 확장·사용자 계정이 이미 침해된 상황을 격리하는 인증 시스템은 아니다. 브라우저 취소는 이미 시작한 서버 분석의 즉시 종료를 보장하지 않는다. LAN이나 인터넷 공유가 필요해지면 인증·TLS·배포 서버를 별도로 설계한다. Python HTTP 서버 기반 구현은 공개 서비스용 운영 서버로 검증한 구성이 아니다. [Python 공식 문서](https://docs.python.org/3/library/http.server.html)

2026-10-09 구현 환경에서 backend 시험 28개, Chromium 시험 39개, 타입 검사와 빌드가 통과했다. 실제 HTTP 파일 제공·업로드, Host/Origin 거부, 인코딩 경로 이동, 내부·외부 심볼릭 링크, 합성 비공개 파일 canary와 보안 응답 헤더를 확인했다. 추가로 빌드 서버의 실제 브라우저 업로드·mock JSON·PNG 32×24 표시·파일 지우기·로컬 폰트 로딩이 통과했고 CSP 위반·페이지 오류·외부 요청은 0건이었다. 별도 빌드 시험의 취소 동작은 응답 완료와의 경쟁으로 검증하지 못했으며, 개발 GUI의 취소·늦은 응답 시험은 39개에 포함된다. mock 검증 결과를 실제 사진 분석의 정확도나 공개 배포 준비로 해석하지 않는다.
