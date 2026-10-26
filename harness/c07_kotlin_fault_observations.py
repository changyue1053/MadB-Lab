"""Failed Runtime.close must retain BridgeFailure and still finish native cleanup.

Outer transport binds fresh nonce/PID/identity. This is not the fresh normal-close
NAPI oracle's scope; retain its raw before/open/final CSV separately.
"""
SCENARIOS={name:{'kn-fault-first-control':'control','kn-fault-first-completed':'native',
 'kn-fault-close-pending-control':'control','kn-fault-close-proof':'vector','kn-fault-held-control':'control','kn-fault-held-native':'native',
 'kn-fault-settlements':'vector','kn-fault-residual-native':'native',
 'kn-fault-residual-control':'control','kn-fault-settler':'settling',
 'kn-fault-close-pending':'native','kn-fault-close-outcome':'vector',
 'kn-fault-closed-native':'native','kn-fault-final-settler':'settling',
 'kn-fault-late-settlements':'vector',**({'kn-fault-after-resolver':'settling'} if name.endswith('accepted') else {})}
 for name in ('kotlin-fault-before-guard','kotlin-fault-after-accepted')}

def predicates(case,frames):
    from c07_kotlin_observations import parse_control_csv
    from c07_kotlin_admission_observations import ZERO, PAIRS
    errors=[]
    def need(ok,message):
        if not ok:errors.append(message)
    try:
        before=case=='kotlin-fault-before-guard'
        first_control=parse_control_csv(frames['kn-fault-first-control'])
        held=parse_control_csv(frames['kn-fault-held-control'])
        need(first_control[3]==2 and first_control[6]==0 and first_control[4]!='0' and first_control[5]!='0','first terminal identity missing')
        need(held[4]==first_control[4] and held[5]!=first_control[5], 'second held Work identity not distinct from first result')
        need(held[3]==2 and held[6]==0 and held[4]!='0' and held[5]!='0','actual success-terminal native hold absent')
        for label in ('kn-fault-first-completed','kn-fault-held-native','kn-fault-residual-native','kn-fault-close-pending','kn-fault-closed-native'):
            f=frames[label]
            need(type(f) is list and len(f)==110 and f[0]==70501 and all(type(x) is int and 0<=x<2**53 for x in f),label+': native110')
        for label in ('kn-fault-settler','kn-fault-final-settler'):
            f=frames[label];need(type(f) is list and len(f)==9 and all(type(x) is int and 0<=x<2**53 for x in f),label+': JS9')
        if errors:return errors
        first=frames['kn-fault-first-completed']; owned=frames['kn-fault-held-native']
        need([first[i] for i in (9,10,11,14,15,24,26)]==[1,0,1,1,1,1,0], 'first Work must complete with one unclaimed result')
        need([owned[i] for i in (9,10,11,14,15,24,26)]==[2,0,2,2,1,2,0], 'second independent Work must be held beside available first result')
        residual=frames['kn-fault-residual-native']; c=parse_control_csv(frames['kn-fault-residual-control'])
        need(residual[12]==1 and residual[13]==0 and residual[39]==1, 'fault must preserve live held worker before cleanup')
        need(residual[26]==int(before) and residual[11]==1+int(before) and residual[9]==2 and residual[10]==int(not before) and residual[14]==2 and residual[15]==1, 'beforeguard residual/afteraccepted disposal differs')
        need(c[26]==int(before) and c[28]==c[29], 'actual transfer boundary or guard pairing differs')
        if before:need(c[28]==0, 'beforeguard must not claim consuming guard')
        else:
            need(c[28]>0,'accepted result lacks actual guard disposal')
            settled=frames['kn-fault-after-resolver'];need(len(settled)==9 and settled[1:6]==[1,1,0,0,1], 'hook is not after accepted resolver and before guard detachment')
        need(frames['kn-fault-settlements']==([0,1,0] if before else [1,0,1]), 'fault result must settle once with exact outcome')
        js=frames['kn-fault-settler'];need(js[4]==int(not before) and js[5]==0,'afteraccepted exception count or JS settling residual')
        pending=frames['kn-fault-close-pending'];need(pending[12]==1 and pending[13]==0 and pending[14]==2 and pending[15]==1 and pending[2]==0 and pending[1]!=4,'close falsely ACKed while worker held')
        end=frames['kn-fault-closed-native'];need([end[i] for i in (1,2,7,12,13,72)]==[4,1,1,1,1,3], 'failed-close did not consume physical ACK')
        need([end[i] for i in (9,10,14,15)]==[2,2,2,2], 'two actual Work/model lifetimes must pair at rejection')
        need(frames['kn-fault-close-proof']==[0,1,1], 'handler evidence failed or original error identity lost')
        close_control=parse_control_csv(frames['kn-fault-close-pending-control'])
        need(close_control[4]==held[4] and close_control[5]==held[5] and close_control[3]==2, 'pending close must retain second held Work identity')
        need(all(end[i]==0 for i in ZERO),'failed-close leaves native/managed owner or error')
        need(all(end[a]==end[b] for a,b in PAIRS),'failed-close actual resource pairs differ')
        need(all(end[i]>0 for i in (9,45,48,78,102,108)),'failed-close zero-equals-zero is not cleanup')
        need(frames['kn-fault-close-outcome']==[0,1], 'BridgeFailure converted to success or duplicated')
        final=frames['kn-fault-final-settler'];need(all(final[i]==0 for i in (5,7,8)), 'timer/tick/settling survives failed cleanup')
        need(frames['kn-fault-late-settlements']==([0,1,0,1] if before else [1,0,0,1]), 'late duplicate settlement')
    except (KeyError,IndexError,TypeError,ValueError):errors.append('missing/malformed fault observations')
    return errors
