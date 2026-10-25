"""Independent public identity-gate oracle; no producer imports or full110 zeros.

Caller binds original HAR/one actual replaced DSO/fixture/source/consumer/PID.
Unloaded provider is unavailable, not zero. Admission slot12 is ignored as a
resource witness because its metric accessor is unbound at both rejection gates.
"""
import json
import re

SCENARIOS = tuple('kotlin-identity-wrong-'+part+'-'+member
                  for part in ('abi','profile','build') for member in ('bootstrap','provider'))
LABELS = ('before-admission','before-napi','stage','rejected','after-admission','after-napi')
SAFE = (1 << 53) - 1
U64 = (1 << 64) - 1
DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)\Z')


def napi_pair(raw):
    if type(raw) is not str or raw.count(';') != 1:
        raise ValueError('NAPI pair must preserve original String')
    sides=[]
    for role,part in enumerate(raw.split(';')):
        if part == 'unavailable':
            if role == 0: raise ValueError('bootstrap observer unavailable')
            sides.append(None); continue
        words=part.split(','); count=(12,83)[role]
        if len(words)!=18+count or any(not DECIMAL.fullmatch(w) or len(w)>20 or int(w)>U64 for w in words):
            raise ValueError('NAPI frame not canonical fixed uint64 CSV')
        f=[int(w) for w in words]
        if f[:4] != [70602,role,count,(1,6)[role]]:
            raise ValueError('NAPI format/role/inventory/capabilities differ')
        if sum(f[18:])!=f[4] or sum(f[5:9])!=f[4] or f[17]!=f[5]:
            raise ValueError('actual API attempts not paired with categories')
        if role==0:
            if f[12]!=U64 or any(f[i] for i in (9,10,11,13,15,16)):
                raise ValueError('bootstrap illegal/unbound API attempt or unknown thread sentinel lost')
        elif any(f[i] for i in (9,10,11,12,13,16)):
            raise ValueError('provider illegal/unbound API attempt')
        sides.append(f)
    return sides


def predicates(case,frames):
    problems=[]
    if case not in SCENARIOS:return ['unsupported Kotlin identity case']
    try:
        if list(frames)!=list(LABELS):raise ValueError('exact frame order/labels required')
        for key in ('before-admission','after-admission'):
            f=frames[key]
            if type(f) is not list or len(f)!=13 or any(type(v) is not int or v<0 or v>SAFE for v in f):
                raise ValueError('admission13 exact safe integers required')
        before=frames['before-admission'];after=frames['after-admission']
        if before[:12]!=[0]*12:problems.append('identity fixture did not start fresh before admission')
        provider=case.endswith('-provider')
        expected=[1,1,0,1,1,0,0,1,1,0,0,0] if provider else [0,0,0,1,0,0,0,0,0,0,0,0]
        if after[:12]!=expected:problems.append('identity admission gate counters differ')
        if frames['stage']!='test-openRuntime-call' or frames['rejected']!=('ProviderIdentityMismatch' if provider else 'IdentityMismatch'):
            problems.append('actual stage/exact typed rejection missing')
        pre,pbefore=napi_pair(frames['before-napi']);post,pafter=napi_pair(frames['after-napi'])
        if pbefore is not None:problems.append('provider already observable before wrong-library admission')
        if not(pre[4]>0 and pre[7]>0 and pre[14]>0 and post[4]>pre[4] and post[14]>pre[14]):
            problems.append('no positive actual bootstrap API/scope evidence')
        if any(b<a for a,b in zip(pre[4:],post[4:])):problems.append('bootstrap observer reset history')
        if provider:
            if pafter is None:problems.append('loaded wrong provider lacks actual readonly observer')
            elif any(pafter[i] for i in range(4,len(pafter))):
                problems.append('wrong provider ran NAPI or bound owner before identity admission')
        elif pafter is not None:problems.append('wrong bootstrap reached provider before identity gate')
    except (ValueError,KeyError,TypeError,IndexError) as error:
        problems.append('malformed/missing identity observation: '+str(error))
    return problems


def parse(raw,*,nonce,pid,case,route='kotlin',**_):
    r={'status':'incomplete','case':case,'route':route,'nonce':nonce,'pid':None,'frames':{},'problems':[],
       'failures':[],'lines':[],'certifies_c07':False,
       'scope':'actual identity gate plus readonly NAPI attempts; no full110/default-zero resource claim',
       'not_resource_evidence':['admission[12] unbound metric fallback','unavailable provider is not zero']}
    p=r['problems']
    if route!='kotlin' or case not in SCENARIOS:r.update(status='unsupported',problems=['unsupported route/case']);return r
    if type(nonce) is not str or not re.fullmatch(r'[A-Za-z0-9_-]+',nonce) or type(pid) is not str or not pid.isdigit() or int(pid)<=0:
        r.update(status='failed',problems=['exact nonce and live positive PID required']);return r
    r['pid']=int(pid)
    lines=[line for line in raw.splitlines() if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(nonce)+r'(?![A-Za-z0-9_-])',line)]
    r['lines']=lines
    if any(len(line.split())<3 or line.split()[2]!=pid for line in lines):p.append('nonce/PID mismatch')
    begin=[];end=[]
    for line in lines:
        if 'PROBE_FAILED '+nonce+' ' in line:r['failures'].append(line)
        for marker,values in (('KOTLIN_IDENTITY_BEGIN',begin),('KOTLIN_IDENTITY_COMPLETE',end)):
            prefix=marker+' '+nonce+' '
            if prefix in line:values.append(line.split(prefix,1)[1].strip())
        prefix='KOTLIN_IDENTITY_FRAME '+nonce+' '
        if prefix not in line:continue
        try:
            label,value=line.split(prefix,1)[1].split(' ',1);value=json.loads(value)
            if label not in LABELS or label in r['frames']:p.append('unknown/duplicate frame '+label);continue
            r['frames'][label]=value
        except (ValueError,TypeError):p.append('malformed identity transport')
    if len(begin)>1 or begin and begin!=[case] or len(end)>1 or end and end!=[case]:p.append('begin/end case mismatch')
    if end:
        if begin!=[case]:p.append('missing exact begin')
        for marker in ('PROBE_STARTED','PROBE_PAGE_READY','PROBE_FINISHED'):
            if sum(bool(re.search(re.escape(marker+' '+nonce)+r'(?:\s|$)',line)) for line in lines)!=1:p.append('missing/duplicate '+marker)
        p.extend(predicates(case,r['frames']))
    r['status']='failed' if p or r['failures'] else 'passed' if end else 'incomplete'
    return r
