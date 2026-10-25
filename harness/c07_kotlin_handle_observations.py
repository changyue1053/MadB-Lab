"""Exact two-engine typed-admission scenario; fresh Runtime remains one epoch."""
SCENARIOS={'kotlin-generation-handles':{
 'kn-handles-first-retired':'native','kn-handles-second-open':'native',
 'kn-handles-work-held':'control','kn-handles-before':'native','kn-handles-after':'native',
 'kn-handles-negative-cases':'vector','kn-handles-recovered':'vector'}}
EXPECTED_ENGINE_COUNT=2

def predicates(frames):
    problems=[]
    def need(ok,message):
        if not ok:problems.append(message)
    try:
        for label in ('kn-handles-first-retired','kn-handles-second-open','kn-handles-before','kn-handles-after'):
            f=frames[label]
            need(type(f) is list and len(f)==110 and f[0]==70501 and all(type(x) is int and 0<=x<2**53 for x in f),label+':110')
        if problems:return problems
        a,b=frames['kn-handles-first-retired'],frames['kn-handles-second-open']
        need([a[i] for i in (12,13,36,39)]==[1,1,1,0], 'request-only first owner not retired')
        need([b[i] for i in (12,13,36,39)]==[2,1,2,1], 'not exact second engine')
        raw=frames['kn-handles-work-held'].split(',')
        need(len(raw)==31 and raw[0]=='1' and raw[3]=='1' and raw[4]=='2' and raw[5]!='0','new actual native work not held')
        before,after=frames['kn-handles-before'],frames['kn-handles-after']
        need([before[i] for i in (24,25,26,36,39)]==[1,1,0,2,1], 'typed probes lack live operation/subscription')
        for i in (9,10,11,14,15,24,25,26,27,28,29,30,31,36,39):
            need(before[i]==after[i], 'native handle admission changed business ownership: '+str(i))
        need(frames['kn-handles-negative-cases']==[1,2,3,4,5], 'all typed native malformed cases required')
        need(frames['kn-handles-recovered']==[42,52,71,15], 'old/new actual results or fifteen rejections missing')
    except (KeyError,IndexError,TypeError,AttributeError):problems.append('missing/malformed handle observations')
    return problems
