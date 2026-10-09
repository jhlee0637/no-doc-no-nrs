---
name: codex-orchestration-local-runtime
description: 로컬 영속 큐·감시·Codex 실행·명시적 세션 재개의 운영 규약
time: "2026-10-09T10:13:14+09:00"
---

# 로컬 실행기

Python 3.10 이상·SQLite 표준 라이브러리·POSIX 파일 잠금을 사용한다. Linux·macOS·WSL 대상이며 Windows 네이티브와 네트워크 파일시스템은 미지원이다. 외부 Python 패키지·타 오케스트라이제이션 플랫폼·데몬 서버는 필요 없다.

## 실제 보장과 경계

- DB 트랜잭션으로 작업 본문·담당자·시도·claim·상태 변경과 이벤트를 저장한다. 동일 작업 ID와 동일 본문/담당자/workspace/의존성의 재등록은 중복을 만들지 않으며, 바인딩이 다르면 거부한다. 재등록으로 예약 시간을 변경하지 않는다.
- claim은 준비된 작업 한 건에 한 담당자만 허용한다. 이전 claim 토큰·시도의 늦은 결과는 거부한다. 만료된 lease를 자동 회수하거나 자동 재실행하지 않는다.
- `tick/watch`는 실행 중에만 예약 시각·선행 작업 완료·heartbeat 만료·blocked 재확인 시각을 감지한다. 이벤트는 작업·시도·종류·예약별 중복을 억제한다. `events --after`로 저장된 이벤트를 다시 읽을 수 있다. stdout과 DB 저장 사이 중단 시 알림을 못 봤을 수 있으므로, 정확히 한 번 전달/수신은 보장하지 않는다.
- 기본 watch는 AI를 호출하지 않는다. 승인된 dispatch만 `codex exec`를 실행한다. 실행 성공은 `review`로 제출하고 의미적 테스트·독립 리뷰·완료 승인은 메인이 담당한다.
- 실행기는 자체 프로세스 그룹에 TERM을 보내고 남으면 KILL로 종료 확인한다. 그룹 종료가 불확실하면 `active`와 쓰기 소유권을 유지한다. zombie·그룹에서 분리된 프로세스·호스트 종료/SIGKILL 이후에는 운영자의 실제 쓰기 종료 확인이 필요하다. 프로세스·메모리 스냅샷 복원, 기존 채팅 깨우기, Subagent 런타임 재생성은 제공하지 않는다.
- 커널 잠금·SQLite는 협조하는 로컬 운영자의 중복 실행을 막는 수단이지 같은 사용자 권한의 악성 코드에 대한 보안 격리가 아니다. 자식이 임의 도구/MCP로 승인 범위를 넘지 않도록 profile·프로젝트 지침도 검토한다.

## 상태·개인정보

항상 같은 DB 경로를 명시한다. 프로젝트에서는 `etc/orchestration/queue.sqlite3`를 후보로 사용하고, Git 제외·이미 추적된 파일 없음·공유/압축 제외를 먼저 확인한다. 테스트는 사용자가 허용한 임시 폴더에 둔다. DB·저널·잠금·`runs/`에 본문·실제 경로·세션 ID·원본 실행 로그가 저장되므로 모두 비공개다. 결과를 공개할 때는 별도로 일반화한다.

`init`는 새 DB만 생성하며 기존 DB를 덮어쓰지 않는다. 읽기 명령도 DB가 없으면 오류로 중단한다. 손상·버전 오류 시 DB를 삭제해 재시작하지 않는다. 이 구현에는 자동 백업·마이그레이션·로그 회전이 없으므로 장기 운영에서 용량과 보존 정책을 별도 검토한다.

아래 명령은 **프로젝트 루트 기준 예시**다. `WORKSPACE`는 승인한 실제 작업 폴더, `VETTED_PROFILE`은 해당 컴퓨터에서 검토한 실제 Codex profile 이름으로 치환한다. 두 값과 예시 task ID는 다른 컴퓨터에 복사되는 실행 상태가 아니다. 설치 위치가 다르면 스크립트 경로도 바꾼다.

## 등록과 기본 감시

작업 본문에는 목표·제외 범위·Skill 위치·담당 역할·수정 가능한 파일·완료 조건·허용 검증·권한을 작성한다. 본문은 등록 당시 텍스트로 저장되며 원본 파일 수정은 기존 작업을 바꾸지 않는다. 본문은 명령 셸에 넣지 않고 Codex stdin에 전달한다.

```bash
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 init
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 enqueue \
  --id example-001 --owner main --workspace WORKSPACE --brief-file etc/ai-generated-task.md
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 watch \
  --owner main --duration 60 --interval 5
```

