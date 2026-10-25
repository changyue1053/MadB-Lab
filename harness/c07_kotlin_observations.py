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
from c07_kotlin_value_observations import SCENARIOS as VALUE_SCENARIOS, predicates as value_predicates
from c07_kotlin_work_observations import SCENARIOS as WORK_SCENARIOS, predicates as work_predicates
from c07_kotlin_stream_observations import validate as validate_stream
from c07_kotlin_napi_observations import parse as parse_napi, validate as validate_napi, inventory as napi_inventory
from c07_kotlin_memory_observations import SCENARIOS as MEMORY_SCENARIOS, predicates as memory_predicates, parse_memory_csv
from c07_kotlin_operation_observations import SCENARIOS as OPERATION_SCENARIOS, predicates as operation_predicates
from c07_kotlin_handle_observations import SCENARIOS as HANDLE_SCENARIOS, predicates as handle_predicates
from c07_kotlin_fault_observations import SCENARIOS as FAULT_SCENARIOS, predicates as fault_predicates
from c07_kotlin_listener_observations import SCENARIOS as LISTENER_SCENARIOS, predicates as listener_predicates
from c07_kotlin_waiter_observations import SCENARIOS as WAITER_SCENARIOS, predicates as waiter_predicates, EXPECTED_ENGINE_COUNTS
from c07_kotlin_thread_observations import SCENARIOS as THREAD_SCENARIOS, FIELDS as THREAD_FIELDS, parse as parse_thread, predicates as thread_predicates
ADMISSION_FIELDS = "InitAttempts InitFailures MainRejected IdentityRejected LibraryLoaded Initialized Slot Epoch RollbackAcks LastFailureStage Delivered Consumed TsfnAdmissionFailures".split()
SETTLEMENT_FIELDS = "Arms Hits ResolveAccepted RejectAccepted Exceptions CurrentSettling MaxObservedWaiterMap TimerArmed TickInFlight".split()
MEMORY_FIELDS = ['Format', 'LedgerCurrentBytes', 'LedgerPeakBytes', 'LedgerChargedBytes', 'LedgerRetiredBytes', 'ModelRequestedCurrentBytes', 'ModelRequestedPeakBytes', 'ModelAllocatedBytes', 'ModelFreedBytes', 'ModelAllocations', 'ModelFrees', 'StagingCurrentBytes', 'StagingPeakBytes', 'StagingAddedBytes', 'StagingCommittedBytes', 'StagingAbandonedBytes', 'Utf16CurrentRequestedBytes', 'Utf16PeakRequestedBytes', 'Utf16AllocatedBytes', 'Utf16FreedBytes', 'Utf16Allocations', 'Utf16Releases']
COMMON_LABELS = {"runtime-open": "native", "runtime-closed": "native", "runtime-complete": "vector", "js-final": "settling", "napi-before-open":"napi", "napi-open":"napi", "napi-final":"napi"}


