import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import evaluate_chopsticks as app


def sample():
    return {"status": "assessable", "comment": "검지를 조금 펴세요.", "reference_notes": "기준 자세를 비교했습니다.",
            "limitations": ["정지 사진의 방향 안내입니다."], "corrections": [{
                "hand_index": 0, "landmark_id": 8, "joint_name": "검지 끝", "observation": "굽혀져 있습니다.",
                "instruction": "검지 끝을 조금 오른쪽으로 이동하세요.", "confidence": "medium", "show_target": True,
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
            self.assertEqual(result["assessment"]["corrections"][0]["target"], {"x": 0.55, "y": 0.4})
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

    def test_absolute_target_survives_start_anchoring(self):
        value = sample()
        target = copy.deepcopy(value["corrections"][0]["target"])
        data = {"hands": [{"hand_index": 0, "landmarks": [{"id": 8, "x": .8, "y": .7}]}]}
        app.anchor_corrections(value, data)
        self.assertEqual(value["corrections"][0]["start"], {"x": .8, "y": .7})
        self.assertEqual(value["corrections"][0]["target"], target)

    def test_twenty_corrections_allowed_twenty_one_rejected(self):
        value = sample()
        value["corrections"] = [copy.deepcopy(value["corrections"][0]) for _ in range(20)]
        for identifier, correction in enumerate(value["corrections"]):
            correction["landmark_id"] = identifier
        app.validate(value)
        value["corrections"].append(copy.deepcopy(value["corrections"][0]))
        with self.assertRaises(ValueError):
            app.validate(value)

    def test_arrow_runs_to_absolute_target_and_circle_marks_target(self):
        value = sample()
        value["corrections"][0].update(start={"x": .2, "y": .5}, target={"x": .8, "y": .5})
        image = Image.new("RGB", (401, 201), "white")
        rendered = app.render(image, value)
        cyan = (0, 207, 255)
        self.assertEqual(rendered.getpixel((200, 100)), cyan)  # arrow shaft
        self.assertEqual(rendered.getpixel((320, 94)), cyan)   # target circle away from label
        self.assertEqual(rendered.getpixel((80, 90)), (255, 255, 255))  # no target circle at start
        self.assertEqual(image.getpixel((200, 100)), (255, 255, 255))   # source preserved

    def assert_target_label_inside_image(self, size, target):
        value = sample()
        value["corrections"][0].update(landmark_id=18, target=dict(target))
        original_target = copy.deepcopy(value["corrections"][0]["target"])
        records = []
        original_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            box = draw.textbbox(xy, text, font=kwargs.get("font"),
                                anchor=kwargs.get("anchor"),
                                stroke_width=kwargs.get("stroke_width", 0))
            records.append((text, box))
            return original_text(draw, xy, text, *args, **kwargs)

        image = Image.new("RGB", size, "white")
        with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
            rendered = app.render(image, value)
        self.assertEqual(rendered.size, size)
        self.assertEqual(len(records), 1)
        text, (left, top, right, bottom) = records[0]
        self.assertEqual(text, "18")
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(right, size[0])
        self.assertLessEqual(bottom, size[1])
        self.assertGreater(right, left)
        self.assertGreater(bottom, top)
        self.assertEqual(value["corrections"][0]["target"], original_target)

    def test_target_labels_fit_at_each_image_edge(self):
        targets = ({"x": 0, "y": .5}, {"x": 1, "y": .5},
                   {"x": .5, "y": 0}, {"x": .5, "y": 1})
        for target in targets:
            with self.subTest(target=target):
                self.assert_target_label_inside_image((200, 100), target)

    def test_target_labels_fit_tiny_image_corners(self):
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
            with self.subTest(x=x, y=y):
                self.assert_target_label_inside_image((8, 6), {"x": x, "y": y})

    def test_hidden_target_does_not_change_image(self):
        value = sample()
        value["corrections"][0]["show_target"] = False
        image = Image.new("RGB", (200, 100), "white")
        self.assertEqual(app.render(image, value).tobytes(), image.tobytes())

    def test_low_confidence_hides_targets_and_arrows(self):
        value = sample()
        value["corrections"][0]["confidence"] = "low"
        image = Image.new("RGB", (200, 100), "white")
        self.assertEqual(app.render(image, value).tobytes(), image.tobytes())


if __name__ == "__main__":
    unittest.main()
