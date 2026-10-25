"""Public ABI encoding and embedded Kotlin identity negative controls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError, semantic_digest
from c07_abi import abi_document, verify_abi
from c07_candidate import verify_embedded_identity


def inputs():
    contract = {'types': [{'id': 'i32', 'definition': {'kind': 'integer', 'bits': 32}}],
                'symbols': [{'public_id': 'fixed', 'shape': {'parameters': [], 'result': 'i32'}, 'source_key': {'ignored': 'path'}}],
                'policies': [{'symbol_id': 'fixed', 'slot': 'thread', 'values': {'executor': 'main'}, 'origin': 'ignored'}],
                'required_features': ['core.values@1']}
    descriptor = {'public': {'authority': 'reader', 'location': {'line': 1}, 'records': [{'name': 'Snapshot'}]},
                  'kotlin': {'facts': {'record': {'qualifiedName': 'x.Snapshot', 'source': {'line': 4}}},
                    'descriptor': {'interfaces': [{'name': 'Snapshot'}], 'authority': 'compiler'},
                    'record_schema': {'qualifiedName': 'x.Snapshot', 'fields': [{'name': 'value', 'kotlinType': 'kotlin.Int', 'location': 'ignored'}]},
                    'frontend_policy': {'notification_interfaces': {'return_type': 'kotlin.Unit'}, 'parameters': {'owned_interface_maximum': 1}},
                    'tools': {'version': 'old'}, 'generated': ['code'], 'source_inputs': ['input'], 'closure': ['lock']}}
    return contract, descriptor, {'values': {'int32': True}, 'execution_domain': 'main', 'authority': 'ignored'}


class AbiTests(unittest.TestCase):
    def test_provenance_does_not_change_semantic_abi(self):
        contract, declarations, policy = inputs(); expected = abi_document(contract, declarations, policy)
        changed = deepcopy(declarations)
        for key in ('tools', 'generated', 'source_inputs', 'closure'): changed['kotlin'][key] = ['changed']
        changed['public']['location']['line'] = 9
        changed['kotlin']['facts']['record']['source']['line'] = 99
        self.assertEqual(abi_document(contract, changed, policy), expected)
        self.assertNotIn('source_key', expected['logical']['symbols'][0])

    def test_types_and_runtime_semantics_change_abi(self):
        contract, declarations, policy = inputs(); expected = abi_document(contract, declarations, policy)
        for mutation in ('type', 'id', 'callback', 'thread', 'role'):
            c, d, p = deepcopy((contract, declarations, policy))
            if mutation == 'type': c['types'][0]['definition']['bits'] = 64
            if mutation == 'id': c['symbols'][0]['public_id'] = 'different'
            if mutation == 'callback': d['kotlin']['frontend_policy']['notification_interfaces']['return_type'] = 'kotlin.Int'
            if mutation == 'thread': p['execution_domain'] = 'worker'
            if mutation == 'role': p['values']['int32'] = False
            self.assertNotEqual(abi_document(c, d, p), expected, mutation)

    def test_candidate_digest_rejects_old_or_tampered_protocol(self):
        c, d, p = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'generated/contract').mkdir(parents=True)
            (root/'declarations.json').write_text(json.dumps(d)); (root/'generated/contract/runtime-policy.json').write_text(json.dumps(p))
            candidate = {'root': root, 'contract': c, 'identity': {'abi_digest': semantic_digest('madb.c07-abi/1', abi_document(c,d,p))}}
            verify_abi(candidate, 'kotlin')
            candidate['identity']['abi_digest'] = semantic_digest('madb.c07-abi/1', {'old': 'whole compiler output'})
            with self.assertRaisesRegex(CandidateError, 'public type/protocol'): verify_abi(candidate, 'kotlin')
            candidate['identity']['abi_digest'] = semantic_digest('madb.c07-abi/1', abi_document(c,d,p))
            c['symbols'][0]['shape']['result'] = 'i64'
            with self.assertRaises(CandidateError): verify_abi(candidate, 'kotlin')
            with self.assertRaises(CandidateError): verify_abi(candidate, 'rust')

    def test_kotlin_binding_and_both_dsos_must_match(self):
        identity = {'schema': 'madb.arkts-runtime-identity/1', 'bootstrap_version': 1,
                    'abi_digest': 'sha256:'+'a'*64, 'profile_digest': 'sha256:'+'b'*64, 'build_id': 'sha256:'+'c'*64}
        text = 'madb-arkts/1:' + ':'.join(identity[x][7:] for x in ('abi_digest','profile_digest','build_id'))
        identity['expected_identity'] = text; raw = text.encode()
        header = json.dumps({'authority': 'actual KSP facts and emitted declaration; bootstrap has separate authored ABI', 'identity': identity}).encode()
        members = {'package/ets/modules.abc': raw+b'\0',
                   'package/libs/arm64-v8a/libmadbc07sdkkotlin.so': b'\x7fELF'+raw+b'\0',
                   'package/libs/arm64-v8a/libmadb_kotlin_owned_runtime.so': b'\x7fELF'+raw+b'\0'}
        facade = b'const EXPECTED_IDENTITY: string = "'+raw+b'";'
        verify_embedded_identity(identity,'kotlin','madbc07sdkkotlin',facade,header,members)
        for name in members:
            bad = dict(members); bad[name] = bad[name].replace(b'c'*64,b'd'*64)
            with self.subTest(name=name), self.assertRaises(CandidateError):
                verify_embedded_identity(identity,'kotlin','madbc07sdkkotlin',facade,header,bad)
        with self.assertRaises(CandidateError):
            verify_embedded_identity(identity,'kotlin','madbc07sdkkotlin',facade,header.replace(b'c'*64,b'd'*64),members)
        for name in ('libmadbc07sdkkotlin.so', 'libmadb_kotlin_owned_runtime.so'):
            bad = dict(members)
            bad['package/libs/arm64-v8a/' + name] += b'c/' + raw + b'\0'
            with self.subTest(name=name), self.assertRaisesRegex(CandidateError, 'route identity'):
                verify_embedded_identity(identity,'kotlin','madbc07sdkkotlin',facade,header,bad)


if __name__ == '__main__': unittest.main()