`enqueue --delay 30`은 30초 뒤부터 준비 상태, `--depends-on example-001`은 해당 작업이 `done`이어야 준비 상태다. 의존성은 이미 존재하는 작업만 허용하므로 순환 추가를 방지한다. 선행 작업의 취소/차단은 자동 성공으로 취급하지 않는다.

watch는 전경 실행이며 지정 기간/Ctrl+C로 끝난다. 감시 종료 후 자동 깨우기는 없다. tmux·systemd·cron·로그인 시 실행·24시간 감시는 설치 및 지속 실행에 대한 별도 승인이 필요하며 이 요청만으로 등록하지 않는다. 컴퓨터가 꺼져 있는 동안 지나간 예약은 같은 DB로 watch/tick을 다시 실행할 때 확인한다.

`status`는 상태 요약, `show --id example-001`은 비공개 본문/claim 포함 상세, `events --after 0`은 이벤트 이력이다. 이 출력도 공개 로그가 아니다. 기존 이벤트가 이미 출력됐다는 이유로 작업이 처리됐다고 판단하지 않는다.

상태 변경 명령에는 방금 확인한 현재 시도를 `--attempt`로 전달한다. 아래의 `--attempt 1`은 첫 시도 예시이며 재작업 후에는 실제 시도로 바꾼다. 늦은 리뷰/복구 요청은 현재 시도와 다르면 거부된다.

## 현재 채팅의 Subagent와 연결

자동 CLI 실행이 필요 없으면 메인이 `claim --id example-001 --owner main`을 실행하고 반환된 attempt/token을 비공개로 보유한다. 실제 Subagent 생성 성공을 확인한 뒤 범위와 작업 ID·시도를 전달한다. 담당자가 실행되지 않으면 종료 확인 후 `block`한다. 메인이 진행 상태를 확인하면서 `heartbeat --id ... --attempt ... --token ...`을 갱신한다. heartbeat는 메인 생존 신호이며 구현자의 건강을 증명하지 않는다.

실제 회신을 파일로 보존한 뒤 `submit --id ... --attempt ... --token ... --result-file ...`로 `review`에 제출한다. Worker는 DB를 직접 쓰지 않는다. claim 토큰은 비공개 로컬 인수로만 사용하고 공개 기록에 넣지 않는다. SQLite 파일을 두 컴퓨터에서 공유하지 않는다.

claim은 active workspace가 같거나 상하위 관계이면 추가 claim을 거부한다. 큐 단위 병렬 실행에는 독립 worktree/폴더를 사용한다. 한 큐 작업 내부의 Codex Subagent는 메인이 파일 소유권을 나누며 기존 Skill의 제한을 따른다. `review`에 올릴 때 실제 쓰기가 끝나 있어야 한다.

## 승인된 자동 실행·깨우기

자동 실행 전 사용자가 대상 작업/workspace·profile·sandbox·기간·최대 호출 횟수·예상 비용을 승인해야 한다. 단순 알림 요청은 실행 승인이 아니다. profile의 모델·MCP·hooks·쓰기 범위가 권한과 맞는지 직접 검토하고, 설치된 `codex exec --help` 및 `codex exec resume --help`를 확인한다. 인증을 자동 생성·복사·수정하지 않는다.

```bash
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 run \
  --id example-001 --owner main --authorize-exec --profile VETTED_PROFILE \
  --sandbox read-only --timeout 120
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 watch \
  --owner main --duration 600 --interval 5 --max-runs 2 \
  --dispatch-codex --authorize-exec --profile VETTED_PROFILE --sandbox read-only --timeout 120
```

쓰기 과제만 명시적으로 `--sandbox workspace-write`를 선택한다. 기본은 read-only이며 danger-full-access·승인 우회·임의 shell hook 옵션을 제공하지 않는다. 실행기는 approval=never, OpenAI provider, 자식 명령의 network=false, 추가 writable roots 없음, 공용 임시 폴더 쓰기 제외를 명시한다. 이는 기존 상위 샌드박스를 우회하지 않으며 MCP 자체 권한까지 제한하는 보장은 아니다. profile/사용자 설정은 별도 검토가 필요하다. 모델은 검토한 profile을 사용하며 임의 대체하지 않는다.

Codex CLI 자체의 모델 통신은 필요하다. 네트워크·인증 차단 시 오류와 private 로그를 기록하고 `blocked`로 멈춘다. child agent는 큐 서버에 접근할 필요가 없고, 본문·결과는 로컬 파일/SQLite와 stdin/JSONL로 부모 실행기가 전달한다. 외부 플랫폼을 사용하지 않는다.

`--codex-bin`은 확인한 실행 파일 하나를 받으며 셸 명령 문자열이 아니다. 존재하지 않는 바이너리/지원되지 않는 옵션은 실패로 기록한다. subprocess 종료 0, `thread.started`, `turn.completed`, 최종 agent_message가 모두 있어야 `review`가 된다. 오류·timeout·중단에는 자동 재시도가 없다. 감시의 max-runs는 한 실행당 호출 상한이며 재시작해서 예산을 리셋하지 않는다.

