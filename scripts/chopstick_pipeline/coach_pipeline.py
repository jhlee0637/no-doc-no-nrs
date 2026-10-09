"""Raw query -> MediaPipe -> type-specific reference -> GPT coaching artifacts."""
import argparse
import json
import math
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageOps
import evaluate_chopsticks as evaluator
from hand_landmarks import CONNECTIONS, NAMES, get_model


NO_HAND_MESSAGE = ('손 관절을 인식하지 못했습니다. 밝은 곳에서 초점을 맞춰 선명하게 촬영하고, '
                   '배경을 깔끔하고 단순하게 정리해 주세요. 손 전체와 손가락이 가리지 않도록 다시 찍어 주세요.')
VIEW_MISMATCH_MESSAGE = ('기준 이미지와 손의 촬영 구도가 너무 달라 비교하기 어렵습니다. '
                         '기준 이미지처럼 손바닥/손등 방향과 카메라 각도를 맞추고, '
                         '손가락과 젓가락이 잘 보이도록 다시 촬영해 주세요.')


class PipelineError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def resolve_reference(catalog, input_type):
    catalog = Path(catalog).resolve()
    data = json.loads(catalog.read_text(encoding='utf-8'))
    if data.get('schema_version') != '1' or not isinstance(data.get('references'), dict):
        raise PipelineError('invalid_catalog', '기준 이미지 목록 형식을 확인하세요.')
    entry = data['references'].get(input_type)
    if not isinstance(entry, dict):
        raise PipelineError('unknown_input_type', '등록되지 않은 input_type입니다.')
    if any(not isinstance(entry.get(k), str) or not entry[k].strip()
           for k in ('reference_id', 'reference_version', 'image')):
        raise PipelineError('invalid_catalog', '기준 ID, 버전, 이미지 경로가 필요합니다.')
    relative = Path(entry['image'])
    if relative.is_absolute() or not (catalog.parent / relative).resolve().is_relative_to(catalog.parent):
        raise PipelineError('invalid_catalog', '기준 이미지는 목록 디렉터리 안의 상대 경로여야 합니다.')
    image = (catalog.parent / relative).resolve()
    if not image.is_file():
        raise PipelineError('reference_unavailable', '등록된 기준 이미지 파일이 없습니다.')
    return entry, image


def load_image(path, mirrored=False):
    path = Path(path)
    if path.stat().st_size > 5 * 1024 * 1024:
        raise PipelineError('image_too_large', '이미지 파일은 5 MiB 이하여야 합니다.')
    with Image.open(path) as source:
        if source.format not in ('JPEG', 'PNG'):
            raise PipelineError('unsupported_image', 'JPEG 또는 PNG 이미지를 사용하세요.')
        if source.width * source.height > 12_000_000:
            raise PipelineError('image_too_large', '이미지는 1200만 픽셀 이하여야 합니다.')
        image = ImageOps.exif_transpose(source).convert('RGB')
    return ImageOps.mirror(image) if mirrored else image


