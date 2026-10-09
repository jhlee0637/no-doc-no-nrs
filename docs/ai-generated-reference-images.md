# 사용자 선택 기준 이미지

bul과 zip 각각 원본과 MediaPipe 관절 표시본을 제공한다.

| 저장소 파일 | 선택한 결과 파일 | 처리 |
| --- | --- | --- |
| assets/references/reference_bul.png | reference_bul.png | 원본, 관절 표시 없음 |
| assets/references/reference_zip.png | reference_zip.png | 원본, 관절 표시 없음 |
| assets/references/reference_bul_landmarks.png | reference_bul_new_conf30.png | MediaPipe, min_hand_detection_confidence=0.3 |
| assets/references/reference_zip_landmarks.png | reference_zip_landmarks_conf30.png | MediaPipe, min_hand_detection_confidence=0.3 |

네 이미지 모두 1686×933이며, 사용자가 제공하거나 선택한 파일을 바이트 그대로 복사했다. bul 표시본은 새 원본으로 다시 처리한 conf30 결과이다. 두 표시본 모두 손 1개가 검출되었다. 검출 성공이 관절 위치나 젓가락 자세의 정확성을 검증한 것은 아니다.

원본 두 PNG의 C2PA 메타데이터에는 ChatGPT/gpt-image 생성 출처가 기록되어 있다. 여기서 원본은 관절 표시를 추가하기 전 파일을 뜻한다. 카메라 촬영 이미지나 검증된 정답 자세라는 의미는 아니다. C2PA 암호 서명은 독립 검증하지 않았다.

현재 통합 CLI는 카탈로그의 reference에 MediaPipe를 적용하므로 원본을 사용한다. 이미 관절 표시가 포함된 파일을 그대로 GPT 입력으로 사용하는 연결 방식과 reference ID/version·input_type 매핑은 이슈 #2와 API 어댑터 검토에서 정해야 한다. 이번 자산 추가는 카탈로그나 API 계약을 변경하지 않는다. 개인 경로·API 키·좌표 JSON·원본 로그는 포함하지 않는다.

후속 카탈로그 초안과 기본 검출 임계값의 차이·실행 방법은 [연결안](ai-generated-reference-catalog-guide.md)에 기록한다. 해당 초안은 공동 계약 합의 전 예시다.
