---
name: "OpenRig 설치·검증 인계 문서"
description: "OpenRig 설치 환경, 덧셈 검증 결과, 실행·종료 방법과 제한사항을 정리한 에이전트 인계 문서"
time: "2026-10-08T14:49:49+09:00"
---

# OpenRig 설치·검증 인계 문서

작성일: 2026-10-08, Asia/Seoul. 설치·덧셈 검증은 13:56~14:26 수행했으며, 문서 작성 시 설치 점검과 에이전트 상태를 재조회했다.

## 1. 결론과 작업 범위

전용 Conda 환경에 OpenRig 0.6.6 설치 완료. OpenRig로 Codex 에이전트 한 개를 실행하고 덧셈 요청을 전달해 `결과: 5` 응답까지 확인했다. 다중 에이전트 협업 전체가 검증된 상태는 아니다.

사용자는 ChopCoach 해커톤 시작 전 계획과 환경 준비에 집중하고 있다. 앱 구현, 새 모델 학습, 저장소 이동·푸시는 이번 작업 범위에 포함되지 않는다. 이 문서는 설치 결과와 이어받기 방법을 전달할 뿐, 에이전트 교체나 추가 실행을 자동 승인하지 않는다.

인계받는 에이전트는 저장소의 최신 `AGENTS.md`를 먼저 읽는다. 현재 규칙은 README 수정 시 사용자 허가 필요, 에이전트 작성 문서의 파일명에 `ai-generated-` 접두사 사용이다.

## 2. 설치 환경과 경로

이 문서는 다른 소유자의 컴퓨터와 인터넷 공개를 전제로 한다. 사용자명, 개인 홈 경로, 작성 환경의 임시 디렉터리 식별자, 실제 rig ID와 세션 UUID는 제거했다. 아래 자리표시자는 실제 설치 경로가 아니며, 새 환경의 값으로 교체해야 한다.

개인화된 로컬 운영 기록은 Git 제외 대상인 `etc/`에 별도로 보관한다. 외부 전달이나 압축 공유 시 해당 폴더를 포함하지 않는다. 공개 문서는 그 비공개 기록에 접근하지 않아도 이해할 수 있도록 작성한다.

| 자리표시자 | 대상 환경에서 지정할 값 |
| --- | --- |
| `<PROJECT_ROOT>` | 저장소를 복제한 프로젝트 루트 |
| `<CONDA_ENV_PREFIX>` | `conda env list` 등으로 확인한 openrig 환경의 절대 경로 |
| `<CODEX_BIN_DIR>` | `command -v codex`로 확인한 실행 파일의 디렉터리 |
| `<CODEX_HOME>` | 해당 소유자의 Codex 설정·상태 루트; 기본 위치는 `~/.codex` |
| `<TEST_ROOT>` | 해당 컴퓨터에서 새로 준비한 테스트 전용 절대 경로 |

셸 예시에서는 `OPENRIG_ENV_PREFIX`, `OPENRIG_TEST_ROOT`, `OPENRIG_CODEX_BIN_DIR`를 사용한다. 이 값들은 각 새 셸에서 지정해야 한다. 기존 로그인 정보는 공유하지 말고, 새 소유자가 자신의 계정으로 Codex 로그인한다. 아래 설치 버전과 결과는 작성 환경의 검증 기록이다.

### 작성 환경의 설치 결과

| 항목 | 확인값 |
| --- | --- |
| 운영 환경 | WSL Ubuntu 24.04, Bash |
| 프로젝트 | `<PROJECT_ROOT>` |
| Conda 환경 | `openrig` |
| 환경 경로 | `<CONDA_ENV_PREFIX>` |
| OpenRig | `0.6.6 (2620dea8)` |
| Node.js / npm | `24.21.0` / `11.19.0` |
| tmux | `3.4` |
| Codex CLI | `0.161.0`, `<CODEX_BIN_DIR>/codex` |
| 인증 | 기존 WSL Codex의 ChatGPT 로그인 재사용 |
| OpenRig 패키지 | `<CONDA_ENV_PREFIX>/lib/node_modules/@openrig/cli` |
| Codex 테스트 프로필 | `<CODEX_HOME>/example-codex.config.toml` |

