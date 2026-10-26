"""Independent Lab oracle for a fresh single-runtime normal-close NAPI scenario.

Inputs are original CSV Strings; before-open provider must be unavailable. Final
must be captured after the caller's independent normal Runtime.close physical ACK.
Static callsites are not proof that every imported API executed. No env validity
or transitive-library internals are observed by these counters.
"""
from __future__ import annotations
import re

MAX = (1 << 64) - 1
NA = str(MAX)
NEUTRAL = frozenset(('napi_acquire_threadsafe_function', 'napi_call_threadsafe_function',
                    'napi_call_threadsafe_function_with_priority', 'napi_release_threadsafe_function'))
ROLES = {'bootstrap': (0, 12, 1), 'provider': (1, 83, 6)}
OPTIONAL_CALLSITE = frozenset(('napi_create_callsite_info', 'napi_delete_callsite_info',
    'napi_get_property_with_callsite_info', 'napi_set_property_with_callsite_info'))


class NapiObservationFailure(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise NapiObservationFailure(message)


def category(name):
    if name in NEUTRAL:
        return 1
    if name == 'napi_module_register':
        return 2
    if name == 'napi_remove_async_cleanup_hook':
        return 3
    return 0


def parse_role(csv, role):
    require(type(csv) is str, role + ': original CSV string required')
    raw = tuple(csv.split(','))
    role_id, apis, capabilities = ROLES[role]
    require(len(raw) == 18 + apis, role + ': exact 30/101 width required')
    for index, token in enumerate(raw):
        require(re.fullmatch(r'0|[1-9][0-9]*', token) is not None, role + ': noncanonical uint64')
        require(len(token) < len(NA) or (len(token) == len(NA) and token <= NA), role + ': uint64 overflow')
        require(token != NA or (role == 'bootstrap' and index == 12), role + ': unexpected unavailable metric')
    require(raw[:4] == ('70602', str(role_id), str(apis), str(capabilities)), role + ': format/role/count/capability mismatch')
    require(raw[12] == NA if role == 'bootstrap' else raw[12] == '0', role + ': wrong-thread/NA contract')
    for index in (9, 10, 11, 13, 16):
        require(raw[index] == '0', role + ': observable violation at field ' + str(index))
    # This equals every env call, never an invalid-env count or a violation.
    require(raw[17] == raw[5], role + ': unknown-validity attempts must be retained, not zero-filled')
    if role == 'bootstrap':
        require(raw[15] == '0' and int(raw[14]) > 0, 'bootstrap legitimate-entry scope witness absent')
    else:
        require(raw[14] == '0' and raw[15] == '1', 'provider must bind exactly once in this fresh epoch')
    return raw


def parse(raw):
    require(type(raw) is str and raw.count(';') == 1, 'expected one original bootstrapCSV;providerCSV string')
    bootstrap, provider = raw.split(';')
    return {'bootstrap': parse_role(bootstrap, 'bootstrap'),
            'provider': None if provider == 'unavailable' else parse_role(provider, 'provider')}


def inventory(binding, identity):
    require(type(binding) is dict and binding.get('format') == 'madb.lab.kn-napi-static-binding/1' and binding.get('passed') is True,
            'independent actual-ELF binding required')
    require(type(identity) is dict and set(identity) == {'bootstrap', 'provider', 'contract'}, 'admitted candidate ELF/contract hashes required')
    require(binding['contract']['sha256'] == identity['contract'], 'candidate contract hash differs')
    fields = {}
    for role, (_, count, _) in ROLES.items():
        entry = binding['roles'][role]
        require(entry['library']['sha256'] == identity[role], role + ': candidate ELF differs from inspected file')
        apis = entry['api_fields']
        names = [a['name'] for a in apis]
        require(len(apis) == count and names == sorted(set(names)) == entry['actual_napi_imports'], role + ': actual imports/order differ')
        require(set(entry['callsites']) == set(names), role + ': per-API callsite binding incomplete')
        relocations = entry['napi_relocations']
        plt = {r['api'] for r in relocations if r['type'] == 'R_AARCH64_JUMP_SLOT'}
        got = {r['api'] for r in relocations if r['type'] == 'R_AARCH64_GLOB_DAT'}
        weak = entry.get('weak_got_imports', [])
        require(plt == set(names) and all(r['type'] in ('R_AARCH64_JUMP_SLOT', 'R_AARCH64_GLOB_DAT')
                and r['api'] in set(names) for r in relocations), role + ': native API relocation coverage differs')
        require(type(weak) is list and weak == sorted(got) and
                (not got or (role == 'provider' and got == OPTIONAL_CALLSITE)),
                role + ': unreviewed optional GOT address or missing actual WEAK binding')
        for index, api in enumerate(apis, 18):
            require(api['index'] == index and api['category'] == category(api['name']), role + ': independently classified field mismatch')
            sites = entry['callsites'][api['name']]
            require(sites['intercepted'] and sites['delegates'], role + ': API has no actual interception/delegation site')
        fields[role] = apis
    return fields


def coherent(raw, fields, role):
    # Only safe at a declared quiescent checkpoint, not concurrent opened frame.
    totals = [0, 0, 0, 0]
    for api in fields:
        totals[api['category']] += int(raw[api['index']])
    require([int(raw[i]) for i in (5, 6, 7, 8)] == totals, role + ': category totals do not match actual per-API counts')
    require(int(raw[4]) == sum(totals), role + ': total attempts not conserved')


def monotonic(a, b, role):
    for i in range(4, len(a)):
        if role == 'bootstrap' and i == 12:
            continue
        require(int(b[i]) >= int(a[i]), role + ': DSO-lifetime counter reset/regressed at ' + str(i))


def validate(before, opened, final, contracts, identity):
    fields = inventory(contracts, identity)
    frames = [parse(value) for value in (before, opened, final)]
    require(frames[0]['provider'] is None, 'fresh before-open provider must be unavailable; never fabricate zero frame')
    require(frames[1]['provider'] is not None and frames[2]['provider'] is not None, 'opened/final provider observation unavailable')
    coherent(frames[0]['bootstrap'], fields['bootstrap'], 'bootstrap-before')
    require(int(frames[0]['bootstrap'][7]) > 0, 'bootstrap actual module-registration attempt missing')
    results = {}
    for role in ROLES:
        a = frames[0][role] if role == 'bootstrap' else frames[1][role]
        b = frames[1][role]
        end = frames[2][role]
        monotonic(a, b, role)
        monotonic(b, end, role)
        coherent(end, fields[role], role + '-final')
        require(int(end[4]) > int(a[4]) and int(end[5]) > 0, role + ': no positive actual API-attempt witness')
        if role == 'provider':
            require(int(end[6]) > 0, 'provider thread-neutral TSFN attempts not exercised')
        exercised, unexercised = [], []
        for api in fields[role]:
            count = end[api['index']]
            record = {'api': api['name'], 'category': api['category'], 'attempts': count,
                      'delta_since_' + ('before_open' if role == 'bootstrap' else 'opened'): str(int(count) - int(a[api['index']])),
                      'direct_callsite_count': len(contracts['roles'][role]['callsites'][api['name']]['intercepted'])}
            (exercised if count != '0' else unexercised).append(record)
        results[role] = {'total_attempts': end[4], 'env_argument_attempts': end[5],
                         'thread_neutral_attempts': end[6], 'registration_attempts': end[7],
                         'cleanup_handle_attempts': end[8], 'wrong_thread_attempts': end[12],
                         'env_validity_unobserved_attempts': end[17],
                         'exercised_apis': exercised, 'unexercised_apis': unexercised}
    return {'scope': 'Observed attempts for inspected DSOs in a fresh normal-close scenario only',
            'observable_violation_check': 'passed', 'env_validity': 'unobserved',
            'transitive_library_calls': 'unobserved', 'raw': {'napi-before-open': before, 'napi-open': opened, 'napi-final': final},
            'candidate_hash_binding': dict(identity), 'roles': results,
            'limitations': ['Open CSV is not an atomic cross-thread snapshot; no cross-field sums asserted there',
                            'Final CSV must follow independent normal Runtime.close physical ACK',
                            'Zero per-API attempts means unexercised, not safe/valid execution',
                            'Static direct callsites do not prove dynamic path execution',
                            'Bootstrap scope count may include nested internal callback helpers']}
