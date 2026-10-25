"""Independent Kotlin 110/13 and control31 transport; never reinterpret C178."""
import json
import re
from c07_kotlin_admission_observations import LABELS as ADMISSION_LABELS, predicates as admission_predicates
MAX_SAFE=2**53-1
NATIVE_FIELDS="""Format ManagedState ReceiptConsumed InitAttempts InitFailures MainRejected IdentityRejected Initialized
ResidualErrors Allocations Releases ModelsLive WorkerStarts PhysicalJoins WorkCalls WorkCompleted Cancelled Discarded ValueCallbacks CallbackFailures Wakes WakeDisposals WakeRejected WakesLive OperationSlots SubscriptionSlots Waiters RetainedBytes EventTickets StateTickets SourceTickets EnteredTickets DispatchDepth ScratchAcquired ScratchReleased ReturnGuards Generation Closing EnvExiting EngineLive DispatcherLive WorkGateEntered SourceGateEntered WorkGate SourceGate
LifeContextsCreated LifeContextsDestroyed LifeContextsLive AsyncHooksAdded AsyncHooksRemoved AsyncHooksLive ActualCleanupEntered ActualCleanupReturned JoinJobsQueued JoinJobsStarted JoinJobsFinished AfterJoinEntered AfterJoinReturned JoinJobsLive StopRequests ExecutorAttached ExecutorDetached JoinSucceeded JoinFailed LifecycleCallbackFailed LifecycleResiduals LifecycleLastError LifecycleLastNapiStatus LifecycleLastUvStatus LifecycleCreateFailed LifecycleMainRejected LifecycleOwnerRejected
ManagedPhase ActiveEntries RejectedEntries Busy ShutdownRequests RefsOwned RefsCreated RefsReleased DescriptorsOwned DescriptorsCreated DescriptorsReleased ManagedHooksOwned ManagedHooksAdded ManagedHooksRemoved ManagedHooksInvoked ManagedFailures UnsupportedShutdown CleanupSnapshotPublished EventSequence OpenSequence GateSequence DrainSequence FinalizerSequence ContextSequence ClassRefsOwned ClassRefsCreated ClassRefsReleased TsfnOutstanding PayloadAllocated PayloadReleased TsfnCreated TsfnFinalized NullEnvDisposals EnqueueUncertain EnqueueRejected NativeNapiErrors TsfnContextsCreated TsfnContextsDestroyed""".split()
CONTROL_FIELDS="""Format WorkBeforeEntered WorkTerminalEntered WorkHeldPhase WorkGeneration WorkId WorkTerminal DeliveryState DeliverySubscriptionId DeliveryTakes DeliveryInvokes DeliveryDiscards PublicationState PublicationRecipients PublicationStagingBytes PublicationReservations PublicationCommits PublicationAbandons CloneCalls CloneHits CloneAllocations CloneReleases CloneLive CloneRemaining TransferArmedPhase AdmissionReturnFaults BeforeGuardFaults AfterGuardFaults GuardsEntered GuardsReleased ClaimsRolledBack""".split()
IDENTITY_INDICES={4,5,8}
SCENARIOS={"kotlin-admission":ADMISSION_LABELS}


def validate_kotlin_contracts(contracts, *, controls=False):
    try:
        frame=contracts["kotlin-frame-layout.json"]
        if (frame["format"]!=70501 or frame["length"]!=110 or
                [(f["index"],f["name"]) for f in frame["fields"]]!=list(enumerate(NATIVE_FIELDS))):
            return ["public Kotlin110 layout differs from independent field obligations"]
        if controls:
            layout=contracts["kotlin-controls-layout.json"]["frame"]
            if [(f["index"],f["name"]) for f in layout["fields"]]!=list(enumerate(CONTROL_FIELDS)):
                return ["public Kotlin31 layout differs from independent control obligations"]
        return []
    except (KeyError,TypeError):return ["missing explicit public Kotlin layout"]


