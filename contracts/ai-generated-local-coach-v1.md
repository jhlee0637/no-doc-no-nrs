# localhost 연결용 계약 제안

2026-10-09 당일 구현을 검토하기 위한 `local-coach-v1` 규약이다. 이슈 #2의 공동 최종 계약과 #3의 폴더 합의는 회신 대기다. 기존 `prototype-http-v1` Vite fixture와 별도이며, 외부 배포 규약으로 확정하지 않는다.

## 서버 설정과 입력

GUI는 같은 origin의 `GET /api/coach/config`를 요청마다 조회한다.

```json
{
  "schema_version": "local-coach-v1",
  "mode": "mock",
  "exercise": "basic_grip",
  "handedness": "right",
  "reference": {"id": "local-mock-reference", "version": "0"},
  "deadline_seconds": 180,
  "asset_ttl_seconds": 600
}
```

실제 분석 모드의 기준 ID·버전은 서버 관리 카탈로그에서 해석한다. 예시의 mock 기준은 실제 기준사진의 확보를 뜻하지 않는다. GUI가 파일 경로·모델·API 키·프롬프트·기준 URL을 보내지 않는다. 현재 운동 유형은 `basic_grip`, 손 설정은 `right`로 제한한다. 오른손 설정은 모델의 손 식별 정확도를 검증했다는 뜻이 아니다.

`POST /api/coach/analyze`에는 `multipart/form-data`로 아래 필드가 각각 한 번 들어간다. 브라우저가 boundary를 작성한다.

| 필드 | 값·책임 |
| --- | --- |
| `schema_version` | `local-coach-v1` |
| `request_id` | GUI가 매 요청·재시도에 생성하는 1~64자 식별자; 공백 없는 출력 가능한 ASCII |
| `exercise` | config의 운동 유형 |
| `handedness` | config의 손 설정 |
| `reference_id` | config의 `reference.id` |
| `reference_version` | config의 `reference.version` |
| `image` | 실제 JPEG/PNG 파일 한 개 |

서버는 중복·추가 필드와 설정 불일치를 거절한다. 파일은 5 MiB 이하, 1200만 픽셀 이하이며 multipart 전체는 6 MiB 이하이다. 선언 MIME·파일 형식·실제 디코딩을 확인한다. 업로드 원본 바이트를 요청별 임시 파일로 전달하며, EXIF 방향·반전의 실제 정규화는 기존 파이프라인이 담당한다. API 검증 과정에서 방향을 다시 바꾸지 않는다. 이 버전에는 사용자 촬영 반전 설정 필드가 없다.

`X-Local-Coach-Scenario: feedback|retake|error`는 mock 모드의 화면 검증용이다. 실제 분석 모드에서 분석 결과를 선택하는 입력으로 사용하지 않는다.

## 응답 봉투

최상위 필드는 다음과 같다.

| 필드 | 의미 |
| --- | --- |
| `schema_version` | `local-coach-v1` |
| `request_id` | 요청 ID; 유효한 ID를 읽지 못한 입력 오류에서는 null |
| `exercise`, `handedness`, `reference` | 서버가 지원하는 운동·손·기준 설정; 유효한 요청에서는 입력과 동일 |
| `source` | `mock`, `analysis`, `preparation` |
| `outcome` | `feedback`, `retake`, `error` |
| `feedback`, `retake`, `error` | 해당 outcome의 객체 하나만 존재하며 나머지는 null |

feedback 객체:

```json
{
  "status": "uncertain",
  "comment": "사진에서 확인할 수 있는 범위의 대표 행동 안내",
  "corrections": [{"joint_name": "관절 이름", "instruction": "교정 행동 안내"}],
  "image": {
    "url": "/api/coach/assets/<opaque>.png",
    "mime_type": "image/png",
    "width": 640,
    "height": 480
  }
}
```

`<opaque>`는 서버가 생성하는 불투명 자산 식별자의 자리표시자이며 그대로 요청하는 경로가 아니다. feedback 상태는 `assessable` 또는 `uncertain`이다. uncertain은 화면에서도 불확실성을 표시한다. corrections가 비어 있다는 이유로 올바른 자세나 차이 없음으로 해석하지 않는다. 반환 텍스트는 HTML로 삽입하지 않는다.

