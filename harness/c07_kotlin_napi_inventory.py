"""Lab-owned final ELF/import/direct-callsite binder. No producer Python imports.

An inventory proves static interception at the inspected direct callsites only.
It does not prove execution, transitive-library interception, or env validity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

NEUTRAL = frozenset(('napi_acquire_threadsafe_function', 'napi_call_threadsafe_function',
                    'napi_call_threadsafe_function_with_priority', 'napi_release_threadsafe_function'))
COUNTS = {'bootstrap': 12, 'provider': 83}
# Four reviewed API24 optional entry addresses; never arbitrary NAPI pointers.
OPTIONAL_CALLSITE = frozenset(('napi_create_callsite_info', 'napi_delete_callsite_info',
    'napi_get_property_with_callsite_info', 'napi_set_property_with_callsite_info'))
FIXED_FIELDS = ('Format', 'Role', 'WrappedApiCount', 'Capabilities', 'TotalAttempts',
    'EnvArgumentAttempts', 'ThreadNeutralAttempts', 'RegistrationAttempts', 'CleanupHandleAttempts',
    'NullEnvAttempts', 'UnboundEnvAttempts', 'WrongEnvAttempts', 'WrongThreadAttempts',
    'UnboundCleanupHandleAttempts', 'BootstrapEntries', 'ProviderBindings', 'NullBindAttempts',
    'EnvValidityUnobservedAttempts')


def need(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def category(name):
    if name in NEUTRAL:
        return 1
    if name == 'napi_module_register':
        return 2
    if name == 'napi_remove_async_cleanup_hook':
        return 3
    return 0


def symbols(text):
    result = []
    for line in text.splitlines():
        columns = line.split()
        if len(columns) >= 8 and columns[0].rstrip(':').isdigit() and columns[0].endswith(':'):
            result.append({'type': columns[3], 'binding': columns[4], 'visibility': columns[5],
                           'section': columns[6], 'name': columns[7].split('@')[0]})
    return result


def inspect_symbols(rows, role, expected):
    actual = {r['name'] for r in rows if r['section'] == 'UND' and r['name'].startswith('napi_')}
    defined = {r['name'][7:] for r in rows if r['section'] != 'UND' and r['name'].startswith('__wrap_napi_')}
    need(actual == expected, f'{role}: actual final NAPI imports differ from contract')
    need(defined == expected, f'{role}: exact wrapper set absent or extra')
    need(not any(r['section'] == 'UND' and r['name'].startswith(('__real_napi_', '__wrap_napi_')) for r in rows), f'{role}: unresolved trampoline')
    need(all(r['binding'] == 'LOCAL' or r['visibility'] == 'HIDDEN' for r in rows if r['name'].startswith('__wrap_napi_')), f'{role}: wrapper exposed')
    metric = 'madb_kn_' + role + '_napi_metric'
    need(any(r['name'] == metric and r['section'] != 'UND' and r['binding'] == 'GLOBAL' and r['visibility'] == 'DEFAULT' for r in rows), f'{role}: missing metric export')
    return sorted(actual)


def callsites(text, expected):
    calls = {api: {'intercepted': [], 'delegates': []} for api in expected}
    function = None
    for line in text.splitlines():
        header = re.match(r'^([0-9a-fA-F]+) <([^>]+)>:$', line)
        if header:
            function = header.group(2)
            continue
        branch = re.match(r'^\s*([0-9a-fA-F]+):\s+(?:bl|b)\s+0x[0-9a-fA-F]+\s+<([^>]+)>', line)
        if not branch:
            continue
        target = branch.group(2)
        target_base = target.split('+')[0]
        site = {'address': '0x' + branch.group(1), 'function': function, 'target': target}
        if target_base.startswith('__wrap_napi_'):
            name = target_base[7:]
            need(name in expected, 'unexpected NAPI wrapper direct target ' + name)
            if function != '__wrap_' + name:
                need(target == '__wrap_' + name, 'branch enters middle of wrapper ' + target)
                calls[name]['intercepted'].append(site)
        elif target_base.startswith('napi_') and target_base.endswith('@plt'):
            name = target_base[:-4]
            need(name in expected, 'unexpected real NAPI direct target ' + name)
            need(function == '__wrap_' + name, 'NAPI direct call bypasses wrapper: ' + str(site))
            calls[name]['delegates'].append(site)
        elif target_base.startswith('__real_napi_'):
            raise ValueError('unresolved direct __real call ' + str(site))
    for name, entries in calls.items():
        need(entries['delegates'], name + ': real delegation site missing')
        need(entries['intercepted'], name + ': no actual producer direct caller of wrapper')
    return calls


def contract_roles(contract):
    need(contract.get('format') == 70602, 'observer format changed; explicit review required')
    need(contract.get('fixed_fields') == [{'index': i, 'name': n} for i, n in enumerate(FIXED_FIELDS)], 'fixed observer field semantics changed')
    roles = {r['role']: r for r in contract['roles']}
    need(set(roles) == set(COUNTS), 'observer roles changed')
    result = {}
    for role, count in COUNTS.items():
        record = roles[role]
        apis = record['per_api_fields']
        names = [a['name'] for a in apis]
        need(record['count'] == count + 18 and len(apis) == count, role + ': reviewed 12/83 closure changed')
        need(names == sorted(set(names)), role + ': API ordering/uniqueness changed')
        for index, api in enumerate(apis, 18):
            name = api['name']
            need(api['index'] == index and api['category'] == category(name), role + ': category/index mismatch ' + name)
            first = api['arguments'][0]
            expected = ('napi_env', 'napi_threadsafe_function', 'napi_module *', 'napi_async_cleanup_hook_handle')[category(name)]
            need(first == expected, role + ': no-env/env classification mismatches declared SDK signature ' + name)
        result[role] = [{'index': a['index'], 'name': a['name'], 'category': category(a['name'])} for a in apis]
    return result


def inspect_relocations(text, rows, role, expected):
    relocations = []
    weak_got = set()
    for line in text.splitlines():
        match = re.search(r'\b(R_AARCH64_\S+)\s+[0-9a-fA-F]+\s+(napi_\w+)\b', line)
        if not match:
            continue
        kind, api = match.groups()
        need(api in expected, role + ': relocation outside NAPI inventory')
        if kind == 'R_AARCH64_GLOB_DAT':
            entries = [r for r in rows if r['name'] == api and r['section'] == 'UND']
            need(role == 'provider' and api in OPTIONAL_CALLSITE and entries
                 and all(r['binding'] == 'WEAK' for r in entries),
                 role + ': only reviewed optional WEAK callsite addresses may use GOT')
            weak_got.add(api)
        else:
            need(kind == 'R_AARCH64_JUMP_SLOT', role + ': unreviewed real-NAPI pointer relocation')
        relocations.append({'type': kind, 'api': api})
    need({r['api'] for r in relocations if r['type'] == 'R_AARCH64_JUMP_SLOT'} == expected,
         role + ': actual NAPI PLT relocation inventory incomplete')
    need(not weak_got or weak_got == OPTIONAL_CALLSITE,
         role + ': optional callsite address quartet incomplete')
    return relocations, sorted(weak_got)


def build(contract_path, libraries, readelf, objdump, output):
    output = Path(output)
    output.mkdir(exist_ok=False, parents=True)
    contract = json.loads(Path(contract_path).read_text())
    roles = contract_roles(contract)
    result = {'format': 'madb.lab.kn-napi-static-binding/1',
              'scope': 'Exact inspected ELF symbols and direct callsites; not dynamic API execution or env-validity proof',
              'contract': pin(contract_path), 'tools': {'readelf': pin(readelf), 'objdump': pin(objdump)}, 'roles': {}}
    for role, library in libraries.items():
        captures = {}
        for label, command in (
            ('symbols', [readelf, '--symbols', '--wide', library]),
            ('relocations', [readelf, '--relocs', '--wide', library]),
            ('disassembly', [objdump, '-d', '--no-show-raw-insn', library]),
        ):
            process = subprocess.run(command, text=True, capture_output=True, timeout=90)
            need(process.returncode == 0, role + ': tool failed ' + process.stderr)
            path = output / f'{role}-{label}.txt'
            path.write_text(process.stdout)
            captures[label] = {'command': command, 'output': pin(path), 'text': process.stdout}
        expected = {a['name'] for a in roles[role]}
        symbol_rows = symbols(captures['symbols']['text'])
        actual = inspect_symbols(symbol_rows, role, expected)
        sites = callsites(captures['disassembly']['text'], expected)
        relocations, weak_got = inspect_relocations(captures['relocations']['text'], symbol_rows, role, expected)
        for capture in captures.values():
            del capture['text']
        result['roles'][role] = {'library': pin(library), 'api_fields': roles[role], 'actual_napi_imports': actual,
                                 'callsites': sites, 'napi_relocations': relocations,
                                 'weak_got_imports': weak_got, 'captures': captures}
    result['passed'] = True
    (output / 'binding.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('contract', 'bootstrap', 'provider', 'readelf', 'objdump', 'output'):
        parser.add_argument('--' + name, required=True)
    a = parser.parse_args()
    result = build(a.contract, {'bootstrap': a.bootstrap, 'provider': a.provider}, a.readelf, a.objdump, a.output)
    print(json.dumps({'binding': pin(Path(a.output) / 'binding.json'),
                      'api_counts': {k: len(v['api_fields']) for k,v in result['roles'].items()}}))

if __name__ == '__main__':
    main()
