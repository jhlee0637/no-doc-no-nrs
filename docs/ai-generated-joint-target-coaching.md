# 관절별 목표점 교정

GPT 평가에서 각 손가락의 MCP·PIP·DIP/IP·TIP을 검토하고 이동이 필요한 관절을 최대 20개 제안한다. 실제 관절 좌표에서 하늘색 목표점까지 화살표를 그리며, 목표 관절끼리의 연결선은 그리지 않는다. 번호는 MediaPipe 관절 ID이다. 목표점은 query 이미지의 정규화 좌표로 제안된 개략적 2D 위치이며 실측값이 아니다. 저확신·유지·깊이 이동만 필요한 관절은 표시하지 않는다.

내부 GPT correction 필드의 `draw_arrow`를 `show_target`으로 변경했다. MediaPipe 좌표로 start를 보정할 때 absolute target은 유지한다. 상위 result.json의 schema_version은 pipeline-1을 유지하지만 nested assessment를 직접 소비하는 코드는 새 필드에 맞춰야 한다.

젓가락과 손가락 배치가 기준과 크게 달라 전체적으로 다시 잡아야 하면 assessment.status=pose_mismatch, corrections=[]를 반환한다. 파이프라인은 status=retake, source=analysis, reason=pose_mismatch로 변환하고 기준 사진에 맞춰 다시 잡고 촬영하라는 안내를 보장한다. 교정 이미지는 반환하지 않는다. 작은 자세 차이는 기존 교정 대상으로 유지한다.

## GUI 연동 PR #7에 필요한 변경

현재 draft API 어댑터는 corrections 최대 6개와 기존 retake 사유만 허용한다. 최대 20개 및 analysis/pose_mismatch를 허용하도록 API·GUI 검증과 계약·fixture를 함께 조정해야 한다. input_type=zip과 해당 reference ID/version 매핑도 아직 공동 확정 전이며, 기존 basic_grip 카탈로그와 자동 호환된다고 가정하지 않는다. 이 PR은 파이프라인 변경이며 GUI 표시 완료를 주장하지 않는다.

## 검증 범위

실제 MediaPipe와 GPT 호출에서 사용자 사진의 관절별 목표점 및 화살표 이미지·코멘트·JSON 생성과 pose_mismatch 재촬영 반환을 확인했다. 사진·키·좌표·로그는 공개 저장소에 포함하지 않는다. 자세 정확성, 3D 운동, GUI/API를 통한 실제 GPT 왕복은 검증하지 않았다. 오프라인 회귀 테스트 결과는 PR 본문에 기록한다.
