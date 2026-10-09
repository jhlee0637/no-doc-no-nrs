# LAN 분석 서버와 요청별 데이터 보관

기본 loopback 바인딩을 유지하면서 --host와 --allowed-host로 같은 네트워크의 명시적 주소를 제공할 수 있다. 일반 production GUI는 로컬 분석 서버를 기본 선택하며 loopback 및 RFC1918 IPv4에서 같은 origin API를 사용한다. 정적 offline 화면은 기존 모의 동작을 유지한다. API 키는 서버 환경변수 OPENAI_API_KEY로 설정하며 프런트엔드에 주입하지 않는다.

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python -m backend.app.server --mode analysis --host 0.0.0.0 --port 8000 \
  --allowed-host '<LAN_IP>:8000' --frontend-dir frontend/dist \
  --catalog '<CATALOG_FILE>' --landmarker-model '<MODEL_FILE>' \
  --pipeline-python '<PYTHON_EXECUTABLE>' --confidence 0.1 \
  --analysis-root '<ANALYSIS_ROOT>'
```

자리표시자는 해당 PC의 사설 IPv4, 서버 관리 reference 카탈로그, MediaPipe 모델, 의존성이 설치된 Python 실행파일, 비공개 분석 보관 폴더로 바꾼다. Python 환경은 scripts/chopstick_pipeline/requirements.txt를 사용한다. 실제 환경에 필요한 런타임 라이브러리 경로도 서버 환경에 설정한다. Windows/WSL2에서는 Windows LAN IP에서 WSL IP로 TCP 포트를 전달하고 방화벽을 같은 네트워크 범위로 제한해야 한다. IP 변경 시 전달 및 allowed-host 설정도 갱신한다.

## 보관 구조

--analysis-root를 지정하면 요청 분석 시작 시각을 KST 마이크로초로 기록하고 YYYYMMDD_HHMMSS_ffffff_<unique> 폴더를 독점 생성한다. 고유 suffix는 동시 요청 충돌을 방지한다. request.json에는 시작/종료 시각과 완료/실패 상태가 기록된다. 원본 업로드는 검증된 query.jpg 또는 query.png로 바이트 그대로 보존한다. output에는 생성된 관절 이미지/JSON, assessment.json, correction.png, comments.txt, result.json이 남는다. 검출 실패 시 GPT assessment와 교정 이미지는 생성되지 않는다. GPT 재촬영 판정에도 검증된 assessment.json은 저장한다. 실패/타임아웃의 중간 파일과 subprocess 로그도 비공개로 보관한다. 자동 삭제 정책은 추가하지 않는다. --analysis-root 미지정 시 기존 임시 파일 정리를 유지한다.

API 어댑터는 최대20개 correction과 analysis/pose_mismatch를 허용한다. GUI 다운로드 확장 계약은 이슈 #2의 별도 제안이며 이 변경이 JSON·원본을 공개 URL로 제공하는 구현은 아니다. 기존 교정 PNG만 제한된 asset 캐시로 전달한다.

## 검증과 접속 범위

실제 PC LAN 주소로 HTTP 업로드→MediaPipe→GPT→feedback10개→PNG 조회200과 마이크로초 요청 폴더·원본·결과 보존을 확인했다. 이 검증은 같은 PC에서 LAN 주소를 사용한 시험이다. 처음 Wi-Fi에서는 휴대폰 ERR_ADDRESS_UNREACHABLE이 보고됐다. 핫스팟으로 연결을 바꾸고 PC별 Host·포트 전달·방화벽 주소를 갱신한 뒤 사용자가 휴대폰에서 페이지 및 분석 결과 표시 성공을 확인했다. 초기 네트워크 실패의 정확한 원인은 확정하지 않았다. 앱 인증/TLS는 이번 변경에 포함하지 않으며 인터넷 공개 서버로 사용하지 않는다. 허용 Host/Origin 검사는 사용자 인증이 아니다.

백엔드 회귀, 프런트엔드 production/offline build와 주소 경계 검증을 수행했다. 전체 브라우저 회귀는 이미 실행 중인8000 서버와 fixture 포트 충돌로 시작하지 못했다. 실제 사진·결과·키·IP와 PC별 시작/방화벽 스크립트는 Git 제외 자료로 유지한다.

분석 요청의 네트워크 오류는 서버 설정 조회와 사진 업로드·분석 응답 수신 단계를 구분해 표시한다. 서버 응답 전송 실패는 예외 종류만 기록하며 키·원본·요청 경로는 기록하지 않는다. 핫스팟 시험 중 한 요청은 서버 분석 완료 뒤 화면 오류가 보고됐고, 재빌드·서버 재시작 후 사용자가 성공을 확인했다. 원인 해결을 특정 코드 변경의 효과로 단정하지 않는다.

모바일 장시간 응답 연결 실패를 줄이기 위해 GUI 분석 요청은 X-Coach-Async:1로 즉시202 접수 후 1초 간격으로 같은 origin의 토큰 job URL을 조회한다. pending202 뒤 기존 결과 envelope를 반환하고, 조회 네트워크 실패는 전체195초 시간 내 재시도한다. 분석을 다시 실행하지 않는다. 작업 보관은 최대32개/600초이며 교정asset 기존 수명은 유지한다. 기존 동기API 소비자는 변경하지 않는다. 실제 시험에서 접수0.14초, 완료feedback200 약20초를 확인했다. 모바일 재시험은 사용자가 수행해야 한다.
