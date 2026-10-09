"""사진에서 손의 21개 랜드마크를 검출하고 이미지와 JSON으로 저장합니다."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import urllib.request


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
NAMES = (
    "WRIST", "THUMB_CMC", "THUMB_MCP", "THUMB_IP", "THUMB_TIP",
    "INDEX_FINGER_MCP", "INDEX_FINGER_PIP", "INDEX_FINGER_DIP", "INDEX_FINGER_TIP",
    "MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP",
    "RING_FINGER_MCP", "RING_FINGER_PIP", "RING_FINGER_DIP", "RING_FINGER_TIP",
    "PINKY_MCP", "PINKY_PIP", "PINKY_DIP", "PINKY_TIP",
)
CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
    (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def get_model(path):
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        print("공식 Hand Landmarker 모델 다운로드 중...", file=sys.stderr)
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="입력 사진 경로")
    parser.add_argument("--output", type=Path, help="결과 이미지 경로 (기본: 입력명_landmarks.png)")
    parser.add_argument("--json", dest="json_path", type=Path, help="좌표 JSON 경로")
    parser.add_argument("--model", type=Path, help="기존 .task 모델 경로")
    parser.add_argument("--num-hands", type=int, default=2, help="최대 검출 손 개수 (기본: 2)")
    parser.add_argument("--confidence", type=float, default=0.5, help="검출 신뢰도 기준 (0~1)")
    args = parser.parse_args()
    if args.num_hands < 1 or not 0 <= args.confidence <= 1:
        parser.error("--num-hands는 1 이상, --confidence는 0~1이어야 합니다.")
    if not args.image.is_file():
        parser.error(f"입력 사진이 없습니다: {args.image}")
    output = args.output or args.image.with_name(args.image.stem + "_landmarks.png")
    json_path = args.json_path or output.with_suffix(".json")
    model = args.model or Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
    paths = [args.image.resolve(), output.resolve(), json_path.resolve(), model.resolve()]
    if len(set(paths)) != len(paths):
        parser.error("입력 사진, 결과 이미지, JSON, 모델 경로는 서로 달라야 합니다.")
    if args.model and not model.is_file():
        parser.error(f"모델이 없습니다: {model}")
    try:
        import mediapipe as mp
        import numpy as np
        from PIL import Image, ImageDraw, ImageOps
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        parser.exit(1, f"의존성을 설치하세요: python -m pip install -r Test/requirements.txt\n{exc}\n")

    try:
        with Image.open(args.image) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        get_model(model)
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=args.num_hands,
            min_hand_detection_confidence=args.confidence,
        )
        with vision.HandLandmarker.create_from_options(options) as detector:
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image)))
        width, height = image.size
        draw = ImageDraw.Draw(image)
        radius = max(3, round(min(width, height) / 150))
        hands = []
        for index, landmarks in enumerate(result.hand_landmarks):
            points = [(lm.x * width, lm.y * height) for lm in landmarks]
            for start, end in CONNECTIONS:
                draw.line([points[start], points[end]], fill="lime", width=max(2, radius // 2))
            for landmark_id, (x, y) in enumerate(points):
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="red", outline="white")
                draw.text((x+radius+2, y-radius), str(landmark_id), fill="white", stroke_width=1, stroke_fill="black")
            category = result.handedness[index][0]
            draw.text(points[0], f"{category.category_name} {category.score:.2f}", fill="yellow", stroke_width=1, stroke_fill="black")
            hands.append({
                "hand_index": index,
                "handedness": category.category_name,
                "handedness_score": category.score,
                "landmarks": [
                    {"id": i, "name": NAMES[i], "x_px": lm.x * width,
                     "y_px": lm.y * height, "x": lm.x, "y": lm.y, "z": lm.z}
                    for i, lm in enumerate(landmarks)
                ],
            })
        output.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        json_path.write_text(json.dumps({
            "image": str(args.image), "width": width, "height": height,
            "coordinate_origin": "top-left of EXIF-oriented image",
            "hands": hands,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"검출된 손: {len(hands)}개\n결과 이미지: {output}\n좌표 JSON: {json_path}")
        if not hands:
            print("손을 찾지 못했습니다. 손이 잘 보이는 사진 또는 낮은 --confidence 값으로 시도하세요.")
    except Exception as exc:
        print(f"처리 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
