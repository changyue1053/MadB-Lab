"""Adversarial supplement-oracle checks; synthetic frames are never target evidence."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from c09_close_windows import CloseWindowSession, guarded_output
from c09_close_windows_observations import expected_labels, parse_observation


def native_frames():
    def frame():
        result = [0] * 178
        result[0] = result[54] = result[156] = 1
        return result
    held = frame()
    for index, value in {13: 1, 14: 1, 55: 1, 56: 2, 57: 1, 58: 1, 62: 10, 63: 11, 65: 1}.items():
        held[index] = value
    pending = held.copy(); pending[30] = 1
    operation = [1, 1, 0, 1, 2, 1, 0, 0, 0, 1]
    closing = [0] * 15
    for i in (0, 5, 8):
        closing[i] = 1
    final = frame()
    for i in (16, 17, 32, 33, 34, 157):
        final[i] = 1
    for i in range(38, 54):
        final[i] = 1
    final[1] = 3; final[55] = 2
    final[62:65] = [10, 11, 12]
    final[65:71] = [1] * 6
    final[71:77] = [1, 2, 3, 4, 5, 6]
    closed = [0] * 15; closed[0] = closed[9] = 1
    frames = {}
    for label in expected_labels("c"):
        if label == "work-held": value = held
        elif label == "operation-held": value = operation
        elif label.startswith(("pending-native-", "after-attempt-native-")): value = pending
        elif label.startswith("pending-facade-"): value = closing
        elif label.startswith("reopen-rejected-"): value = [1, 0, 0]
        elif label.endswith("physical-closed"): value = final
        elif label.endswith("facade-closed"): value = closed
        elif label == "first-close-outcome": value = [1, 0]
        else: value = [42]
        frames[label] = copy.deepcopy(value)
    return frames


def encoded(frames):
    lines = ["x y 17 PROBE_STARTED nonce", "x y 17 PROBE_PAGE_READY nonce", "x y 17 PROBE_FINISHED nonce"]
    lines.extend("x y 17 C09_CLOSE_FRAME nonce " + label + " " + json.dumps(value) for label, value in frames.items())
    lines.append("x y 17 C09_CLOSE_COMPLETE nonce")
    return "\n".join(lines)


def kotlin_frames():
    frames = {}
    opened = [0] * 110
    opened[0] = 70501; opened[1] = opened[7] = opened[12] = opened[39] = 1
    held = [70604, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0]
    for label in expected_labels("kotlin"):
        if label.endswith("runtime-open") or label.startswith("pending-native"):
            value = opened.copy()
        elif label.endswith("runtime-closed"):
            count = 1 if label.startswith("first") else 2
            value = [0] * 110; value[0] = 70501
            value[1] = 4; value[2] = value[7] = 1; value[72] = 3
            for i in (12, 13, 45, 46, 48, 49, 78, 79, 102, 103, 108, 109): value[i] = count
        elif label.startswith("thread-"):
            value = held.copy()
            if label == "thread-armed": value[5] = value[6] = value[11] = value[16] = 0
            elif label == "thread-released": value[12] = 1
            elif label == "thread-final":
                value[4:7] = [0] * 3
                value[7:10] = [18446744073709551615] * 3
                value[10:20] = [1] * 10
            value = ",".join(map(str, value))
        elif label.endswith("js-final"): value = [0] * 9
        elif label.startswith("reopen-rejected"): value = [1, 0, 0]
        elif label == "first-close-outcome": value = [1, 0]
        else: value = [42]
        frames[label] = value
    return frames


class RejectionTests(unittest.TestCase):
    def check_failure(self, frames):
        self.assertEqual(parse_observation(encoded(frames), nonce="nonce", pid="17", route="c")["status"], "failed")

    def test_known_complete_transport(self):
        result = parse_observation(encoded(native_frames()), nonce="nonce", pid="17", route="c")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["status"], "passed")

    def test_missing_second_checkpoint(self):
        frames = native_frames(); del frames["reopen-rejected-1"]
        self.check_failure(frames)

    def test_already_physical_is_not_pre_ack(self):
        frames = native_frames(); frames["pending-native-0"][55] = 2
        self.check_failure(frames)

    def test_close_finished_before_rejection(self):
        frames = native_frames(); frames["reopen-rejected-1"] = [1, 1, 0]
        self.check_failure(frames)

    def test_attempt_releasing_worker_is_rejected(self):
        frames = native_frames(); frames["after-attempt-native-0"][59] = 1
        self.check_failure(frames)

    def test_physical_without_consumed_receipt_is_not_final(self):
        frames = native_frames(); frames["first-physical-closed"][32] = 0
        self.check_failure(frames)

    def test_retained_native_or_js_owner_is_rejected(self):
        for label, index in (("second-physical-closed", 25), ("first-facade-closed", 6)):
            frames = native_frames(); frames[label][index] = 1
            self.check_failure(frames)

    def test_wrong_process_and_duplicate_label(self):
        raw = encoded(native_frames())
        self.assertEqual(parse_observation(raw, nonce="nonce", pid="18", route="c")["status"], "failed")
        raw += '\nx y 17 C09_CLOSE_FRAME nonce reopened-result [42]'
        self.assertEqual(parse_observation(raw, nonce="nonce", pid="17", route="c")["status"], "failed")

    def test_kotlin_never_accepts_c_layout(self):
        raw = 'x y 17 C09_CLOSE_FRAME nonce first-runtime-open ' + json.dumps([0] * 178)
        self.assertEqual(parse_observation(raw, nonce="nonce", pid="17", route="kotlin")["status"], "failed")

    def test_output_input_overlap_rejected_without_creation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            candidate = root / "candidate"; candidate.mkdir()
            alias = root / "alias"; alias.symlink_to(candidate, target_is_directory=True)
            for output in (candidate, candidate / "new", alias / "new", root):
                with self.assertRaises(ValueError):
                    guarded_output(output, [candidate])
            self.assertFalse((candidate / "new").exists())
            self.assertEqual(guarded_output(root / "safe", [candidate]), root / "safe")

    def test_existing_probe_refuses_legacy_stop(self):
        session = object.__new__(CloseWindowSession)
        with patch("c09_close_windows.ControlledSession.hdc", return_value={"stdout": "123\n"}) as hdc:
            with self.assertRaisesRegex(RuntimeError, "not owned"):
                session.hdc("stop-old-probe", "shell", "aa", "force-stop", "com.madb.c07probe")
        self.assertEqual(hdc.call_args.args[1:3], ("shell", "pidof"))

    def test_kotlin_cumulative_second_epoch_and_missing_receipt(self):
        frames = kotlin_frames()
        result = parse_observation(encoded(frames), nonce="nonce", pid="17", route="kotlin")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["status"], "passed")
        for index, value in ((12, 1), (13, 1), (2, 0), (47, 1)):
            mutant = copy.deepcopy(frames)
            mutant["second-runtime-closed"][index] = value
            self.assertEqual(parse_observation(encoded(mutant), nonce="nonce", pid="17", route="kotlin")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