대상 프로젝트는 [mvschwarz/openrig](https://github.com/mvschwarz/openrig)이며, 설치한 npm 패키지는 `@openrig/cli@0.6.6`이다. Claude 런타임은 사용하지 않았다. `cmux`는 설치하지 않았으며, 현재 tmux 테스트에는 필요하지 않았다.

### 설치 과정에서의 주의점

- Conda 환경은 `conda-forge`에서 Node.js 24와 tmux 3.4를 설치해 생성했다. Python 기반 환경으로 구성한 것은 아니다.
- 이 실행 환경에서는 `conda activate openrig` 또는 `conda run`만으로 Node.js 선택이 보장되지 않았다. 기존 nvm의 Node.js 24.15.0이 먼저 선택되는 현상을 관찰했다.
- 원인을 Conda 자체 문제로 단정하지 않는다. 설치·검증에는 환경 내부 Node.js의 절대 경로와 명시적 npm prefix를 사용했다.
- npm 설치 시 postinstall이 자동 실행되지 않았으므로, 패키지의 `scripts/check-abi.mjs`를 직접 실행했다. Node.js와 better-sqlite3 호환성 검사 통과.
- 제한된 상위 샌드박스에서는 ABI 검사 중 자식 프로세스 생성이 `EPERM`으로 실패했다. 승인받은 실행에서 통과했으며, 이를 ABI 불일치로 판단하지 않았다.
- `rig setup`은 `--dry-run`만 수행했다. 기본 kernel을 포함한 전체 초기 설정 완료로 표현하면 안 된다.

아래는 경로를 일반화한 참고용 명령이다. 작성 환경에서는 설치 완료 상태였지만, 다른 컴퓨터의 설치 상태는 따로 확인해야 한다. 설치·실행 전 해당 컴퓨터 소유자의 승인을 받는다.

```bash
conda create --name openrig --override-channels --channel conda-forge nodejs=24 tmux=3.4 --yes

# 아래 값은 대상 컴퓨터에서 확인한 경로로 반드시 교체한다.
export OPENRIG_ENV_PREFIX="<CONDA_ENV_PREFIX>"
export OPENRIG_TEST_ROOT="<TEST_ROOT>"
export OPENRIG_CODEX_BIN_DIR="<CODEX_BIN_DIR>"

env PATH="$OPENRIG_ENV_PREFIX/bin:$OPENRIG_CODEX_BIN_DIR:/usr/bin:/bin" \
  "$OPENRIG_ENV_PREFIX/bin/node" \
  "$OPENRIG_ENV_PREFIX/lib/node_modules/npm/bin/npm-cli.js" \
  install --global --prefix "$OPENRIG_ENV_PREFIX" \
  --cache "$OPENRIG_TEST_ROOT/npm-cache" @openrig/cli@0.6.6

"$OPENRIG_ENV_PREFIX/bin/node" \
  "$OPENRIG_ENV_PREFIX/lib/node_modules/@openrig/cli/scripts/check-abi.mjs"
```

## 3. 테스트 구성과 예시 이름

| 항목 | 값 |
| --- | --- |
| 임시 루트 | `<TEST_ROOT>` |
| 작업 디렉터리 | `<TEST_ROOT>/work` |
| OpenRig 상태 | `<TEST_ROOT>/state` |
| 공유 문서 루트 | `<TEST_ROOT>/shared-docs` |
| RigSpec | `<TEST_ROOT>/spec/rig.yaml` |
| AgentSpec | `<TEST_ROOT>/spec/agents/calculator/agent.yaml` |
| 인스턴스용 래퍼 | `<TEST_ROOT>/rig` |
| 데몬 | `http://127.0.0.1:17433` |
| rig 이름 | `demo-rig` |
| logical ID | `math.calculator` |
| tmux／canonical session | `math-calculator@demo-rig` |
| 런타임 / 모델 | Codex / `gpt-6.1-sol` |
| reasoning effort | `low` |

작성 환경에서 검증 당시 조회 결과는 `sessionStatus=running`, `startupStatus=ready`, `agentActivity.state=idle`, 할당된 작업 없음이었다. 이는 과거 검증 기록이며, 다른 컴퓨터에 해당 데몬이나 에이전트가 존재한다는 뜻이 아니다. 새 소유자의 환경은 별도로 구성하고 확인한다.

작성 환경의 임시 루트는 영구 보관하지 않았다. 재부팅·임시 영역 정리 후 사라질 수 있다. Conda 환경과 Codex 프로필이 남아 있어도 래퍼와 RigSpec의 존재 여부는 별도로 확인한다.

## 4. 실행 래퍼와 권한 설정

일반 `rig` 명령은 다른 OpenRig 인스턴스를 선택할 수 있으므로, 이번 테스트에는 아래 래퍼를 사용한다. 환경 내부 Node.js를 직접 지정해 nvm 경로 간섭을 피한다.

`<TEST_ROOT>/rig`에 저장하고 실행 권한을 부여할 래퍼 예시다. 작성 환경에서 검증한 래퍼를 환경 변수 기반으로 일반화한 것이며, 이 변형 자체는 다른 컴퓨터에서 재검증해야 한다.

```sh
#!/bin/sh
: "${OPENRIG_ENV_PREFIX:?Conda 환경 경로 지정 필요}"
: "${OPENRIG_TEST_ROOT:?테스트 루트 경로 지정 필요}"
: "${OPENRIG_CODEX_BIN_DIR:?Codex 실행 파일 디렉터리 지정 필요}"
export PATH="$OPENRIG_ENV_PREFIX/bin:$OPENRIG_CODEX_BIN_DIR:/usr/bin:/bin"
export OPENRIG_HOME="$OPENRIG_TEST_ROOT/state"
export OPENRIG_SHARED_DOCS_ROOT="$OPENRIG_TEST_ROOT/shared-docs"
export OPENRIG_PORT=17433
export OPENRIG_RUNTIME_CODEX_HOOKS_ENABLED=false
export OPENRIG_CONTEXT_SYSTEM_WORLD=disabled
export OPENRIG_ONBOARDING_DEFAULT_PACK_ENABLED=false
export OPENRIG_YOLO=0
exec "$OPENRIG_ENV_PREFIX/bin/node" "$OPENRIG_ENV_PREFIX/lib/node_modules/@openrig/cli/dist/bin-wrapper.js" "$@"
```

`<CODEX_HOME>/example-codex.config.toml`의 내용:

```toml
model = "gpt-6.1-sol"
model_reasoning_effort = "low"
sandbox_mode = "workspace-write"
approval_policy = "never"

[sandbox_workspace_write]
network_access = false
exclude_slash_tmp = true
exclude_tmpdir_env_var = true
writable_roots = []

[mcp_servers.aws-mcp]
enabled = false
```

처음에는 `read-only`를 시도했으나, OpenRig가 `--add-dir`로 추가 쓰기 경로를 전달하는 구성과 충돌해 실행에 실패했다. 이후 제한된 `workspace-write`로 변경했다. `writable_roots=[]`만 보고 읽기 전용으로 해석하면 안 된다. 실제 작업 폴더와 CLI로 추가한 폴더는 쓰기 범위에 포함된다. `--add-dir`의 의미는 [Codex CLI 공식 문서](https://learn.chatgpt.com/docs/cli/reference)에 명시되어 있다.

Codex 실행 기록에서 확인한 실제 쓰기 범위:

- `<TEST_ROOT>/work`
- `<TEST_ROOT>/work/.git`
- `<TEST_ROOT>/shared-docs/rigs/demo-rig/state/math`

`/tmp`와 `TMPDIR` 전체에 대한 기본 쓰기 허용을 제외하고, 명령 네트워크 접근을 끈 설정이다. 승인 정책은 `never`이다. 설정 항목의 의미는 [Codex 설정 공식 문서](https://learn.chatgpt.com/docs/config-file/config-reference)를 참고한다.

Conda는 의존성 분리 수단이며 보안 샌드박스가 아니다. 위 제한은 자식 Codex의 명령 실행 정책이다. 호스트에서 실행하는 OpenRig 데몬 자체를 동일한 정책으로 가둔 것은 아니며, 컨테이너·VM 수준의 완전한 격리나 호스트 파일 읽기 차단도 제공하지 않는다. 모델 응답에 필요한 Codex 자체 통신까지 끈 것으로 해석하지 않는다.

### 호스트에 남은 변경

- 전용 Conda 환경과 그 내부 npm 패키지 설치.
- 별도 Codex 테스트 프로필 생성; 테스트 프로필에서 AWS MCP 비활성화.
- `<CODEX_HOME>/config.toml`에 테스트 작업 폴더의 `trust_level="trusted"` 항목 추가 확인.
- `~/.agents/skills/openrig-skills/SKILL.md`와 `~/.claude/skills/openrig-skills/SKILL.md` 생성 확인.
- 테스트 작업 폴더의 `AGENTS.md`는 OpenRig가 생성한 파일이며, 프로젝트 저장소의 `AGENTS.md`와 다름.
- Windows `.codex`를 직접 공유하지 않고 WSL 자체 설정·인증 사용.

즉, `OPENRIG_HOME`을 분리했어도 호스트 설정 변경이 전혀 없었던 것은 아니다. 정리 시 기존 사용자 설정을 통째로 덮어쓰거나 전역 스킬을 무조건 삭제하지 않는다.

## 5. 검증 결과와 증거

| 확인 항목 | 결과와 해석 |
| --- | --- |
| 설치·실행 버전 | OpenRig 0.6.6, Node.js 24.21.0, tmux 3.4 재확인 |
| SQLite 네이티브 모듈 | 설치 당시 ABI 검사 통과 |
| `rig doctor --json` | 문서 작성 시 `healthy: true`; cmux 미설치는 경고 |
| Spec와 현재 토폴로지의 일치 | 기본 doctor에서 건너뜀; `--spec` 검증 미실시 |
| Codex 에이전트 실행 | 단일 에이전트 running / ready 확인 |
| 요청 전달 | `rig send --raw --verify --json`의 delivered / verified 성공 |
| 실제 계산 응답 | `2 + 3`에 대해 `결과: 5` 확인 |
| 적용된 권한 정책 | transcript의 `turn_context`에서 실제 정책 확인 |
| 제한 우회·침투 테스트 | 미실시; 정책 확인을 완전한 보안 검증으로 표현하지 않음 |
| 다중 에이전트 협업 | 미실시 |

덧셈 응답 시각은 2026-10-08 14:23:29 KST. 원본 실행 기록은 작성 환경에만 남아 있으며 공개 문서에는 세션 식별자와 실제 파일명을 넣지 않는다. 아래는 기록 위치의 패턴일 뿐, 다른 컴퓨터에서 접근 가능한 증거 파일이 아니다. 인증 파일이나 전체 전역 설정도 복사하지 않았다.

```text
<CODEX_HOME>/sessions/<YYYY>/<MM>/<DD>/rollout-<SESSION>.jsonl
```

작성 환경에서 확인한 원본 기록의 `response_item` 및 `task_complete`에 `결과: 5`가 기록되어 있다. `turn_context`에는 작업 경로, 모델, `approval_policy=never`, `network_access=false`, 두 임시 경로 제외 설정이 기록되어 있다.

제한된 자식 Codex에서는 자체 `rig` 명령으로 로컬 데몬에 접속할 수 없었다. 외부 운영자가 메시지를 전달하고 에이전트가 텍스트로 응답하는 흐름만 성공했다. 따라서 현재 설정을 에이전트 간 메시지·큐 조정까지 가능한 다중 에이전트 운영 구성으로 소개하면 안 된다.

## 6. 대상 환경에서의 조회·테스트·종료 명령

아래 명령은 새 소유자의 환경에 테스트 구성이 준비되어 있을 때만 적용한다. 먼저 파일 존재와 해당 환경의 현재 상태만 확인한다. 제한된 상위 에이전트 환경에서는 로컬 데몬 접근도 차단되어 `Daemon not running`처럼 보일 수 있다. 작성 환경에서는 일반 실행에서 그 메시지가 나왔지만, 승인받은 조회에서는 실행 중임을 확인했다. 조회 실패만으로 데몬을 재시작하거나 중복 실행하지 않는다.

```bash
test -x "$OPENRIG_TEST_ROOT/rig"
"$OPENRIG_TEST_ROOT/rig" --version
"$OPENRIG_TEST_ROOT/rig" doctor --json
"$OPENRIG_TEST_ROOT/rig" ps --nodes --rig demo-rig --json
```

화면 연결과 기존 응답 확인:

```bash
"$OPENRIG_ENV_PREFIX/bin/tmux" attach-session -t math-calculator@demo-rig
```

tmux 기본 키 설정에서 `Ctrl+b`, 이어서 `d`를 누르면 세션을 종료하지 않고 화면에서 빠져나온다.

추가 테스트를 요청받은 경우에만 실행한다. 메시지 전송은 읽기 전용 조회가 아니며 모델 사용량이 발생할 수 있다.

```bash
"$OPENRIG_TEST_ROOT/rig" send math-calculator@demo-rig \
  '덧셈 테스트입니다. 2 + 3을 계산해 주세요. 도구 실행이나 파일 변경 없이 답변만 해 주세요. 답변은 결과: <계산값> 형식의 한 줄로 작성해 주세요.' \
  --raw --verify --json
```

`delivered=true`나 `verified=true`는 메시지 전달 증거다. 계산 성공을 판단하려면 화면 또는 Codex 원본 기록에서 실제 응답을 확인해야 한다.

종료 요청을 받으면 해당 테스트 rig부터 종료하고 데몬을 종료한다. 아래 명령은 이번 문서 작성 과정에서는 실행하지 않았다.

```bash
"$OPENRIG_TEST_ROOT/rig" down demo-rig
"$OPENRIG_TEST_ROOT/rig" daemon stop
```

해당 컴퓨터에서 구성했던 rig가 종료된 상태이고, 재개를 요청받았으며 파일·상태가 남아 있다면, 먼저 데몬 상태를 확인한다. 정말 종료된 경우에만 kernel 없이 시작하고, 기존 rig를 재개한다. 현재 실행 중인 rig에는 실행하지 않는다.

```bash
"$OPENRIG_TEST_ROOT/rig" daemon start --host 127.0.0.1 --port 17433 --no-kernel
"$OPENRIG_TEST_ROOT/rig" up demo-rig --existing --json
```

기존 rig 이름 재개와 Spec를 통한 새 팀 실행은 다르다. 아래는 최초 생성용이며, 기존 상태가 있을 때 무심코 반복 실행하지 않는다.

```bash
"$OPENRIG_TEST_ROOT/rig" up "$OPENRIG_TEST_ROOT/spec/rig.yaml" --json
```

## 7. 재구성에 필요한 Spec 원본

다른 컴퓨터에서 새 테스트를 구성하거나 임시 폴더가 사라진 경우의 참고 자료다. 재구성 시 사용자 승인을 받고 새 임시 루트를 만들며, Spec의 `<TEST_ROOT>`를 새 루트의 실제 절대 경로로 치환하고, 래퍼에 필요한 환경 변수를 지정한다. YAML의 자리표시자는 자동으로 환경 변수 치환되지 않는다. 권한 범위를 확인한 뒤 실행한다. 상태 DB와 이전 대화가 복원되는 것은 아니다.

`spec/rig.yaml`:

```yaml
version: "0.2"
name: demo-rig
summary: A single Codex seat with writes limited to the test workspace and state.
permission_policy: none
pods:
  - id: math
    label: Arithmetic
    members:
      - id: calculator
        agent_ref: "local:agents/calculator"
        profile: default
        runtime: codex
        model: gpt-6.1-sol
        effort: low
        codex_config_profile: example-codex
        cwd: "<TEST_ROOT>/work"
    edges: []
edges: []
```

`permission_policy: none`은 이 Spec의 OpenRig 정책 지정값이다. 이를 Codex 샌드박스 해제로 해석하지 않는다. 실제 제한은 앞서 제시한 별도 Codex 프로필과 실행 기록으로 확인했다.

`spec/agents/calculator/agent.yaml`:

```yaml
name: calculator
version: "1.0"
description: Answer the user's simple arithmetic questions in the conversation.
profiles:
  default:
    uses:
      skills: []
      guidance: []
      subagents: []
      plugins: []
      runtime_resources: []
resources: {}
startup:
  files: []
  actions: []
```

## 8. 다음 담당자가 남겨야 할 판단

- 대상 컴퓨터의 설치 상태와 소유자 권한부터 확인. 새 데모 구성이나 영구 경로 사용 여부는 해당 소유자에게 확인.
- 협업 검증이 필요하면 로컬 데몬 접근과 명령 네트워크 제한의 충돌부터 검토. 임의로 `danger-full-access`나 무제한 네트워크를 활성화하지 않음.
- 다중 에이전트 구성, 큐 조정, 세션 복원, 장시간 안정성, 실제 프로젝트 개발 작업은 추가 검증 대상.
- 예시 이름은 그대로 사용할 수 있지만, 작성 환경의 실행 중인 세션·상태 DB·인증은 다른 컴퓨터로 이전되지 않음.
- 문서 전달은 실행 중인 좌석의 담당자 교체나 OpenRig handover 수행과 다름. 이번 작업에서는 그러한 변경을 수행하지 않음.
