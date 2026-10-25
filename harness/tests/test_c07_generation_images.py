"""Image pin regressions; synthetic bytes test admission, never SDK behavior."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import file_digest
from c07_execution import ExecutionError
from c07_generation import generation_images, verify_generation_tools


class GenerationImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.args = SimpleNamespace()
        tools = []
        for name, tool_id in (("madb", "c07-madb-host"), ("finalizer", "c07-finalizer")):
            data = ("synthetic parser input " + name).encode()
            path = self.root / name
            path.write_bytes(data)
            setattr(self.args, name + "_image", path)
            setattr(self.args, name + "_sha256", file_digest(data))
            tools.append(dict(id=tool_id, version="test-only", sha256=file_digest(data), size=len(data)))
        self.candidate = {"toolchain": {"tools": tools}}

    def test_exact_images_and_generated_tool_closure(self):
        images = generation_images(self.args, self.candidate)
        self.write_result(images, self.candidate["toolchain"]["tools"])
        verify_generation_tools(self.root, self.candidate, images)

    def test_local_pin_cannot_replace_different_candidate_tool(self):
        self.args.madb_image.write_bytes(b"different but locally pinned")
        self.args.madb_sha256 = file_digest(self.args.madb_image.read_bytes())
        with self.assertRaisesRegex(ExecutionError, "differs from admitted candidate"):
            generation_images(self.args, self.candidate)

    def test_modified_image_cannot_use_old_pin(self):
        self.args.finalizer_image.write_bytes(b"changed")
        with self.assertRaisesRegex(ExecutionError, "differs from explicit pin"):
            generation_images(self.args, self.candidate)

    def test_changed_or_duplicate_generation_tool_is_rejected(self):
        images = generation_images(self.args, self.candidate)
        tools = self.candidate["toolchain"]["tools"]
        changed = deepcopy(tools)
        changed[0]["sha256"] = "sha256:" + "0" * 64
        for actual in (changed, tools + [tools[0]]):
            self.write_result(images, actual)
            with self.subTest(actual=actual), self.assertRaises(ExecutionError):
                verify_generation_tools(self.root, self.candidate, images)

    def test_reported_host_must_match_selected_image(self):
        images = generation_images(self.args, self.candidate)
        self.write_result(images, self.candidate["toolchain"]["tools"])
        result = json.loads((self.root / "result.json").read_text())
        result["host"]["size"] += 1
        (self.root / "result.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(ExecutionError, "does not bind"):
            verify_generation_tools(self.root, self.candidate, images)

    def write_result(self, images, tools):
        result = {key: {field: image[field] for field in ("sha256", "size")}
                  for key, image in zip(("host", "finalizer"), images)}
        (self.root / "result.json").write_text(json.dumps(result))
        (self.root / "tool-observation.json").write_text(json.dumps({"public": {"tools": tools}}))
