import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from PIL import Image

from backend.app.pipeline import PipelineFailure, PipelineRunner, map_manifest


REFERENCE = {"id": "test-reference", "version": "1"}


def manifest(status="uncertain", source="analysis"):
    return {"schema_version": "pipeline-1", "input_type": "basic_grip", "reference": REFERENCE, "status": status, "source": source, "comment": "불확실성을 포함한 안내", "assessment": {"status": status, "corrections": []}, "image": {"file": "correction.png", "mime_type": "image/png", "width": 8, "height": 6}}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        Image.new("RGB", (8, 6)).save(self.output / "correction.png")

    def tearDown(self):
        self.temp.cleanup()

    def test_uncertain_and_empty_corrections_are_not_inferred_retake(self):
        value, content = map_manifest(manifest(), self.output, REFERENCE)
        self.assertEqual((value["outcome"], value["feedback"]["status"], value["feedback"]["corrections"]), ("feedback", "uncertain", []))
        self.assertTrue(content.startswith(b"\x89PNG"))

    def test_retake_preserves_preparation_and_reason(self):
        value = manifest("retake", "preparation")
        value["reason"] = "no_hand_detected"
        result, image = map_manifest(value, self.output, REFERENCE)
        self.assertEqual((result["source"], result["outcome"], result["retake"]["reason"]), ("preparation", "retake", "no_hand_detected"))
        self.assertIsNone(image)
        value["source"] = "analysis"
        with self.assertRaises(PipelineFailure):
            map_manifest(value, self.output, REFERENCE)

    def test_manifest_identity_image_dimensions_and_path_confinement(self):
        for key, replacement in (("schema_version", "other"), ("reference", {"id": "wrong", "version": "1"}), ("input_type", "other")):
            value = manifest()
            value[key] = replacement
            with self.assertRaises(PipelineFailure):
                map_manifest(value, self.output, REFERENCE)
        for replacement in ({"file": "../outside.png", "mime_type": "image/png", "width": 8, "height": 6}, {"file": "correction.png", "mime_type": "image/png", "width": 9, "height": 6}):
            Image.new("RGB", (8, 6)).save(self.root / "outside.png")
            value = manifest()
            value["image"] = replacement
            with self.assertRaises(PipelineFailure):
                map_manifest(value, self.output, REFERENCE)

    def runner(self, program, deadline=2):
        Image.new("RGB", (2, 2)).save(self.root / "reference.png")
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps({"schema_version": "1", "references": {"basic_grip": {"reference_id": REFERENCE["id"], "reference_version": REFERENCE["version"], "image": "reference.png"}}}))
        model = self.root / "hand.task"
        model.write_bytes(b"fake model")
        script = self.root / "fake_pipeline.py"
        script.write_text(program)
        private = self.root / "private"
        private.mkdir(exist_ok=True)
        return PipelineRunner(catalog, model, python=sys.executable, script=script, deadline_seconds=deadline, temp_root=private)

    def test_actual_subprocess_command_manifest_and_temporary_cleanup(self):
        program = """
import argparse, json
from pathlib import Path
from PIL import Image
p=argparse.ArgumentParser()
p.add_argument('query'); p.add_argument('--input-type'); p.add_argument('--catalog')
p.add_argument('--output-dir'); p.add_argument('--landmarker-model'); p.add_argument('--timeout')
a=p.parse_args()
assert a.input_type=='basic_grip' and Path(a.query).read_bytes()==b'private query bytes'
assert Path(a.catalog).is_file() and Path(a.landmarker_model).is_file()
assert 0 < float(a.timeout) <= 2
out=Path(a.output_dir);out.mkdir();Image.new('RGB',(8,6)).save(out/'correction.png')
(out/'result.json').write_text(json.dumps(REPLACE))
print('private stdout never exposed')
""".replace("REPLACE", repr(manifest()))
        runner = self.runner(program)
        result, image = runner.run(b"private query bytes")
        self.assertEqual(result["feedback"]["status"], "uncertain")
        self.assertTrue(image)
        self.assertEqual(list(runner.temp_root.iterdir()), [])
        self.assertNotIn("private stdout", json.dumps(result))

    def test_actual_subprocess_deadline_termination_and_cleanup(self):
        runner = self.runner("import time; time.sleep(5)", deadline=0.1)
        started = time.monotonic()
        with self.assertRaisesRegex(PipelineFailure, "timeout"):
            runner.run(b"private query")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(list(runner.temp_root.iterdir()), [])

    def test_failed_subprocess_logs_are_private_and_removed(self):
        runner = self.runner("import sys; print('sensitive original provider log', file=sys.stderr); sys.exit(1)")
        with self.assertRaisesRegex(PipelineFailure, "pipeline_failed"):
            runner.run(b"private query")
        self.assertEqual(list(runner.temp_root.iterdir()), [])

    def test_nonfinite_runner_deadline_is_rejected(self):
        for deadline in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(ValueError):
                self.runner("pass", deadline=deadline)

    def test_valid_output_png_can_exceed_upload_file_limit(self):
        image = Image.frombytes("RGB", (1400, 1400), os.urandom(1400 * 1400 * 3))
        image.save(self.output / "correction.png")
        value = manifest()
        value["image"].update(width=1400, height=1400)
        mapped, content = map_manifest(value, self.output, REFERENCE)
        self.assertGreater(len(content), 5 * 1024 * 1024)
        self.assertEqual(mapped["feedback"]["image"]["width"], 1400)


if __name__ == "__main__":
    unittest.main()
