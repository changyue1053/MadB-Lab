"""Exact ordinary openRuntime rejection. No zero-owner diagnostic claim.

Actual unchanged ordinary HAR, single replaced native member, admitted fixture
source and target PID must be bound by the caller. Loader failure is not this case.
"""
import json,re
C3_ERRORS={'wrong-abi':'AbiMismatch','wrong-profile':'ProfileMismatch','wrong-build':'ArtifactMismatch'}
def expected_cases(route):
    if route in ('c','cpp','rust'):return {'ordinary-identity-'+kind:error for kind,error in C3_ERRORS.items()}
    if route=='kotlin':return {'ordinary-identity-'+kind+'-'+member:('IdentityMismatch' if member=='bootstrap' else 'ProviderIdentityMismatch') for kind in C3_ERRORS for member in ('bootstrap','provider')}
    return {}

def parse(raw,*,nonce,pid,case,route):
    expected=expected_cases(route)
    result={'status':'incomplete','case':case,'route':route,'nonce':nonce,'pid':None,
      'frames':{},'problems':[],'failures':[],'lines':[],'certifies_c07':False,
      'scope':'Actual ordinary openRuntime rejection only; owner counters must come from matched independent companion evidence'}
    problems=result['problems']
    if case not in expected:result.update(status='unsupported',problems=['unsupported ordinary identity case']);return result
    if not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',nonce) or not isinstance(pid,str) or not pid.isdigit() or int(pid)<=0:
        result.update(status='failed',problems=['exact nonce/live positive PID required']);return result
    result['pid']=int(pid)
    lines=[line for line in raw.splitlines() if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(nonce)+r'(?![A-Za-z0-9_-])',line)]
    result['lines']=lines
    if any(len(line.split())<3 or line.split()[2]!=pid for line in lines):problems.append('nonce/PID mismatch')
    frames=result['frames'];begin=[];end=[]
    for line in lines:
        if 'PROBE_FAILED '+nonce+' ' in line:result['failures'].append(line)
        for marker,target in (('ORDINARY_IDENTITY_BEGIN',begin),('ORDINARY_IDENTITY_COMPLETE',end)):
            prefix=marker+' '+nonce+' '
            if prefix in line:target.append(line.split(prefix,1)[1].strip())
        prefix='ORDINARY_IDENTITY_FRAME '+nonce+' '
        if prefix not in line:continue
        try:
            label,encoded=line.split(prefix,1)[1].split(' ',1);value=json.loads(encoded)
            if label not in ('stage','rejected') or label in frames or type(value) is not str:problems.append('unknown/duplicate/malformed ordinary identity frame')
            frames[label]=value
        except (ValueError,TypeError):problems.append('malformed ordinary identity transport')
    if len(begin)>1 or begin and begin!=[case] or len(end)>1 or end and end!=[case]:problems.append('begin/end case mismatch')
    if end:
        if begin!=[case] or list(frames)!=['stage','rejected'] or frames!={'stage':'ordinary-openRuntime-call','rejected':expected[case]}:problems.append('actual ordinary bootstrap stage/code missing or different')
        for marker in ('PROBE_STARTED','PROBE_PAGE_READY','PROBE_FINISHED'):
            if sum(bool(re.search(re.escape(marker+' '+nonce)+r'(?:\s|$)',line)) for line in lines)!=1:problems.append('missing/duplicate '+marker)
    result['status']='failed' if problems or result['failures'] else 'passed' if end else 'incomplete'
    return result