STREAM_SCENARIOS = {'kotlin-state': {'kn-stream-state-drained-native': 'native',
                  'kn-stream-state-entry-before-next': 'vector',
                  'kn-stream-state-entry-before-next-native': 'native',
                  'kn-stream-state-entry-current': 'vector',
                  'kn-stream-state-entry-new-trace': 'vector',
                  'kn-stream-state-entry-original-trace': 'vector',
                  'kn-stream-state-entry-replaced-native': 'native',
                  'kn-stream-state-held-native': 'native',
                  'kn-stream-state-release-sync': 'vector',
                  'kn-stream-state-replaced-native': 'native',
                  'kn-stream-state-trace': 'vector',
                  'kn-stream-state-held-control': 'control',
                  'kn-stream-state-replaced-control': 'control'},
 'kotlin-state-staging-bytes': {'kn-stream-staging-abort-native': 'native',
                                'kn-stream-staging-commit-sync': 'vector',
                                'kn-stream-staging-full-native': 'native',
                                'kn-stream-staging-held-native': 'native',
                                'kn-stream-staging-rejected-native': 'native',
                                'kn-stream-staging-trace-0': 'vector',
                                'kn-stream-staging-trace-1': 'vector',
                                'kn-stream-staging-trace-2': 'vector',
                                'kn-stream-staging-trace-3': 'vector',
                                'kn-stream-staging-abort-after-control': 'control',
                                'kn-stream-staging-abort-before-control': 'control',
                                'kn-stream-staging-held-control': 'control'},
 'kotlin-event-fifo-and-atomic': {'kn-stream-event-empty-after-native': 'native',
                                  'kn-stream-event-empty-before-native': 'native',
                                  'kn-stream-event-entered-native': 'native',
                                  'kn-stream-event-fanout-rejected-native': 'native',
                                  'kn-stream-event-fanout-six-native': 'native',
                                  'kn-stream-event-fanout-trace-0': 'vector',
                                  'kn-stream-event-fanout-trace-1': 'vector',
                                  'kn-stream-event-fanout-trace-2': 'vector',
                                  'kn-stream-event-full-native': 'native',
                                  'kn-stream-event-isolation-event-trace': 'vector',
                                  'kn-stream-event-isolation-state-trace': 'vector',
                                  'kn-stream-event-outstanding-entered-native': 'native',
                                  'kn-stream-event-outstanding-rejected-native': 'native',
                                  'kn-stream-event-outstanding-rejections': 'vector',
                                  'kn-stream-event-outstanding-trace-0': 'vector',
                                  'kn-stream-event-outstanding-trace-1': 'vector',
                                  'kn-stream-event-rejected-native': 'native',
                                  'kn-stream-event-release-sync': 'vector',
                                  'kn-stream-event-trace': 'vector',
                                  'kn-stream-event-held-control': 'control'},
 'kotlin-source-stop': {'kn-stream-delivery-stop-0-closed-native': 'native',
                        'kn-stream-delivery-stop-0-pending': 'vector',
                        'kn-stream-delivery-stop-0-pending-native': 'native',
                        'kn-stream-delivery-stop-0-release-sync': 'vector',
                        'kn-stream-delivery-stop-1-closed-native': 'native',
                        'kn-stream-delivery-stop-1-pending': 'vector',
                        'kn-stream-delivery-stop-1-pending-native': 'native',
                        'kn-stream-delivery-stop-1-release-sync': 'vector',
                        'kn-stream-source-0-abandoned-native': 'native',
                        'kn-stream-source-0-abort-held-native': 'native',
                        'kn-stream-source-0-abort-released-native': 'native',
                        'kn-stream-source-0-held-native': 'native',
                        'kn-stream-source-0-live-trace': 'vector',
                        'kn-stream-source-0-pending': 'vector',
                        'kn-stream-source-0-stopped-trace': 'vector',
                        'kn-stream-source-1-abandoned-native': 'native',
                        'kn-stream-source-1-abort-held-native': 'native',
                        'kn-stream-source-1-abort-released-native': 'native',
                        'kn-stream-source-1-held-native': 'native',
                        'kn-stream-source-1-live-trace': 'vector',
                        'kn-stream-source-1-pending': 'vector',
                        'kn-stream-source-1-stopped-trace': 'vector',
                        'kn-stream-delivery-stop-0-baseline-control': 'control',
                        'kn-stream-delivery-stop-0-closed-control': 'control',
                        'kn-stream-delivery-stop-0-held-control': 'control',
                        'kn-stream-delivery-stop-1-baseline-control': 'control',
                        'kn-stream-delivery-stop-1-closed-control': 'control',
                        'kn-stream-delivery-stop-1-held-control': 'control',
                        'kn-stream-source-0-abandoned-control': 'control',
                        'kn-stream-source-0-abort-after-control': 'control',
                        'kn-stream-source-0-abort-before-control': 'control',
                        'kn-stream-source-0-held-control': 'control',
                        'kn-stream-source-1-abandoned-control': 'control',
                        'kn-stream-source-1-abort-after-control': 'control',
                        'kn-stream-source-1-abort-before-control': 'control',
                        'kn-stream-source-1-held-control': 'control'},
 'kotlin-fanout-allocation': {'kn-stream-clone-0-owned-after-native': 'native',
                              'kn-stream-clone-0-owned-before-native': 'native',
                              'kn-stream-clone-0-owned-trace-0': 'vector',
                              'kn-stream-clone-0-owned-trace-1': 'vector',
                              'kn-stream-clone-0-owned-trace-2': 'vector',
                              'kn-stream-clone-0-pre-after-native': 'native',
                              'kn-stream-clone-0-pre-before-native': 'native',
                              'kn-stream-clone-0-pre-trace-0': 'vector',
                              'kn-stream-clone-0-pre-trace-1': 'vector',
                              'kn-stream-clone-0-pre-trace-2': 'vector',
                              'kn-stream-clone-1-owned-after-native': 'native',
                              'kn-stream-clone-1-owned-before-native': 'native',
                              'kn-stream-clone-1-owned-trace-0': 'vector',
                              'kn-stream-clone-1-owned-trace-1': 'vector',
                              'kn-stream-clone-1-owned-trace-2': 'vector',
                              'kn-stream-clone-1-pre-after-native': 'native',
                              'kn-stream-clone-1-pre-before-native': 'native',
                              'kn-stream-clone-1-pre-trace-0': 'vector',
                              'kn-stream-clone-1-pre-trace-1': 'vector',
                              'kn-stream-clone-1-pre-trace-2': 'vector',
                              'kn-stream-clone-0-owned-after-control': 'control',
                              'kn-stream-clone-0-owned-before-control': 'control',
                              'kn-stream-clone-0-pre-after-control': 'control',
                              'kn-stream-clone-0-pre-before-control': 'control',
                              'kn-stream-clone-1-owned-after-control': 'control',
                              'kn-stream-clone-1-owned-before-control': 'control',
                              'kn-stream-clone-1-pre-after-control': 'control',
                              'kn-stream-clone-1-pre-before-control': 'control'}}
