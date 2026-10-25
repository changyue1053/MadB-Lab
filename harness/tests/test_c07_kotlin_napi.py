"""Independent synthetic counterexamples; no target NAPI execution is claimed."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import copy
import unittest

from c07_kotlin_napi_inventory import callsites, inspect_symbols
from c07_kotlin_napi_observations import NA, NapiObservationFailure, validate

from c07_synthetic_napi_binding import synthetic_binding


def fixture_binding():
    return synthetic_binding()


def encoded(role, binding, calls, entries=0):
    values = [0] * (18 + len(binding['roles'][role]['api_fields']))
    values[:4] = [70602, 0 if role == 'bootstrap' else 1, 12 if role == 'bootstrap' else 83, 1 if role == 'bootstrap' else 6]
    values[12] = NA if role == 'bootstrap' else 0
    values[14] = entries if role == 'bootstrap' else 0
    values[15] = 0 if role == 'bootstrap' else 1
    for api in binding['roles'][role]['api_fields']:
        value = calls.get(api['name'], 0)
        values[api['index']] = value
        values[5 + api['category']] += value
        values[4] += value
    values[17] = values[5]
    return ','.join(map(str, values))


def positive():
    binding = fixture_binding()
    identity = {r: binding['roles'][r]['library']['sha256'] for r in ('bootstrap', 'provider')}
    identity['contract'] = binding['contract']['sha256']
    b0 = {'napi_module_register': 1, 'napi_create_object': 1, 'napi_define_properties': 1}
    b1 = dict(b0, napi_get_cb_info=4, napi_create_string_utf8=1)
    b2 = dict(b1, napi_get_cb_info=7, napi_create_string_utf8=5)
    p1 = {'napi_create_threadsafe_function': 1, 'napi_create_reference': 2,
          'napi_get_uv_event_loop': 1, 'napi_add_async_cleanup_hook': 1}
    p2 = dict(p1, napi_delete_reference=2, napi_remove_async_cleanup_hook=1,
              napi_call_threadsafe_function=1, napi_release_threadsafe_function=1)
    return [encoded('bootstrap', binding, b0, 1) + ';unavailable',
            encoded('bootstrap', binding, b1, 2) + ';' + encoded('provider', binding, p1),
            encoded('bootstrap', binding, b2, 3) + ';' + encoded('provider', binding, p2), binding, identity]


def set_field(args, moment, role, index, value):
    parts = args[moment].split(';')
    fields = parts[role].split(',')
    fields[index] = str(value)
    parts[role] = ','.join(fields)
    args[moment] = ';'.join(parts)


class NapiChecks(unittest.TestCase):
    def test_positive_unknown_validity_and_unexercised_are_explicit(self):
        args = positive()
        result = validate(*args)
        self.assertEqual(result['env_validity'], 'unobserved')
        self.assertEqual(result['roles']['bootstrap']['wrong_thread_attempts'], NA)
        self.assertEqual(result['roles']['provider']['env_validity_unobserved_attempts'], '7')
        self.assertEqual(result['roles']['provider']['thread_neutral_attempts'], '2')
        self.assertTrue(result['roles']['provider']['unexercised_apis'])
        self.assertEqual(result['raw']['napi-final'], args[2])

    def test_uint64_attempts_remain_exact_strings(self):
        args = positive()
        fields = args[2].split(';')[0].split(',')
        api = next(a for a in args[3]['roles']['bootstrap']['api_fields'] if a['name'] == 'napi_create_string_utf8')
        increment = 9007199254740993
        for index in (4, 5, 17, api['index']):
            set_field(args, 2, 0, index, int(fields[index]) + increment)
        result = validate(*args)
        self.assertEqual(result['roles']['bootstrap']['env_argument_attempts'], str(int(fields[5]) + increment))
        self.assertEqual(result['raw']['napi-final'], args[2])

    def test_open_concurrent_snapshot_not_falsely_rejected(self):
        args = positive()
        # Worker increments total before its neutral/per-API counts are read.
        fields = args[1].split(';')[1].split(',')
        set_field(args, 1, 1, 4, int(fields[4]) + 1)
        validate(*args)

    def test_observable_violations_na_and_unknown_mutations_rejected(self):
        for role, index, value in [(r, i, 1) for r in (0, 1) for i in (9, 10, 11, 13, 16)] + [
                (1, 12, 1), (0, 12, 0), (1, 12, NA), (1, 17, 0), (0, 17, 0),
                (1, 15, 0), (1, 15, 2), (0, 3, 6), (1, 3, 1), (1, 2, 82)]:
            with self.subTest(role=role, index=index, value=value):
                args = positive(); set_field(args, 2, role, index, value)
                with self.assertRaises(NapiObservationFailure): validate(*args)

    def test_missing_provider_zero_frames_and_wrong_wire_rejected(self):
        for mutation in ('unavailable-final', 'zero-provider', 'loaded-before', 'float', 'overflow', 'negative', 'extra-field', 'extra-role'):
            args = positive()
            if mutation == 'unavailable-final': args[2] = args[2].split(';')[0] + ';unavailable'
            elif mutation == 'zero-provider': args[2] = args[2].split(';')[0] + ';' + ','.join(['0'] * 101)
            elif mutation == 'loaded-before': args[0] = args[0].split(';')[0] + ';' + args[1].split(';')[1]
            elif mutation == 'float': set_field(args, 2, 1, 5, '7.0')
            elif mutation == 'overflow': set_field(args, 2, 1, 5, '18446744073709551616')
            elif mutation == 'negative': set_field(args, 2, 1, 5, '-1')
            elif mutation == 'extra-field': args[2] += ',0'
            else: args[2] += ';unavailable'
            with self.subTest(mutation=mutation), self.assertRaises(NapiObservationFailure): validate(*args)

    def test_exact_final_category_conservation_and_monotonicity(self):
        for index in (4, 5, 6, 7, 8, 18):
            args = positive(); fields = args[2].split(';')[1].split(',')
            set_field(args, 2, 1, index, int(fields[index]) + 1)
            with self.subTest(index=index), self.assertRaises(NapiObservationFailure): validate(*args)
        args = positive(); set_field(args, 1, 1, 4, 100)
        with self.assertRaises(NapiObservationFailure): validate(*args)

    def test_candidate_inventory_binding_is_mandatory(self):
        for mutation in ('elf-hash', 'contract-hash', 'category', 'index', 'missing-api', 'missing-caller', 'missing-delegate', 'imports', 'pointer-relocation', 'not-passed'):
            args = positive(); b = args[3]
            if mutation == 'elf-hash': args[4]['provider'] = '0' * 64
            elif mutation == 'contract-hash': args[4]['contract'] = '0' * 64
            elif mutation == 'category': b['roles']['provider']['api_fields'][0]['category'] = 0
            elif mutation == 'index': b['roles']['provider']['api_fields'][0]['index'] = 19
            elif mutation == 'missing-api': b['roles']['provider']['api_fields'].pop()
            elif mutation in ('missing-caller', 'missing-delegate'):
                kind = 'intercepted' if mutation == 'missing-caller' else 'delegates'
                b['roles']['provider']['callsites']['napi_acquire_threadsafe_function'][kind] = []
            elif mutation == 'imports': b['roles']['provider']['actual_napi_imports'].pop()
            elif mutation == 'pointer-relocation': b['roles']['provider']['napi_relocations'][0]['type'] = 'R_AARCH64_GLOB_DAT'
            else: b['passed'] = False
            with self.subTest(mutation=mutation), self.assertRaises(NapiObservationFailure): validate(*args)

    def test_static_direct_bypass_and_middle_entry_rejected(self):
        text = ('00000100 <caller>:\n  100: bl 0x200 <__wrap_napi_get_undefined>\n'
                '00000200 <__wrap_napi_get_undefined>:\n  200: b 0x300 <napi_get_undefined@plt>\n')
        good = callsites(text, {'napi_get_undefined'})
        self.assertEqual(len(good['napi_get_undefined']['intercepted']), 1)
        for bad in (text.replace('bl 0x200 <__wrap_napi_get_undefined>', 'bl 0x300 <napi_get_undefined@plt>'),
                    text.replace('bl 0x200 <__wrap_napi_get_undefined>', 'bl 0x204 <__wrap_napi_get_undefined+0x4>'),
                    text.replace('  200: b 0x300 <napi_get_undefined@plt>\n', '')):
            with self.assertRaises(ValueError): callsites(bad, {'napi_get_undefined'})

    def test_static_symbol_closure_rejects_missing_or_unwrapped(self):
        rows = [{'name':'napi_get_undefined','section':'UND','type':'FUNC','binding':'GLOBAL','visibility':'DEFAULT'},
                {'name':'__wrap_napi_get_undefined','section':'12','type':'FUNC','binding':'LOCAL','visibility':'HIDDEN'},
                {'name':'madb_kn_bootstrap_napi_metric','section':'12','type':'FUNC','binding':'GLOBAL','visibility':'DEFAULT'}]
        inspect_symbols(rows, 'bootstrap', {'napi_get_undefined'})
        for bad in (rows[:1] + rows[2:], rows + [dict(rows[0], name='napi_get_null')],
                    [rows[0], dict(rows[1], binding='GLOBAL', visibility='DEFAULT'), rows[2]]):
            with self.assertRaises(ValueError): inspect_symbols(bad, 'bootstrap', {'napi_get_undefined'})


if __name__ == '__main__':
    unittest.main()