retake 객체는 `{reason, message}`, error 객체는 `{code, message}`이다. 내부 예외 원문·경로·키·provider 응답 ID·중간 산출물은 HTTP 응답에 포함하지 않는다. 정상 feedback·retake는 HTTP 200, 입력 오류는 4xx, 실행·서비스 오류는 5xx이다. 오류 응답도 가능한 경우 봉투로 전달하며 GUI가 HTTP 상태와 계약을 함께 확인한다.

## 파이프라인 변환

| 기존 `pipeline-1` 상태 | HTTP 결과 |
| --- | --- |
| `assessable` / `analysis` | feedback / assessable |
| `uncertain` / `analysis` | feedback / uncertain |
| `retake` / `preparation` 또는 `analysis` | retake / 같은 source |
| `error`, 비정상 종료, 손상된 manifest | error / analysis |
| `prepared`, 기타 미지원 상태 | error; 분석 완료로 표시하지 않음 |

`view_mismatch`, `not_assessable`의 retake 변환은 기존 파이프라인에서 수행한다. API는 `run_pipeline`을 중복 구현하지 않고 기존 CLI를 격리된 프로세스로 실행한다. 카탈로그·모델·실행 Python은 서버 설정이며, 결과 디렉터리는 요청마다 새로 생성한다. PNG와 manifest의 기준·형식·크기를 검사한 뒤 필요한 설명과 완성 이미지에 대해서만 공개 URL을 생성한다.

## 이미지 수명과 시간 제한

완성 PNG는 같은 origin의 `/api/coach/assets/`에서 제공한다. 원본·기준사진·landmark JSON은 제공하지 않는다. 결과 PNG는 1200만 픽셀·40 MiB 이하이며 JPEG 입력과 별도로 제한한다. 자산은 메모리에 최대 16개·총 64 MiB, 기본 600초 보관하고 만료·제거 후 404를 반환한다. 개수·용량 제한으로 오래된 자산은 TTL 이전에도 제거될 수 있다. 서버 재시작 시 URL은 무효다. `Cache-Control: no-store`를 사용한다. GUI는 실제 이미지 로드와 크기를 확인하고 실패 시 설명을 유지하며 이미지 실패를 표시한다. 이 제한·TTL·URL 규약은 공동 검토용 제안이다.

동시 분석은 한 개이며 처리 중 추가 분석은 503이다. 실제 CLI 실행에는 기본 180초의 전체 실행 제한을 두고 초과 시 자식 프로세스를 종료·회수한다. GUI는 config 조회를 포함한 대기 시간을 제한하고 서버 실행 제한에 15초의 전송 여유를 둔다. 프로세스 실행 제한은 업로드·응답 전송 전체의 실측 SLA가 아니다.

사진 교체·취소는 브라우저 요청을 중단하고 이전 응답이 화면을 덮어쓰지 못하게 한다. 브라우저 abort가 서버 계산을 즉시 취소한다는 보장은 없다. 이미 시작한 CLI는 완료 또는 서버 실행 제한까지 지속할 수 있다. 요청 임시 입력·중간 결과는 작업 종료 시 제거한다.

정상 서버 종료는 진행 중인 handler의 실행 제한과 임시 자료 정리가 끝날 때까지 기다린다. 따라서 활성 분석이 있으면 종료가 즉시 완료되지 않을 수 있다. 강제 프로세스 종료 후 정리를 검증한 기능은 아니다.

## 검증의 경계

mock에서 실제 파일 전송·서버 입력 검증·별도 PNG 조회·GUI 표시를 검증한다. 합성 mock 이미지는 사용자의 사진을 분석한 결과가 아니다. CLI 실행 경계·상태 변환·시간 초과는 외부 모델 호출 없는 시험으로 검증할 수 있다. 실제 MediaPipe/GPT 실행·정확도·실제 기준사진 매핑은 별도 자료와 환경을 갖추고 재검증해야 한다.