SCENARIOS = {"kotlin-admission": ADMISSION_LABELS, **{name: {**labels, **COMMON_LABELS} for name, labels in {**VALUE_SCENARIOS, **WORK_SCENARIOS, **STREAM_SCENARIOS, **MEMORY_SCENARIOS, **OPERATION_SCENARIOS, **HANDLE_SCENARIOS, **FAULT_SCENARIOS, **LISTENER_SCENARIOS, **WAITER_SCENARIOS, **THREAD_SCENARIOS}.items()}}


def validate_kotlin_contracts(contracts, *, controls=False, admission=False, settling=False, memory=False):
    try:
        frame=contracts["kotlin-frame-layout.json"]
        if (frame["format"]!=70501 or frame["length"]!=110 or
                [(f["index"],f["name"]) for f in frame["fields"]]!=list(enumerate(NATIVE_FIELDS))):
            return ["public Kotlin110 layout differs from independent field obligations"]
        if controls:
            layout=contracts["kotlin-controls-layout.json"]["frame"]
            if [(f["index"],f["name"]) for f in layout["fields"]]!=list(enumerate(CONTROL_FIELDS)):
                return ["public Kotlin31 layout differs from independent control obligations"]
        for enabled, key, names in ((admission, "admission-frame.json", ADMISSION_FIELDS),
                                    (settling, "settlement-frame.json", SETTLEMENT_FIELDS),
                                    (memory, "memory-frame.json", MEMORY_FIELDS)):
            if enabled:
                layout = contracts[key]
                if layout["length"] != len(names) or [(f["index"], f["name"]) for f in layout["fields"]] != list(enumerate(names)):
                    return ["public " + key + " differs from independent field obligations"]
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


