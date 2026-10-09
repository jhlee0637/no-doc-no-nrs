"""Private subprocess boundary for the existing pipeline-1 artifact manifest."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from PIL import Image

MAX_OUTPUT_IMAGE = 40 * 1024 * 1024


class PipelineFailure(Exception):
    def __init__(self, code="pipeline_failed"):
        super().__init__(code)
        self.code = code


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def resolve_catalog(catalog):
    """Only server-controlled basic_grip entries are accepted."""
    catalog = Path(catalog).resolve(strict=True)
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1" or not isinstance(data.get("references"), dict):
        raise ValueError("invalid_catalog")
    entry = data["references"].get("basic_grip")
    if not isinstance(entry, dict) or not all(nonempty(entry.get(key)) for key in ("reference_id", "reference_version", "image")):
        raise ValueError("invalid_catalog")
    relative = Path(entry["image"])
    image = (catalog.parent / relative).resolve(strict=True)
    if relative.is_absolute() or not image.is_relative_to(catalog.parent) or not image.is_file():
        raise ValueError("invalid_catalog")
    return {"id": entry["reference_id"], "version": entry["reference_version"]}


def map_manifest(manifest, output_dir, reference):
    """Copy only the public subset; never return artifact paths or provider errors."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "pipeline-1" or manifest.get("input_type") != "basic_grip" or manifest.get("reference") != reference:
        raise PipelineFailure("invalid_pipeline_result")
    source = manifest.get("source")
    status = manifest.get("status")
    if source not in ("analysis", "preparation"):
        raise PipelineFailure("invalid_pipeline_result")
    comment = manifest.get("comment")
    if status == "retake":
        reason = manifest.get("reason")
        if not nonempty(comment) or (source, reason) not in {("preparation", "no_hand_detected"), ("analysis", "view_mismatch"), ("analysis", "model_not_assessable"), ("analysis", "pose_mismatch")}:
            raise PipelineFailure("invalid_pipeline_result")
        return {"source": source, "outcome": "retake", "retake": {"reason": reason, "message": comment}}, None
    if status == "error":
        raise PipelineFailure()
    assessment = manifest.get("assessment")
    if source != "analysis" or status not in ("assessable", "uncertain") or not nonempty(comment) or not isinstance(assessment, dict) or assessment.get("status") != status:
        raise PipelineFailure("invalid_pipeline_result")
    corrections = assessment.get("corrections")
    if not isinstance(corrections, list) or len(corrections) > 20:
        raise PipelineFailure("invalid_pipeline_result")
    public_corrections = []
    for item in corrections:
        if not isinstance(item, dict) or not nonempty(item.get("joint_name")) or not nonempty(item.get("instruction")):
            raise PipelineFailure("invalid_pipeline_result")
        public_corrections.append({"joint_name": item["joint_name"], "instruction": item["instruction"]})
    image = manifest.get("image")
    if not isinstance(image, dict) or image.get("mime_type") != "image/png" or not nonempty(image.get("file")):
        raise PipelineFailure("invalid_pipeline_result")
    root = Path(output_dir).resolve()
    relative = Path(image["file"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_OUTPUT_IMAGE:
        raise PipelineFailure("invalid_pipeline_result")
    content = path.read_bytes()
    try:
        with Image.open(io.BytesIO(content)) as decoded:
            if decoded.format != "PNG" or decoded.width * decoded.height > 12_000_000:
                raise PipelineFailure("invalid_pipeline_result")
            decoded.load()
            width, height = decoded.size
        if type(image.get("width")) is not int or type(image.get("height")) is not int or (image["width"], image["height"]) != (width, height):
            raise PipelineFailure("invalid_pipeline_result")
    except PipelineFailure:
        raise
    except Exception as exc:
        raise PipelineFailure("invalid_pipeline_result") from exc
    return {"source": source, "outcome": "feedback", "feedback": {"status": status, "comment": comment, "corrections": public_corrections, "image": {"mime_type": "image/png", "width": width, "height": height}}}, content


def stop_process(process):
    """Terminate the private child group, then reap it before deleting its files."""
    def send(sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass
    send(signal.SIGTERM)
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        process.wait()
    finally:
        # A child can exit before descendants. Remove any remaining private group.
        if os.name == "posix":
            send(signal.SIGKILL)


@dataclass
class PipelineRunner:
    catalog: Path
    landmarker_model: Path
    python: str = sys.executable
    deadline_seconds: float = 180
    script: Path | None = None
    temp_root: Path | None = None
    analysis_root: Path | None = None
    confidence: float = 0.1

    def __post_init__(self):
        if isinstance(self.deadline_seconds, bool) or not isinstance(self.deadline_seconds, (int, float)) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError("invalid_pipeline_options")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid_pipeline_options")
        if self.analysis_root is not None:
            self.analysis_root = Path(self.analysis_root).resolve()
            self.analysis_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.catalog = Path(self.catalog).resolve(strict=True)
        self.landmarker_model = Path(self.landmarker_model).resolve(strict=True)
        if not self.landmarker_model.is_file():
            raise ValueError("model_unavailable")
        self.reference = resolve_catalog(self.catalog)
        self.script = Path(self.script or Path(__file__).resolve().parents[2] / "scripts/chopstick_pipeline/coach_pipeline.py").resolve(strict=True)
        executable = shutil.which(self.python)
        if not executable or not self.script.is_file():
            raise ValueError("invalid_pipeline_options")
        self.python = executable

    def run(self, content, *, timeout=None):
        started = datetime.now(timezone(timedelta(hours=9), name="KST"))
        if self.analysis_root is None:
            context = tempfile.TemporaryDirectory(prefix="coach-api-", dir=self.temp_root)
        else:
            private = tempfile.mkdtemp(prefix=started.strftime("%Y%m%d_%H%M%S_%f_"), dir=self.analysis_root)
            context = nullcontext(private)
        with context as private:
            root = Path(private)
            metadata = {"started_at": started.isoformat(timespec="microseconds"),
                        "timezone": "Asia/Seoul", "status": "running"}
            if self.analysis_root is not None:
                (root / "request.json").write_text(json.dumps(metadata), encoding="utf-8")
            try:
                result = self._run_private(root, content, timeout=timeout)
                metadata.update(status="completed", outcome=result[0]["outcome"])
                return result
            except BaseException as exc:
                metadata.update(status="error", error_code=exc.code if isinstance(exc, PipelineFailure) else "pipeline_failed")
                raise
            finally:
                if self.analysis_root is not None:
                    metadata["finished_at"] = datetime.now(timezone(timedelta(hours=9), name="KST")).isoformat(timespec="microseconds")
                    (root / "request.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_private(self, root, content, *, timeout=None):
        suffix = ".image"
        if self.analysis_root is not None:
            try:
                with Image.open(io.BytesIO(content)) as image:
                    suffix = {"JPEG": ".jpg", "PNG": ".png"}[image.format]
                    image.verify()
            except Exception as exc:
                raise PipelineFailure("invalid_image") from exc
        query = root / ("query" + suffix)
        query.write_bytes(content)
        # Startup availability is insufficient if catalog files change later.
        if resolve_catalog(self.catalog) != self.reference or not self.landmarker_model.is_file():
            raise PipelineFailure("reference_unavailable")
        output = root / "output"
        budget = min(self.deadline_seconds, timeout if timeout is not None else self.deadline_seconds)
        if not math.isfinite(budget) or budget <= 0:
            raise PipelineFailure("timeout")
        command = [self.python, str(self.script), str(query), "--input-type", "basic_grip", "--catalog", str(self.catalog), "--output-dir", str(output), "--landmarker-model", str(self.landmarker_model), "--timeout", str(budget), "--confidence", str(self.confidence)]
        # Credentials are inherited normally, never copied to command arguments.
        with (root / "stdout.log").open("wb") as stdout, (root / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=os.name == "posix")
            try:
                process.wait(timeout=budget)
            except subprocess.TimeoutExpired as exc:
                stop_process(process)
                raise PipelineFailure("timeout") from exc
            except BaseException:
                stop_process(process)
                raise
            finally:
                # Also clean descendants of a normally terminated subprocess.
                if process.poll() is not None and os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        if process.returncode != 0:
            raise PipelineFailure()
        if not output.resolve().is_relative_to(root.resolve()):
            raise PipelineFailure("invalid_pipeline_result")
        manifest_file = output / "result.json"
        if not manifest_file.resolve().is_relative_to(output.resolve()) or not manifest_file.is_file() or manifest_file.stat().st_size > 1024 * 1024:
            raise PipelineFailure("invalid_pipeline_result")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PipelineFailure("invalid_pipeline_result") from exc
        return map_manifest(manifest, output, self.reference)
