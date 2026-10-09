import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import coach_pipeline as app
from test_chopstick_eval import sample


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.query = self.root / 'query.jpg'
        Image.new('RGB', (200, 100), 'white').save(self.query)
        Image.new('RGB', (200, 100), 'white').save(self.root / 'reference.jpg')
        self.catalog = self.root / 'catalog.json'
        self.catalog.write_text(json.dumps({'schema_version': '1', 'references': {'basic_grip': {
            'reference_id': 'demo', 'reference_version': '1', 'image': 'reference.jpg'}}}))

    def detect(self, image, output, model, **kwargs):
        image.save(output)
        return {'width': image.width, 'height': image.height, 'hands': [{'hand_index': 0,
            'landmarks': [{'id': i, 'x': 0.5, 'y': 0.5} for i in range(21)]}]}

    def run_app(self, **kwargs):
        return app.run_pipeline(self.query, 'basic_grip', self.catalog, self.root / 'out',
                                landmarker_model=self.root / 'model.task', api_key='fake', **kwargs)

    def test_full_flow_and_safe_manifest(self):
        with patch.object(app, 'mark_joints', side_effect=self.detect) as detect, \
             patch.object(app.evaluator, 'request_assessment', return_value=(sample(), 'private-id')) as request:
            result = self.run_app()
        self.assertEqual(detect.call_count, 2)
        self.assertEqual(result['reference']['id'], 'demo')
        self.assertEqual(result['status'], 'assessable')
        self.assertTrue(request.call_args.args[0].startswith('data:image/jpeg;base64,'))
        self.assertTrue(request.call_args.args[1].startswith('data:image/jpeg;base64,'))
        self.assertEqual(result['assessment']['corrections'][0]['start'], {'x': .5, 'y': .5})
        self.assertEqual(result['assessment']['corrections'][0]['target'], {'x': .55, 'y': .4})
        for name in ('correction.png', 'comments.txt', 'assessment.json', 'result.json'):
            self.assertTrue((self.root / 'out' / name).is_file())
        self.assertNotIn(str(self.root), (self.root / 'out' / 'result.json').read_text())
        self.assertNotIn('private-id', (self.root / 'out' / 'result.json').read_text())

    def test_no_hand_skips_api(self):
        with patch.object(app, 'mark_joints', return_value={'hands': []}), \
             patch.object(app.evaluator, 'request_assessment') as request:
            result = self.run_app()
        self.assertEqual(result['status'], 'retake')
        self.assertEqual(result['reason'], 'no_hand_detected')
        self.assertIn('선명하게', result['comment'])
        self.assertIn('배경', result['comment'])
        self.assertNotIn('reference', result['artifacts'])
        request.assert_not_called()

    def test_view_mismatch_returns_retake_without_correction_image(self):
        assessment = sample()
        assessment.update(status='view_mismatch', corrections=[], comment='다른 방향입니다.')
        with patch.object(app, 'mark_joints', side_effect=self.detect), \
             patch.object(app.evaluator, 'request_assessment', return_value=(assessment, 'private-id')):
            result = self.run_app()
        self.assertEqual(result['status'], 'retake')
        self.assertEqual(result['reason'], 'view_mismatch')
        self.assertIn('카메라 각도', result['comment'])
        self.assertIn('다시 촬영', result['comment'])
        self.assertIsNone(result['image'])
        self.assertFalse((self.root / 'out' / 'correction.png').exists())
        self.assertEqual(json.loads((self.root / 'out' / 'result.json').read_text())['reason'], 'view_mismatch')

    def test_pose_mismatch_requires_regrip_guidance_and_no_image(self):
        assessment = sample()
        assessment.update(status='pose_mismatch', corrections=[], comment='잡는 배치가 다릅니다.')
        with patch.object(app, 'mark_joints', side_effect=self.detect), \
             patch.object(app.evaluator, 'request_assessment', return_value=(assessment, 'private-id')):
            result = self.run_app()
        self.assertEqual(result['status'], 'retake')
        self.assertEqual(result['reason'], 'pose_mismatch')
        self.assertIn('잡는 배치가 다릅니다.', result['comment'])
        self.assertIn('기준 사진처럼 젓가락과 손가락 위치를 맞춰 다시 잡은 뒤 촬영해 주세요.', result['comment'])
        self.assertIsNone(result['image'])
        self.assertFalse((self.root / 'out' / 'correction.png').exists())
        self.assertFalse((self.root / 'out' / 'comments.txt').exists())
        saved = json.loads((self.root / 'out' / 'result.json').read_text())
        self.assertEqual(saved['reason'], 'pose_mismatch')
        self.assertEqual(saved['comment'], result['comment'])

    def test_pose_mismatch_must_not_include_corrections(self):
        assessment = sample()
        assessment['status'] = 'pose_mismatch'
        with self.assertRaises(ValueError):
            app.evaluator.validate(assessment)

    def test_view_mismatch_must_not_include_corrections(self):
        assessment = sample()
        assessment['status'] = 'view_mismatch'
        with self.assertRaises(ValueError):
            app.evaluator.validate(assessment)

    def test_catalog_and_overwrite_rejected_before_model(self):
        with self.assertRaises(app.PipelineError):
            app.resolve_reference(self.catalog, 'unknown')
        data = json.loads(self.catalog.read_text())
        data['references']['basic_grip']['image'] = '../reference.jpg'
        self.catalog.write_text(json.dumps(data))
        with self.assertRaises(app.PipelineError):
            app.resolve_reference(self.catalog, 'basic_grip')

    def test_existing_directory_is_preserved(self):
        (self.root / 'out').mkdir()
        marker = self.root / 'out' / 'marker'
        marker.write_text('keep')
        with patch.object(app, 'mark_joints') as detect:
            with self.assertRaises(FileExistsError):
                self.run_app()
        detect.assert_not_called()
        self.assertEqual(marker.read_text(), 'keep')

    def test_api_failure_does_not_become_retake(self):
        with patch.object(app, 'mark_joints', side_effect=self.detect), \
             patch.object(app.evaluator, 'request_assessment', side_effect=RuntimeError('secret-provider-body')):
            with self.assertRaises(RuntimeError):
                self.run_app()
        result = json.loads((self.root / 'out' / 'result.json').read_text())
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('secret-provider-body', json.dumps(result))

    def test_invalid_timeout_and_model_collision(self):
        for timeout in (float('nan'), float('inf'), 0):
            with self.assertRaises(app.PipelineError):
                self.run_app(timeout=timeout)
        with self.assertRaises(app.PipelineError):
            app.run_pipeline(self.query, 'basic_grip', self.catalog, self.root / 'out',
                             landmarker_model=self.root / 'out' / 'correction.png', api_key='fake')
        self.assertFalse((self.root / 'out').exists())

    def test_prepare_only_does_not_call_api(self):
        with patch.object(app, 'mark_joints', side_effect=self.detect), \
             patch.object(app.evaluator, 'request_assessment') as request:
            result = self.run_app(prepare_only=True)
        self.assertEqual(result['status'], 'prepared')
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
