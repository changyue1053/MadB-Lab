"""Bounded command-log JSON uses the unchanged strict metadata parser."""
from pathlib import Path
import io
import unittest
from unittest.mock import patch
from candidate import CandidateError, parse_json, read_json
from c07_route_ownership import verify_route_ownership
import test_c07_route_ownership as fixtures

MIB = 1024 * 1024


class CommandLogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RouteOwnershipTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def replace(self, name, value):
        self.fixture.put(name, value)
        self.fixture.put('evidence/compile.json', self.fixture.compile)
        self.fixture.put('evidence/link.json', self.fixture.link)

    def verify(self):
        return verify_route_ownership(self.fixture.candidate)

    def test_large_compile_and_link_logs_are_bound(self):
        for name, rows in [('compile', self.fixture.compile_rows), ('link', self.fixture.link_rows)]:
            rows[0]['stdout'] = 'x' * MIB
            self.replace('logs/' + name + '-commands.json', rows)
        self.assertEqual(self.verify()['status'], 'bound')

    def test_command_log_above_32_mib_is_rejected(self):
        self.replace('logs/compile-commands.json', b'[]' + b' ' * (32 * MIB - 1))
        with self.assertRaisesRegex(CandidateError, 'JSON exceeds 32 MiB'):
            self.verify()

    def test_metadata_keeps_one_mib_limit(self):
        self.replace('madb.lock', b'{}' + b' ' * (MIB - 1))
        with self.assertRaisesRegex(CandidateError, 'JSON exceeds 1 MiB'):
            self.verify()
        with self.assertRaisesRegex(CandidateError, 'JSON exceeds 1 MiB'):
            read_json(self.fixture.root / 'madb.lock')

    def test_changed_log_bytes_rejected_before_parse(self):
        path = self.fixture.root / 'logs/compile-commands.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(CandidateError, 'changed candidate evidence'):
            self.verify()

    def test_same_size_changed_hash_is_rejected(self):
        path = self.fixture.root / 'logs/compile-commands.json'
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b'clang', b'CLANG', 1))
        with self.assertRaisesRegex(CandidateError, 'changed candidate evidence'):
            self.verify()

    def test_unlisted_log_is_rejected(self):
        self.fixture.candidate['manifest']['files'] = [v for v in self.fixture.candidate['manifest']['files']
            if v['path'] != 'logs/compile-commands.json']
        with self.assertRaises(CandidateError):
            self.verify()

    def test_log_preserves_strict_json_subset(self):
        cases = [b'[{"key":1,"key":2}]', b'[1.5]', b'[NaN]', b'[Infinity]', b'[-0]',
                 b'[9007199254740992]', b'[' * 66 + b'0' + b']' * 66,
                 b'["\xff"]', b'["\\ud800"]', b'[] trailing']
        for raw in cases:
            with self.subTest(raw=raw):
                self.replace('logs/compile-commands.json', raw + b' ' * MIB)
                with self.assertRaises(CandidateError):
                    self.verify()

    def test_log_is_read_once_with_max_plus_one(self):
        path = self.fixture.root / 'logs/compile-commands.json'
        raw = path.read_bytes()
        reads = []
        class Tracked(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        original = Path.open
        def open_path(current, *args, **kwargs):
            return Tracked(raw) if current == path else original(current, *args, **kwargs)
        with patch.object(Path, 'open', open_path):
            self.assertEqual(self.verify()['status'], 'bound')
        self.assertEqual(reads, [32 * MIB + 1])

    def test_metadata_reader_is_bounded_and_uses_same_parser(self):
        reads = []
        class Tracked(io.BytesIO):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        with patch.object(Path, 'open', return_value=Tracked(b'{}')) as opened:
            self.assertEqual(read_json(Path('metadata.json')), {})
        opened.assert_called_once_with('rb')
        self.assertEqual(reads, [MIB + 1])
        self.assertEqual(parse_json(b'{"integer":9007199254740991}'), {'integer':9007199254740991})

    def test_exact_limit_is_accepted(self):
        self.assertEqual(parse_json(b'{}' + b' ' * (MIB - 2)), {})
        self.assertEqual(parse_json(b'[]' + b' ' * (32 * MIB - 2), limit=32 * MIB), [])