def parse_kotlin(raw, *, nonce, pid, case, contracts, napi_binding=None, napi_identity=None):
    result={"status":"unsupported","case":case,"route":"kotlin","nonce":nonce,
        "pid":int(pid) if isinstance(pid,str) and pid.isdigit() else None,
        "frames":{},"problems":[],"failures":[],"lines":[],"certifies_c07":False,
        "scope":"independent normal main-env Kotlin runtime; no host VM destruction or other route equivalence"}
    if case not in SCENARIOS:return result
    problems=result["problems"]
    kinds = set(SCENARIOS[case].values())
    problems.extend(validate_kotlin_contracts(contracts, controls="control" in kinds,
        admission="admission" in kinds, settling="settling" in kinds, memory="memory" in kinds))
    if not isinstance(nonce,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",nonce) or result["pid"] is None or result["pid"]<=0:
        problems.append("missing exact nonce/live PID")
    if problems:result["status"]="failed";return result
    if case in LISTENER_SCENARIOS or case == "kotlin-distinct-close-denied":
        layout=contracts.get("subscription-frame.json",{})
        if layout.get("format")!=1 or layout.get("length")!=4 or [(f.get("index"),f.get("name")) for f in layout.get("fields",[])]!=list(enumerate(("Format","Closing","Closed","ListenerPresent"))):
            result.update(status="failed",problems=["missing exact retained Kotlin subscription-record contract"]);return result
    if case in THREAD_SCENARIOS:
        layout=contracts.get("thread-frame.json",{})
        if layout.get("format")!=70604 or layout.get("length")!=21 or [(f.get("index"),f.get("name")) for f in layout.get("fields",[])]!=list(enumerate(THREAD_FIELDS)):
            result.update(status="failed",problems=["missing exact Kotlin simultaneous-thread contract"]);return result
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
            elif kind=="memory":
                parse_memory_csv(value)
            elif kind=="thread":
                parse_thread(value)
            elif kind=="napi":
                parse_napi(value)
            else:
                if not isinstance(value,list) or any(type(v) is not int or abs(v)>MAX_SAFE for v in value):raise ValueError("not a safe integer array")
                if kind=="native" and (len(value)!=110 or value[0]!=70501 or any(v<0 for v in value)):raise ValueError("not a Kotlin110 frame")
                if kind=="admission" and (len(value)!=13 or any(v<0 for v in value)):raise ValueError("not an admission13 frame")
                if kind=="settling" and (len(value)!=9 or any(v<0 for v in value)):raise ValueError("not a settlement9 frame")
            frames[label]=value
        except (TypeError,ValueError) as error:problems.append("invalid Kotlin transport: "+str(error))
    if len(begin)>1 or begin and begin!=[case] or len(end)>1 or end and end!=[case]:problems.append("Kotlin begin/end mismatch")
    if end:
        if begin!=[case] or set(frames)!=set(SCENARIOS[case]):problems.append("missing exact Kotlin scenario observations")
        for marker in ("PROBE_STARTED","PROBE_PAGE_READY","PROBE_FINISHED"):
            if sum(bool(re.search(re.escape(marker+" "+nonce)+r"(?:\s|$)",line)) for line in lines)!=1:problems.append("missing/duplicate "+marker)
        if not problems:
            if case=="kotlin-admission":problems.extend(admission_predicates(frames))
            else:
                problems.extend(normal_shutdown(frames, expected_engines=EXPECTED_ENGINE_COUNTS.get(case, 2 if case in HANDLE_SCENARIOS else 1)))
                try:
                    if case in FAULT_SCENARIOS:
                        napi_inventory(napi_binding,napi_identity)
                        if parse_napi(frames["napi-before-open"])["provider"] is not None:
                            raise ValueError("failed-close scenario was not a fresh unloaded provider")
                        result["napi_observation"]={"scope":"failed-close raw checkpoints and inspected ELF only; no normal-close oracle attribution",
                            "env_validity":"unobserved","candidate_hash_binding":napi_identity,
                            "raw":{k:frames[k] for k in ("napi-before-open","napi-open","napi-final")}}
                    else:
                        result["napi_observation"] = validate_napi(frames["napi-before-open"],frames["napi-open"],
                            frames["napi-final"],napi_binding,napi_identity)
                except (ValueError,KeyError,TypeError) as error:problems.append("NAPI observation: "+str(error))
                if case in VALUE_SCENARIOS:problems.extend(value_predicates(case,frames))
                elif case in WORK_SCENARIOS:problems.extend(work_predicates(case,frames))
                elif case in OPERATION_SCENARIOS:problems.extend(operation_predicates(case,frames))
                elif case in THREAD_SCENARIOS:problems.extend(thread_predicates(frames))
                elif case in WAITER_SCENARIOS:problems.extend(waiter_predicates(case,frames))
                elif case in HANDLE_SCENARIOS:problems.extend(handle_predicates(frames))
                elif case in FAULT_SCENARIOS:problems.extend(fault_predicates(case,frames))
                elif case in LISTENER_SCENARIOS or case == "kotlin-distinct-close-denied":problems.extend(listener_predicates(frames))
                elif case in MEMORY_SCENARIOS:problems.extend(memory_predicates(case,frames))
                elif case in STREAM_SCENARIOS:
                    try:
                        validate_stream(case, {k:v for k,v in frames.items() if isinstance(v,list)},
                            {k:v for k,v in frames.items() if isinstance(v,str)})
                    except ValueError as error:problems.append(str(error))
    result["status"]="failed" if problems or result["failures"] else "passed" if end else "incomplete"
    return result


def normal_shutdown(frames, *, expected_engines=1):
    from c07_kotlin_admission_observations import ZERO, PAIRS
    initial, final = frames["runtime-open"], frames["runtime-closed"]
    problems = []
    if any(frames["js-final"][i] != 0 for i in (5,7,8)):problems.append("Kotlin JS settling/timer/tick survives normal close")
    if frames["runtime-complete"] != [1]:problems.append("normal Kotlin scenario did not complete")
    if final[1] != 4 or final[72] != 3 or final[2] != 1 or final[7] != 1:
        problems.append("actual normal runtime physical ACK not consumed")
    if any(final[i] != 0 for i in ZERO):problems.append("Kotlin native/managed responsibility or error remains")
    if any(final[a] != final[b] for a,b in PAIRS):problems.append("Kotlin actual resource lifetime pairs differ")
    if final[12] != expected_engines or final[13] != expected_engines or any(final[i] <= 0 for i in (45,48,78,102,108)):
        problems.append("scenario lacks exact engine-generation work/ref/lifecycle/TSFN activity")
    if initial[39] != 1 or initial[7] != 1 or initial[1] != 1:
        problems.append("scenario was not observed on a fresh open Kotlin runtime")
    return problems
