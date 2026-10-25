from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError
from c07_execution import verify_system_dependencies


class SystemDependencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sdk = Path(self.directory.name)
        self.stubs = self.sdk / "openharmony/native/sysroot/usr/lib/aarch64-linux-ohos"
        self.stubs.mkdir(parents=True)
        self.elf = b"\x7fELF\x02\x01" + bytes(12) + b"\xb7\x00" + bytes(44)
        for name in ("libc.so", "libhilog_ndk.z.so"):
            (self.stubs / name).write_bytes(self.elf)
        self.needed = {"provider.so": ["libc.so", "libhilog_ndk.z.so", "libc++_shared.so"],
                       "libc++_shared.so": ["libc.so"]}
        self.declared = ["libc.so", "libhilog_ndk.z.so"]

    def test_kotlin_explicit_sdk_platform_dependencies(self):
        result = verify_system_dependencies("kotlin", self.needed, self.declared, self.sdk)
        self.assertEqual(result["system_libraries"], self.declared)
        self.assertEqual(len(result["sdk_platform_stubs"]), 2)
        self.assertNotIn("libc++_shared.so", result["system_libraries"])

    def test_c_route_does_not_inherit_kotlin_extensions(self):
        for route in ("c", "cpp", "rust"):
            with self.subTest(route=route), self.assertRaises(CandidateError):
                verify_system_dependencies(route, self.needed, self.declared, self.sdk)

    def test_unknown_or_undeclared_dependency_rejected(self):
        for declared in (self.declared + ["libarbitrary.so"], ["libc.so"], self.declared * 2):
            with self.subTest(declared=declared), self.assertRaises(CandidateError):
                verify_system_dependencies("kotlin", self.needed, declared, self.sdk)

    def test_missing_and_wrong_architecture_sdk_stub_rejected(self):
        path = self.stubs / "libhilog_ndk.z.so"
        path.unlink()
        with self.assertRaises(CandidateError):
            verify_system_dependencies("kotlin", self.needed, self.declared, self.sdk)
        path.write_bytes(self.elf[:18] + b"\x3e\x00" + self.elf[20:])
        with self.assertRaises(CandidateError):
            verify_system_dependencies("kotlin", self.needed, self.declared, self.sdk)

    def test_existing_c_allowance_is_preserved(self):
        result = verify_system_dependencies("c", {"sdk.so": ["libc.so"]},
            ["libace_napi.z.so", "libc.so", "libdl.so", "libm.so", "libuv.so"], self.sdk)
        self.assertEqual(result["system_libraries"], ["libc.so"])