감시 기한은 후보 선정·잠금 획득 후와 subprocess 시작 직전에 다시 확인한다. 남은 기한이 없으면 새 호출을 하지 않으며, 실행 중 timeout에도 그 기한을 적용한다. 프로세스 그룹 종료 확인을 위한 짧은 정리 시간이 감시 기간 뒤에 추가될 수 있다. 중단 처리에서는 종료 직전 JSONL의 세션 ID도 보존하므로 다음 실행에서 기록이 없다고 자동 fresh로 바꾸지 않는다.

## 리뷰와 완료

메인은 코드·검토 대상 해시·실제 테스트 결과와 독립 리뷰를 확인하고 비공개 증거 파일을 작성한다. `accept`는 이 판단을 기록하는 명령이지 증거의 진위를 자동 평가하는 엔진이 아니다.

```bash
python3 skills/codex-orchestration/scripts/orchestrate.py --db etc/orchestration/queue.sqlite3 accept \
  --id example-001 --attempt 1 --note '검토 및 실제 테스트 확인' --evidence-file etc/ai-generated-verification.md
```

수정이 필요하면 `rework --id ... --attempt ... --note '재현 근거와 수정 요청'`을 사용한다. 저장 상태는 `queued`, 시도와 repair 횟수는 증가하고 원래 담당자·세션·workspace는 유지된다. 기존 결과와 수정 요청은 이력에 보존한다. repair는 최대 2회이며 `requeue`를 결함 수정 한도 우회로 쓰지 않는다. 완료/취소 작업은 자동 재개하지 않고 새 범위에는 새 task ID를 사용한다.

## 정체·중단 후 재개

`recover`는 기록을 읽을 뿐 다시 실행하지 않는다. heartbeat 만료는 `attention-stale` 이벤트만 남기며 담당자·claim·시도를 그대로 유지한다. 감시기가 살아 있어도 작업자를 자동 교체하지 않는다.

1. `status/show/events`와 실제 파일·프로세스·자식 작업자의 쓰기 상태를 대조한다. 실행기의 local lock 해제만으로 자식 종료를 추정하지 않는다.
2. 쓰기 종료를 실제 확인하고 다음 실행 권한을 확인한 후 `requeue --id ... --attempt ... --writer-stopped --note '중단 확인 근거와 다음 행동'`을 사용한다. 이 플래그는 운영자의 확인 진술이지 자동 종료 증거가 아니다.
3. 네이티브 세션 ID가 있으면 같은 profile·sandbox·Codex 실행 파일로 `run ... --resume`을 명시한다. 저장된 실행 자세 또는 profile/base config 해시가 다르면 거부하며 `--last`나 새 세션으로 자동 대체하지 않는다. 설정 해시에는 인증 파일을 포함하지 않는다. 원래 세션 파일이 없거나 session ID가 없으면 자동 resume을 하지 않는다.
4. 아직 세션이 시작되지 않은 실패라면 승인 범위에서 새 실행을 선택할 수 있다. 원래 세션이 존재하는 작업의 강제 fresh 기능은 제공하지 않으므로 새 범위/새 작업으로 명확히 구분한다.

`block --id ... --attempt ... --note ... --wake-after 60`은 60초 뒤 blocked 재확인 알림만 예약한다. 권한·외부 의존성이 해결됐다고 추정해 실행하지 않는다. `cancel` 및 active→blocked는 active 작업자의 쓰기 종료 확인이 필요하다. 실제 Codex 실행 중에는 충돌 전환이 잠금으로 거부되지만 감시 반복 사이에는 메인이 리뷰·완료를 기록할 수 있다. 충돌 workspace는 감시가 건너뛰고 다음 독립 후보를 확인한다. 이 상태 변경을 위해 다른 프로세스를 임의로 종료하지 않는다.

## 검증과 공식 근거

```bash
python3 -B -m unittest discover -s skills/codex-orchestration/scripts -p 'test_*.py' -v
```

단위 테스트는 임시 SQLite와 모의 Codex 프로세스를 사용한다. 실제 모델 호출·인증·장시간 감시·호스트 재부팅·실제 세션 resume은 별도 승인된 통합 검증이 필요하다. 테스트 통과를 실제 세션 복구 성공으로 표현하지 않는다.

Codex의 stdin 실행·JSONL 사건·지정 세션 resume 근거: [공식 비대화형 실행 문서](https://learn.chatgpt.com/docs/non-interactive-mode). 실행 옵션은 설치 버전의 도움말이 우선이며, 해당 문서는 이 로컬 큐·잠금·재시도 정책을 보증하지 않는다.
