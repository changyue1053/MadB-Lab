"""Independent exact-stage identity rejection, with monotonic actual bootstrap events."""
import json
import re
from c07_admission_observations import validate_contracts
SCENARIOS = ("identity-positive", "identity-wrong-abi", "identity-wrong-profile", "identity-wrong-build")
EVENTS = {"identity-wrong-abi":3,"identity-wrong-profile":4,"identity-wrong-build":5}
MAX_SAFE = 2**53-1


def parse_identity(raw, *, nonce, pid, case, route, contracts):
    result={"status":"incomplete","case":case,"route":route,"nonce":nonce,
        "pid":int(pid) if isinstance(pid,str) and pid.isdigit() else None,
        "frames":{},"problems":[],"failures":[],"lines":[],"certifies_c07":False,
        "scope":"actual public bootstrap rejection; no module-load failure equivalence"}
    problems=result["problems"]
    if route not in ("c","cpp","rust") or case not in SCENARIOS:
        result.update(status="unsupported",problems=["unsupported identity fixture route/case"]);return result
    problems.extend(validate_contracts(contracts))
    if not isinstance(nonce,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",nonce) or result["pid"] is None or result["pid"]<=0:
        result.update(status="failed",problems=problems+["invalid nonce/live PID"]);return result
    lines=[line for line in raw.splitlines() if re.search(r"(?<![A-Za-z0-9_-])"+re.escape(nonce)+r"(?![A-Za-z0-9_-])",line)]
    result["lines"]=lines;frames=result["frames"]
    if any(len(line.split())<3 or line.split()[2]!=pid for line in lines):problems.append("nonce/PID mismatch")
    required={"before":16,"after":16,**({"closed":178} if case=="identity-positive" else {"rejected":1})}
    begin=[];end=[]
    for line in lines:
        if "PROBE_FAILED "+nonce+" " in line:result["failures"].append(line)
        for marker,values in (("IDENTITY_BEGIN",begin),("IDENTITY_COMPLETE",end)):
            prefix=marker+" "+nonce+" "
            if prefix in line:values.append(line.split(prefix,1)[1].strip())
        prefix="IDENTITY_FRAME "+nonce+" "
        if prefix not in line:continue
        try:
            label,encoded=line.split(prefix,1)[1].split(" ",1);value=json.loads(encoded)
            if label not in required or label in frames:problems.append("unknown/duplicate frame "+label);continue
            if (not isinstance(value,list) or len(value)!=required[label] or
                    any(type(v) is not int or v<0 or v>MAX_SAFE for v in value)):
                problems.append("bad identity frame "+label)
            frames[label]=value
        except (TypeError,ValueError):problems.append("malformed identity transport")
    if len(begin)>1 or begin and begin!=[case] or len(end)>1 or end and end!=[case]:problems.append("case begin/end mismatch")
    if end:
        if begin!=[case] or set(frames)!=set(required):problems.append("missing exact identity observations")
        for marker in ("PROBE_STARTED","PROBE_PAGE_READY","PROBE_FINISHED"):
            if sum(bool(re.search(re.escape(marker+" "+nonce)+r"(?:\s|$)",line)) for line in lines)!=1:problems.append("missing/duplicate "+marker)
        if not problems:
            before,after=frames["before"],frames["after"]
            if before[0]!=1 or after[0]!=1:problems.append("bootstrap format differs")
            delta=[a-b for a,b in zip(after,before)];result["delta"]=delta
            if case!="identity-positive":
                event=EVENTS[case]
                if frames["rejected"]!=[event] or delta!=[0]+[int(i in (1,event)) for i in range(1,16)]:
                    problems.append("wrong bootstrap rejection or owner creation before identity admission")
            else:
                if delta!=[0,1,1,0,0,0,1,1,1,1,1,1,1,1,1,1]:problems.append("positive bootstrap did not create/release actual owners")
                f=frames["closed"]
                if any(f[i]!=v for i,v in {0:1,1:3,16:1,17:1,54:1,55:2,156:1}.items()):problems.append("positive control lacks physical ACK")
                if any(f[i]!=0 for i in (2,3,4,5,6,7,8,9,10,11,12,13,14,18,19,20,21,22,23,24,25,26,28,29,35,37,77,158,159,160,161,169,170)):
                    problems.append("positive control retains ownership or illegal API attempts")
                if any(f[i]!=f[i+1] for i in (33,38,40,42,44,46,48,50,52)) or any(f[i]!=1 for i in range(65,71)) or f[157]<=0:
                    problems.append("positive actual cleanup pairs/thread events missing")
    result["status"]="failed" if problems or result["failures"] else "passed" if end else "incomplete"
    return result
