"""KSP route negative controls, independent of compiler implementation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import file_digest
from c07_execution import ExecutionError
from c07_generation import fixture_files, generation_configuration
from c07_kotlin_generation import GENERATED, FUNCTIONS, TYPES, validate_facts, validate_kotlin_rejection, validate_port


def declared_kotlin():
    """Synthetic transport evidence. No execution or real KSP is claimed here."""
    function_parameters = {
        "ownedCancel": ([('operation', 'kotlin.String')], 'kotlin.Unit'),
        "ownedClaimResult": ([('operation', 'kotlin.String'), ('id', 'kotlin.String')], 'kotlin.Unit'),
        "ownedConnect": ([('runtime', 'kotlin.String')], 'kotlin.String'),
        "ownedDeliver": ([('subscription', 'kotlin.String')], 'kotlin.Int'),
        "ownedObserve": ([('engine', 'kotlin.String'), ('stream', 'kotlin.Int')], 'kotlin.String'),
        "ownedOpen": ([('observer', 'com.madb.c07.RuntimeDispatcher')], 'kotlin.String'),
        "ownedPeek": ([('runtime', 'kotlin.String'), ('id', 'kotlin.String')], 'kotlin.Int'),
        "ownedPublish": ([('snapshot', 'com.madb.c07.Parcel'), ('engine', 'kotlin.String'), ('stream', 'kotlin.Int')], 'kotlin.Unit'),
        "ownedRequestClose": ([('handle', 'kotlin.String')], 'kotlin.Unit'),
        "ownedRoundtrip": ([('snapshot', 'com.madb.c07.Parcel'), ('engine', 'kotlin.String')], 'com.madb.c07.Parcel'),
        "ownedRuntimeClose": ([('runtime', 'kotlin.String')], 'kotlin.Unit'),
        "ownedSubmit": ([('snapshot', 'com.madb.c07.Parcel'), ('engine', 'kotlin.String')], 'kotlin.String'),
        "ownedTakeSnapshot": ([('runtime', 'kotlin.String'), ('id', 'kotlin.String')], 'com.madb.c07.Parcel'),
        "ownedTakeStatus": ([('runtime', 'kotlin.String'), ('id', 'kotlin.String')], 'kotlin.Int'),
        "ownedWatchClose": ([('handle', 'kotlin.String'), ('id', 'kotlin.String')], 'kotlin.Int'),
    }
    types = {'kotlin.String': 'string', 'kotlin.Int': 'number', 'kotlin.Unit': 'void',
             'com.madb.c07.Parcel': 'Parcel', 'com.madb.c07.RuntimeDispatcher': 'RuntimeDispatcher'}
    fields = [{'name': 'value', 'kotlinType': 'kotlin.Int'}, {'name': 'text', 'kotlinType': 'kotlin.String'}]
    facts = {'schema': 'madb.kotlin-ksp-facts/1', 'record': {'qualifiedName': 'com.madb.c07.Parcel', 'fields': fields},
             'functions': [{'name': n, 'qualifiedName': 'com.madb.c07.' + n,
                            'parameters': [{'name': a, 'kotlinType': t} for a, t in p], 'returnType': r}
                           for n, (p, r) in sorted(function_parameters.items())]}
    callback_parameters = {'onReady': [], 'onValue': [('handle', 'kotlin.String'), ('snapshot', 'com.madb.c07.Parcel')],
                           'onClosed': [('handle', 'kotlin.String'), ('status', 'kotlin.Int')]}
    facts['interfaces'] = [{'qualifiedName': 'com.madb.c07.RuntimeDispatcher', 'methods': [
        {'name': n, 'parameters': [{'name': a, 'kotlinType': t} for a, t in p], 'returnType': 'kotlin.Unit'}
        for n, p in callback_parameters.items()]}]
    descriptor = {'authority': 'actual KSP symbols plus emitted declaration parsed by pinned TypeScript AST',
        'functions': [{'name': n, 'parameters': [{'name': a, 'type': types[t]} for a, t in p], 'returnType': types[r]}
                      for n, (p, r) in sorted(function_parameters.items())],
        'interfaces': [{'name': 'Parcel', 'members': [
            {'kind': 'property', 'name': 'value', 'type': 'number', 'readonly': True},
            {'kind': 'property', 'name': 'text', 'type': 'string', 'readonly': True}]},
            {'name': 'RuntimeDispatcher', 'members': [
                {'kind': 'method', 'name': n, 'parameters': [{'name': a, 'type': types[t]} for a, t in p], 'returnType': 'void'}
                for n, p in callback_parameters.items()]}]}
    schema = {'qualifiedName': 'com.madb.c07.Parcel', 'source': TYPES, 'fields': fields}
    texts = {name: '// synthetic generated evidence' for name in GENERATED}
    texts['resources/frontend-facts.json'] = json.dumps(facts)
    texts['resources/record-schema.json'] = json.dumps(schema)
    texts['resources/record-export.d.ts'] = 'export interface Parcel { readonly value: number; readonly text: string; }'
    texts['kotlin/org/cpf/kotlin/akinterop/generated/KNapiGenerated_MetaData.kt'] = 'KSPClass("Parcel", "com.madb.c07.Parcel")'
    return {'authority': 'actual CPF Kotlin KSP1 and akinterop 1.1.0; managed single-record profile',
            'test_support': False, 'typed_api_inferred': False, 'facts': facts, 'descriptor': descriptor,
            'record_schema': schema, 'declaration': texts['resources/record-export.d.ts'],
            'generated': [{'path': n, 'text': t, 'sha256': file_digest(t.encode()), 'size': len(t.encode())} for n, t in sorted(texts.items())]}


class KotlinGenerationTests(unittest.TestCase):
    def test_actual_kotlin_record_and_typed_decl_must_both_change(self):
        good = declared_kotlin()
        self.assertEqual(validate_facts(good)['record']['qualifiedName'], 'com.madb.c07.Parcel')
        for mutation in ('record', 'return', 'callback', 'missing', 'duplicate'):
            bad = deepcopy(good)
            if mutation == 'record': bad['facts']['record']['qualifiedName'] = 'com.madb.c07.Snapshot'
            if mutation == 'return': next(x for x in bad['facts']['functions'] if x['name'] == 'ownedRoundtrip')['returnType'] = 'com.madb.c07.Snapshot'
            if mutation == 'callback': bad['facts']['interfaces'][0]['methods'][0]['returnType'] = 'kotlin.Int'
            if mutation == 'missing': bad['descriptor']['functions'].pop()
            if mutation == 'duplicate': bad['facts']['functions'].append(bad['facts']['functions'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ExecutionError): validate_facts(bad)

    def test_generated_metadata_cannot_be_replaced_by_handwritten_claim(self):
        for mutation in ('bytes', 'stock', 'facts'):
            bad = declared_kotlin()
            item = next(x for x in bad['generated'] if x['path'].endswith('MetaData.kt' if mutation == 'stock' else 'frontend-facts.json'))
            item['text'] = '{}' if mutation == 'facts' else '// old Snapshot'
            if mutation != 'bytes':
                item.update(sha256=file_digest(item['text'].encode()), size=len(item['text'].encode()))
            with self.subTest(mutation=mutation), self.assertRaises(ExecutionError): validate_facts(bad)

    def test_private_port_alias_does_not_change_the_imported_record(self):
        for binding, local in (("Parcel", "Parcel"), ("Parcel as Snapshot", "Snapshot")):
            port = "import bootstrap, { OwnedApi, " + binding + ", RuntimeDispatcher } from 'libmadbc07sdkkotlin.so';\n"
            port += "onValue(handle: string, snapshot: " + local + "): void {}"
            validate_port(port)
            with self.assertRaises(ExecutionError): validate_port(port.replace(binding + ",", "Snapshot,"))
            with self.assertRaises(ExecutionError): validate_port(port.replace("snapshot: " + local, "snapshot: Other"))

    def test_pinned_kotlin_configuration_and_four_author_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'config.json'; path.write_text('{}')
            args = SimpleNamespace(route='kotlin', kotlin_configuration=path)
            with self.assertRaises(ExecutionError): generation_configuration(args)
            args.kotlin_configuration_sha256 = file_digest(path.read_bytes())
            arguments, paths = generation_configuration(args)
            self.assertEqual(paths, [path]); self.assertEqual(arguments[0], '--kotlin-configuration')
            args.rust_configuration = path
            with self.assertRaisesRegex(ExecutionError, 'only valid'): generation_configuration(args)
        self.assertEqual(set(fixture_files('kotlin')), {'BoundaryTypes.kt', 'OwnedExports.kt', 'Boundary.ets.in', 'runtime-policy.json'})
        self.assertEqual(len(fixture_files('c')), 2)

    def test_rejection_requires_real_author_line_and_no_committed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve(); author = output / 'workspace' / TYPES
            author.parent.mkdir(parents=True); author.write_text('interface RuntimeDispatcher {\n    suspend fun onReady()\n}\n')
            message = 'MADB_RECORD: suspend/generic/extension export unsupported'
            result = {'requested_stage': 'generate', 'completed_requested_stage': False, 'target_executed': False, 'error': message}
            (output / 'result.json').write_text(json.dumps(result))
            command = {'timeout': False, 'exit_code': 1, 'stderr': f'e: [ksp] {author}:2: {message}\n'}
            actual = validate_kotlin_rejection(output, command, 'reject-async')
            self.assertIsNone(actual['column']); self.assertEqual(actual['line'], 2)
            with self.assertRaises(ExecutionError): validate_kotlin_rejection(output, command, 'reject-async-listener')
            command['stderr'] = command['stderr'].replace(':2:', ':1:')
            with self.assertRaises(ExecutionError): validate_kotlin_rejection(output, command, 'reject-async')


if __name__ == '__main__': unittest.main()