def parse_control_csv(value):
    """Preserve decimal identities as strings; every other value is range checked."""
    if not isinstance(value,str):raise ValueError("Kotlin control frame must be a CSV string")
    fields=value.split(",")
    if len(fields)!=31:raise ValueError("Kotlin control frame must contain31 fields")
    result=[]
    for i,text in enumerate(fields):
        if not re.fullmatch(r"0|[1-9][0-9]*|-1",text):raise ValueError("noncanonical decimal control field")
        number=int(text)
        if i in IDENTITY_INDICES:
            if not 0<=number<2**64:raise ValueError("control identity outside uint64")
            result.append(text)
        else:
            if abs(number)>MAX_SAFE or number<0 and i!=6:raise ValueError("unsafe control counter")
            result.append(number)
    if result[0]!=1 or result[3] not in (0,1,2) or result[6] not in (-1,0,5,8,10) or any(result[i] not in (0,1,2,3) for i in (7,12,24)):
        raise ValueError("unsupported control format/state")
    return result


def parse_kotlin(raw, *, nonce, pid, case, contracts):
    result={"status":"unsupported","case":case,"route":"kotlin","nonce":nonce,
        "pid":int(pid) if isinstance(pid,str) and pid.isdigit() else None,
        "frames":{},"problems":[],"failures":[],"lines":[],"certifies_c07":False,
        "scope":"independent normal main-env Kotlin runtime; no host VM destruction or other route equivalence"}
    if case not in SCENARIOS:return result
    problems=result["problems"];problems.extend(validate_kotlin_contracts(contracts))
    if not isinstance(nonce,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",nonce) or result["pid"] is None or result["pid"]<=0:
        problems.append("missing exact nonce/live PID")
    if problems:result["status"]="failed";return result
    lines=[line for line in raw.splitlines() if re.search(r"(?<![A-Za-z0-9_-])"+re.escape(nonce)+r"(?![A-Za-z0-9_-])",line)]
    result["lines"]=lines;frames=result["frames"]
    if any(len(line.split())<3 or line.split()[2]!=pid for line in lines):problems.append("nonce/PID mismatch")
    begin=[];end=[]
    for line in lines:
        if "PROBE_FAILED "+nonce+" " in line:result["failures"].append(line)
        for marker,values in (("KOTLIN_BEGIN",begin),("KOTLIN_COMPLETE",end)):
            prefix=marker+" "+nonce+" "
            if prefix in line:values.append(line.split(prefix,1)[1].strip())
        prefix="KOTLIN_FRAME "+nonce+" "
        if prefix not in line:continue
        try:
            label,encoded=line.split(prefix,1)[1].split(" ",1);value=json.loads(encoded)
            if label not in SCENARIOS[case] or label in frames:problems.append("unknown/duplicate observation "+label);continue
            kind=SCENARIOS[case][label]
            if kind=="control":
                parse_control_csv(value)
            else:
                if not isinstance(value,list) or any(type(v) is not int or abs(v)>MAX_SAFE for v in value):raise ValueError("not a safe integer array")
                if kind=="native" and (len(value)!=110 or value[0]!=70501):raise ValueError("not a Kotlin110 frame")
                if kind=="admission" and (len(value)!=13 or any(v<0 for v in value)):raise ValueError("not an admission13 frame")
            frames[label]=value
        except (TypeError,ValueError) as error:problems.append("invalid Kotlin transport: "+str(error))
    if len(begin)>1 or begin and begin!=[case] or len(end)>1 or end and end!=[case]:problems.append("Kotlin begin/end mismatch")
    if end:
        if begin!=[case] or set(frames)!=set(SCENARIOS[case]):problems.append("missing exact Kotlin scenario observations")
        for marker in ("PROBE_STARTED","PROBE_PAGE_READY","PROBE_FINISHED"):
            if sum(bool(re.search(re.escape(marker+" "+nonce)+r"(?:\s|$)",line)) for line in lines)!=1:problems.append("missing/duplicate "+marker)
        if not problems and case=="kotlin-admission":problems.extend(admission_predicates(frames))
    result["status"]="failed" if problems or result["failures"] else "passed" if end else "incomplete"
    return result
