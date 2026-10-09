import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import evaluate_chopsticks as app


def sample():
    return {"status": "assessable", "comment": "검지를 조금 펴세요.", "reference_notes": "기준 자세를 비교했습니다.",
            "limitations": ["정지 사진의 방향 안내입니다."], "corrections": [{
                "hand_index": 0, "landmark_id": 8, "joint_name": "검지 끝", "observation": "굽혀져 있습니다.",
                "instruction": "검지 끝을 조금 오른쪽으로 이동하세요.", "confidence": "medium", "draw_arrow": True,
                "start": {"x": 0.4, "y": 0.4}, "target": {"x": 0.55, "y": 0.4}}]}


class EvaluationTests(unittest.TestCase):
    def test_api_payload_and_rendered_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ref, query = root / "ref.png", root / "query.png"
            for path in (ref, query):
                Image.new("RGB", (200, 100), "white").save(path)
            data = {"width": 200, "height": 100, "hands": [{"hand_index": 0,
                "landmarks": [{"id": i, "x": 0.5, "y": 0.5} for i in range(21)]}]}
            query.with_suffix(".json").write_text(json.dumps(data))
            body = {"id": "mock-response", "status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(sample())}]}]}
            with patch.object(app.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as request:
                result = app.evaluate_chopsticks(ref, query, root / "output", api_key="mock-key")
            payload = json.loads(request.call_args.args[0].data)
            images = [part for part in payload["input"][0]["content"] if part["type"] == "input_image"]
            self.assertEqual(len(images), 2)
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertEqual(result["assessment"]["corrections"][0]["start"], {"x": 0.5, "y": 0.5})
            with Image.open(result["image_path"]) as rendered:
                self.assertEqual(rendered.size, (200, 100))
                self.assertTrue(any(pixel != (255, 255, 255) for pixel in rendered.getdata()))
            self.assertIn("검지를", Path(result["comment_path"]).read_text())
            self.assertEqual(json.loads(Path(result["json_path"]).read_text())["response_id"], "mock-response")
            with patch.object(app.urllib.request, "urlopen") as request:
                with self.assertRaises(ValueError):
                    app.evaluate_chopsticks(ref, query, root / "output", api_key="mock-key")
                request.assert_not_called()

    def test_invalid_coordinates_and_unassessable(self):
        value = sample()
        value["corrections"][0]["target"]["x"] = 1.1
        with self.assertRaises(ValueError):
            app.validate(value)
        value = sample()
        value["status"] = "not_assessable"
        with self.assertRaises(ValueError):
            app.validate(value)
        value["corrections"] = []
        app.validate(value)

    def test_refusal_and_incomplete(self):
        for body in ({"status": "incomplete"}, {"status": "completed", "output": [{"content": [{"type": "refusal"}]}]}):
            with patch.object(app.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())):
                with self.assertRaises(RuntimeError):
                    app.request_assessment("ref", "query", None, None, "mock-model", "mock-key")

    def test_low_confidence_no_arrows(self):
        value = sample()
        value["corrections"][0]["confidence"] = "low"
        image = Image.new("RGB", (200, 100), "white")
        self.assertEqual(app.render(image, value).tobytes(), image.tobytes())


if __name__ == "__main__":
    unittest.main()
