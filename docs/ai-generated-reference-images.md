# 사용자 선택 기준 이미지

사용자가 선택한 MediaPipe 관절 표시 결과 두 개를 기준 이미지 후보로 추가한다.

| 저장소 파일 | 선택한 결과 파일 | 검출 기준 | 크기 |
| --- | --- | --- | --- |
| assets/references/reference_zip.png | reference_zip_landmarks_conf30.png | min_hand_detection_confidence=0.3 | 1686×933 |
| assets/references/reference_bul.png | reference_bul_landmarks_conf30.png | min_hand_detection_confidence=0.3 | 1686×933 |

원본은 사용자 제공 이미지이며, 표시된 관절과 번호는 기존 MediaPipe 처리 결과이다. 해당 결과 파일을 픽셀·해상도·PNG 메타데이터 변경 없이 바이트 그대로 복사하고 저장소 파일명만 변경했다. 두 처리 기록 모두 손 1개 검출이며, 검출 성공이 관절 위치나 젓가락 자세의 정확성을 검증한 것은 아니다.

이미 MediaPipe 표시가 포함된 이미지이다. 현재 통합 CLI는 카탈로그의 reference에 MediaPipe를 다시 적용하므로, 기존 표시·좌표를 그대로 사용할 연결 방식과 reference ID/version·input_type 매핑은 이슈 #2와 API 어댑터 검토에서 정해야 한다. 이번 자산 추가가 해당 계약이나 정상 자세를 확정하는 것은 아니다. 이 PR에는 개인 경로·API 키·원본 로그·다른 실행 결과를 포함하지 않는다.
