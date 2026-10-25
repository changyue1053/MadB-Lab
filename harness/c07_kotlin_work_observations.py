"""Independent work/capacity expectations; raw110 and exact CSV31 are distinct."""
NAMES = ('kotlin-terminal-cancel','kotlin-terminal-success','kotlin-terminal-domain',
 'kotlin-operations-capacity','kotlin-subscriptions-capacity','kotlin-shared-waiters',
 'kotlin-settling-reentry','kotlin-dropped-promise','kotlin-claim-rollback','kotlin-bytes-scratch','kotlin-after-guard')
SCENARIOS={
 'kotlin-terminal-cancel':{'terminal-before':'control','terminal-after':'control','terminal-close-pending':'native','terminal-outcome':'vector'},
 'kotlin-terminal-success':{'terminal-before':'control','terminal-after':'control','terminal-close-pending':'native','terminal-outcome':'vector'},
 'kotlin-terminal-domain':{'terminal-before':'control','terminal-after':'control','terminal-close-pending':'native','terminal-outcome':'vector'},
 'kotlin-operations-capacity':{'operations-full':'native','operations-denied':'native','operations-recovered':'vector'},
 'kotlin-subscriptions-capacity':{'subscriptions-full':'native','subscriptions-denied':'native','subscriptions-recovered':'vector'},
 'kotlin-shared-waiters':{'waiters-full':'native','parent-close-full':'native'},
 'kotlin-settling-reentry':{'waiters-full':'native','settling-actual':'settling'},
 'kotlin-dropped-promise':{'dropped-owned':'native','dropped-consumed':'native'},
 'kotlin-claim-rollback':{'claim-rollback-control':'control','claim-rollback-native':'native','claim-rollback-result':'vector'},
 'kotlin-bytes-scratch':{'bytes-scratch-full':'native','bytes-scratch-denied':'native'},
 'kotlin-after-guard':{'after-guard-control':'control','after-guard-native':'native'},
}
GATED=set(SCENARIOS)-{'kotlin-subscriptions-capacity'}
for name in GATED:SCENARIOS[name].update({'work-held':'native','work-held-control':'control'})


def predicates(case, frames):
    problems=[]
    def need(ok, message):
        if not ok:problems.append(message)
    def eq(label,values):
        need(all(frames[label][i]==value for i,value in values.items()),label+': independent values differ')
    def control(label):
        from c07_kotlin_observations import parse_control_csv
        return parse_control_csv(frames[label])
    try:
        if case in GATED:
            phase=2 if case in ('kotlin-terminal-success','kotlin-terminal-domain','kotlin-after-guard') else 1
            held=frames['work-held'];gate=control('work-held-control')
            need(gate[3]==phase and held[12]==1 and held[13]==0 and held[39]==1 and held[24]>=1,
                 'native worker/operation was not actually held at the declared phase')
            need(gate[4]!='0' and gate[5]!='0', 'missing actual generation/operation identity')
        if case.startswith('kotlin-terminal-'):
            mode=case.removeprefix('kotlin-terminal-');winner={'cancel':5,'success':0,'domain':8}[mode]
            need(control('terminal-before')[6]==(-1 if mode=='cancel' else winner), 'terminal phase witness differs')
            if mode!='cancel':need(control('terminal-after')[6]==winner, 'cancel rewrote a committed terminal outcome')
            eq('terminal-close-pending',{13:0});need(frames['terminal-outcome']==[winner], 'actual result winner differs')
        elif case=='kotlin-operations-capacity':
            eq('operations-full',{24:8});eq('operations-denied',{24:8})
            need(frames['operations-full'][9]==frames['operations-denied'][9], 'rejected ninth operation allocated a model')
            need(frames['operations-recovered']==[42], 'operation capacity did not recover')
        elif case=='kotlin-subscriptions-capacity':
            for label in ('subscriptions-full','subscriptions-denied'):eq(label,{25:8,28:0,29:0})
            need(frames['subscriptions-recovered']==[1], 'shared subscription budget did not recover')
        elif case in ('kotlin-shared-waiters','kotlin-settling-reentry'):
            eq('waiters-full',{26:32})
            if case=='kotlin-shared-waiters':eq('parent-close-full',{26:32,13:0})
            else:
                f=frames['settling-actual'];need(len(f)==9 and f[1]==1 and f[5]==1 and f[6]==32,
                    'actual settler return did not retain the shared charged waiter')
        elif case=='kotlin-dropped-promise':
            eq('dropped-owned',{26:1});eq('dropped-consumed',{26:0})
        elif case=='kotlin-claim-rollback':
            c=control('claim-rollback-control');need(c[25]==1 and c[30]==1,'actual claim precommit rollback missing')
            eq('claim-rollback-native',{26:0});need(frames['claim-rollback-result']==[42],'result retry failed')
        elif case=='kotlin-bytes-scratch':
            for label in ('bytes-scratch-full','bytes-scratch-denied'):
                eq(label,{24:4,27:4096});f=frames[label];need(f[33]>0 and f[33]==f[34],'independent scratch lease not returned')
        elif case=='kotlin-after-guard':
            c=control('after-guard-control');need(c[27]==1 and c[28]>0 and c[28]==c[29], 'actual consume guard did not dispose exactly once')
            eq('after-guard-native',{26:0})
    except (KeyError,IndexError,ValueError,TypeError) as error:problems.append('missing/malformed work observation: '+str(error))
    return problems