def mark_joints(image, output, model, *, num_hands=2, confidence=0.5):
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    get_model(model)
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.IMAGE, num_hands=num_hands,
        min_hand_detection_confidence=confidence)
    with vision.HandLandmarker.create_from_options(options) as detector:
        detected = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(image)))
    result = image.copy()
    draw = ImageDraw.Draw(result)
    width, height = image.size
    radius = max(3, round(min(width, height) / 150))
    hands = []
    for index, landmarks in enumerate(detected.hand_landmarks):
        points = [(lm.x * width, lm.y * height) for lm in landmarks]
        for start, end in CONNECTIONS:
            draw.line([points[start], points[end]], fill='lime', width=max(2, radius // 2))
        for identifier, (x, y) in enumerate(points):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill='red', outline='white')
            draw.text((x+radius+2, y-radius), str(identifier), fill='white', stroke_width=1, stroke_fill='black')
        category = detected.handedness[index][0]
        hands.append({'hand_index': index, 'handedness': category.category_name,
                      'handedness_score': category.score,
                      'landmarks': [{'id': i, 'name': NAMES[i], 'x': lm.x, 'y': lm.y, 'z': lm.z}
                                    for i, lm in enumerate(landmarks)]})
    data = {'width': width, 'height': height, 'coordinate_origin': 'top-left; EXIF oriented; unmirrored',
            'hands': hands}
    result.save(output)
    output.with_suffix('.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def save_result(output_dir, value):
    (output_dir / 'result.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return value


def run_pipeline(query, input_type, catalog, output_dir, *, landmarker_model,
                 model='gpt-4.1', api_key=None, timeout=60, mirrored=False,
                 confidence=0.5, prepare_only=False):
    """Return a local artifact manifest, not the still-unagreed HTTP response contract.

    Catalog paths are server-controlled. Images returned by GPT are rendered locally
    from validated correction coordinates; the original hand appearance is preserved.
    """
    if not 0 <= confidence <= 1 or not math.isfinite(timeout) or timeout <= 0:
        raise PipelineError('invalid_options', 'confidence는 0~1, timeout은 양수여야 합니다.')
    entry, reference = resolve_reference(catalog, input_type)
    query_image = load_image(query, mirrored)
    reference_image = load_image(reference)
    key = api_key or os.environ.get('OPENAI_API_KEY')
    output_dir = Path(output_dir)
    if Path(landmarker_model).resolve().is_relative_to(output_dir.resolve()):
        raise PipelineError('invalid_options', '모델 경로는 결과 디렉터리 밖에 있어야 합니다.')
    # Exclusive directory creation prevents overwriting or mixing concurrent runs.
    output_dir.mkdir(parents=True, exist_ok=False)
    base = {'schema_version': 'pipeline-1', 'input_type': input_type,
            'reference': {'id': entry['reference_id'], 'version': entry['reference_version']},
            'status': 'preparing', 'source': 'preparation', 'image': None, 'comment': None,
            'assessment': None, 'error': None,
            'artifacts': {}}
    try:
        query_data = mark_joints(query_image, output_dir / 'query_landmarks.png', Path(landmarker_model), confidence=confidence)
        base['artifacts']['query'] = 'query_landmarks.png'
        if not query_data['hands']:
            base.update(status='retake', comment=NO_HAND_MESSAGE, reason='no_hand_detected')
            return save_result(output_dir, base)
        reference_data = mark_joints(reference_image, output_dir / 'reference_landmarks.png', Path(landmarker_model), confidence=confidence)
        base['artifacts']['reference'] = 'reference_landmarks.png'
        if not reference_data['hands']:
            raise PipelineError('reference_unavailable', '기준 이미지에서 손을 검출하지 못했습니다.')
        if prepare_only:
            base.update(status='prepared')
            return save_result(output_dir, base)
        if not key:
            raise PipelineError('missing_api_key', 'OPENAI_API_KEY 또는 --api-key-file을 설정하세요.')
        _, reference_url = evaluator.prepare_image(output_dir / 'reference_landmarks.png')
        annotated, query_url = evaluator.prepare_image(output_dir / 'query_landmarks.png')
        assessment, _ = evaluator.request_assessment(reference_url, query_url, reference_data, query_data, model, key, timeout=timeout)
        evaluator.validate(assessment)
        (output_dir / 'assessment.json').write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding='utf-8')
        if assessment['status'] == 'pose_mismatch':
            guidance = '기준 사진처럼 젓가락과 손가락 위치를 맞춰 다시 잡은 뒤 촬영해 주세요.'
            comment = assessment['comment']
            if guidance not in comment:
                comment = comment.rstrip() + '\n\n' + guidance
            base.update(status='retake', source='analysis', reason='pose_mismatch',
                        comment=comment, assessment=assessment)
            return save_result(output_dir, base)
        if assessment['status'] == 'view_mismatch':
            base.update(status='retake', source='analysis', reason='view_mismatch',
                        comment=VIEW_MISMATCH_MESSAGE, assessment=assessment)
            return save_result(output_dir, base)
        evaluator.anchor_corrections(assessment, query_data)
        # A model-declared failure must not be emitted as successful coaching.
        if assessment['status'] == 'not_assessable':
            base.update(status='retake', source='analysis', reason='model_not_assessable',
                        comment=assessment['comment'], assessment=assessment)
            return save_result(output_dir, base)
        evaluator.render(annotated, assessment).save(output_dir / 'correction.png')
        (output_dir / 'comments.txt').write_text(evaluator.comments_text(assessment), encoding='utf-8')
        (output_dir / 'assessment.json').write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding='utf-8')
        base.update(status=assessment['status'], source='analysis', comment=assessment['comment'], assessment=assessment,
                    image={'file': 'correction.png', 'mime_type': 'image/png', 'width': annotated.width, 'height': annotated.height},
                    artifacts={**base['artifacts'], 'comments': 'comments.txt', 'assessment': 'assessment.json'})
        return save_result(output_dir, base)
    except Exception as exc:
        # Preserve useful intermediate artifacts but never persist provider errors or credentials.
        code = exc.code if isinstance(exc, PipelineError) else 'pipeline_failed'
        base.update(status='error', error={'code': code, 'message': '처리에 실패했습니다. 입력, 모델 및 API 설정을 확인하세요.'})
        save_result(output_dir, base)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', type=Path)
    parser.add_argument('--input-type', required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--landmarker-model', type=Path, required=True)
    parser.add_argument('--model', default=os.environ.get('OPENAI_MODEL', 'gpt-4.1'))
    parser.add_argument('--api-key-file', type=Path)
    parser.add_argument('--timeout', type=float, default=60, help='API socket timeout seconds; not a total request deadline')
    parser.add_argument('--confidence', type=float, default=0.5)
    parser.add_argument('--query-mirrored', action='store_true', help='Unmirror pixels before detection; preview mirroring alone does not require this')
    parser.add_argument('--prepare-only', action='store_true', help='Run MediaPipe without calling GPT')
    args = parser.parse_args()
    try:
        key = args.api_key_file.read_text(encoding='utf-8').strip() if args.api_key_file else None
        result = run_pipeline(args.query, args.input_type, args.catalog, args.output_dir,
                              landmarker_model=args.landmarker_model, model=args.model, api_key=key,
                              timeout=args.timeout, mirrored=args.query_mirrored,
                              confidence=args.confidence, prepare_only=args.prepare_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['status'] == 'error' else 0
    except Exception as exc:
        code = exc.code if isinstance(exc, PipelineError) else type(exc).__name__
        print(f'처리 실패 [{code}]. 입력, 출력 경로 및 API 설정을 확인하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
