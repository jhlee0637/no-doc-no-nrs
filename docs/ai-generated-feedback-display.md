# 교정 안내의 한국어 표시와 이미지 확대

서버의 관절 식별자는 그대로 유지하고 GUI에서 한국어로 표시한다. 표는 프로젝트의 21개 MediaPipe 관절 이름에 대응하는 사용자 안내용 표현이다. [MediaPipe 손 관절 설명](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)을 참고한다.

| 코드 | 화면 표시 |
| --- | --- |
| WRIST | 손목 |
| THUMB_CMC | 엄지 손목 쪽 관절 |
| THUMB_MCP | 엄지 뿌리 관절 |
| THUMB_IP | 엄지 끝마디 관절 |
| THUMB_TIP | 엄지 끝 |
| INDEX_FINGER_MCP | 검지 뿌리 관절 |
| INDEX_FINGER_PIP | 검지 가운데 관절 |
| INDEX_FINGER_DIP | 검지 끝마디 관절 |
| INDEX_FINGER_TIP | 검지 끝 |
| MIDDLE_FINGER_MCP | 중지 뿌리 관절 |
| MIDDLE_FINGER_PIP | 중지 가운데 관절 |
| MIDDLE_FINGER_DIP | 중지 끝마디 관절 |
| MIDDLE_FINGER_TIP | 중지 끝 |
| RING_FINGER_MCP | 약지 뿌리 관절 |
| RING_FINGER_PIP | 약지 가운데 관절 |
| RING_FINGER_DIP | 약지 끝마디 관절 |
| RING_FINGER_TIP | 약지 끝 |
| PINKY_MCP | 새끼손가락 뿌리 관절 |
| PINKY_PIP | 새끼손가락 가운데 관절 |
| PINKY_DIP | 새끼손가락 끝마디 관절 |
| PINKY_TIP | 새끼손가락 끝 |

세부 안내 제목뿐 아니라 설명 문장에 들어간 코드와 관절 약어도 치환한다. 알 수 없는 코드는 위치를 추측하지 않고 관절 이름 확인이 필요하다고 표시한다. 원본 API 응답은 수정하지 않는다.

사진 분석 안내는 기존 설명을 문장과 줄바꿈 경계에서 나눠 목록으로 표시한다. 모델 호출이나 새로운 요약은 수행하지 않으며 수치와 부정 표현을 유지한다. 서버 문자열은 텍스트 노드로 표시하여 HTML로 실행하지 않는다.

교정 PNG는 사진 미리보기의 고정 높이 제한을 적용하지 않고 결과 카드 폭에 맞춰 원본 비율로 표시한다. 서버 응답에 기록된 크기와 실제 이미지 크기가 일치하면 ‘이미지 크게 보기’를 제공한다. 확대 창은 닫기 버튼과 Escape로 닫을 수 있다. 사진 교체·삭제·새 요청·오류가 발생하면 이전 이미지를 제거한다. 창은 [HTML dialog](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog)를 사용한다.

정적 화면 예시는 계속 사진 선택과 모의 안내만 제공한다. 이 변경은 실제 분석 서버를 배포하거나 분석 정확도를 검증하는 작업이 아니다.
