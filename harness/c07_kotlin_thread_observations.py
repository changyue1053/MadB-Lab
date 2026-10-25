"""Actual simultaneous owner/business/cleanup witness, not historical thread IDs."""
import re
UNKNOWN='18446744073709551615'
FIELDS='Format Epoch Generation OwnerEntryActive BusinessBodyActive BusinessExitHeld CleanupJoinCallInFlight OwnerBusinessDistinct OwnerCleanupDistinct BusinessCleanupDistinct ExitArmCount ExitHoldEntered ExitReleaseCount BodyExited TlsMarkerAttached TlsMarkerDestructed JoinCalls JoinReturned JoinSucceeded ExecutorDestroyed ProbeErrors'.split()
SCENARIOS={'kotlin-live-threads':{
 **{'kn-thread-'+n:'thread' for n in ('before','armed','live-first','live-heartbeat','released','final')},
 'kn-thread-work':'vector','kn-thread-heartbeat':'vector','kn-thread-close-pending':'native','kn-thread-closed-native':'native','kn-thread-close-outcome':'vector'}}
def parse(raw):
 if type(raw) is not str or len(raw.encode('utf-8'))>440:raise ValueError('thread21 raw bounded string required')
 f=raw.split(',')
 if len(f)!=21 or f[0]!='70604':raise ValueError('thread21 format/length differs')
 for token in f:
  if not re.fullmatch(r'0|[1-9][0-9]*',token) or len(token)>20 or len(token)==20 and token>UNKNOWN:raise ValueError('thread21 canonical uint64 required')
 for i in (3,4,5,6,19):
  if f[i] not in ('0','1'):raise ValueError('thread21 boolean domain')
 for i in (7,8,9):
  if f[i] not in ('0','1',UNKNOWN):raise ValueError('thread21 live comparison domain')
 return f

def predicates(frames):
 errors=[]
 def need(ok,why):
  if not ok:errors.append(why)
 try:
  fs={n:parse(frames['kn-thread-'+n]) for n in ('before','armed','live-first','live-heartbeat','released','final')}
  if {k for k in frames if k.startswith('kn-thread-')}!=set(SCENARIOS['kotlin-live-threads']):return ['thread21 labels differ']
  before=fs['before'];final=fs['final'];identity=before[1:3]
  need(all(x!='0' for x in identity),'real epoch and executor generation absent')
  need(all(f[1:3]==identity for f in fs.values()),'thread snapshots cross epoch/generation')
  need(all(f[20]=='0' for f in fs.values()),'actual native thread probe error')
  need(all(f[3]=='1' for f in fs.values()),'each successful snapshot must execute on the current legal owner')
  need(before[4]=='1' and all(before[i]=='0' for i in (5,6,10,11,12,13,15,16,17,18,19)),'before must be live existing executor before stop/arm')
  need(fs['armed'][10]=='1' and fs['armed'][12]=='0','arm did not precede release')
  for name in ('live-first','live-heartbeat'):
   f=fs[name]
   need(f[3:10]==['1']*7,'actual simultaneous live threads/pthread_equal witness missing '+name)
   need(all(f[i]=='1' for i in (10,11,14,16)) and all(f[i]=='0' for i in (12,13,15,17,18,19)), 'join returned/body or TLS exited while exit held '+name)
  h=frames['kn-thread-heartbeat'];need(type(h) is list and len(h)==3 and type(h[0]) is int and h[0]>=2 and h[1:]==[0,0],'owner event loop did not heartbeat while original close remained pending')
  need(fs['released'][12]=='1','actual explicit release not observed')
  need(final[4:7]==['0']*3 and final[7:10]==[UNKNOWN]*3,'final live intervals remain or invalid historical comparisons reported')
  need(all(final[i]=='1' for i in range(10,20)),'real exit/TLS/join/destroy events did not complete exactly once')
  for a,b in zip(fs.values(),list(fs.values())[1:]):
   need(all(int(b[i])>=int(a[i]) for i in range(10,21)),'thread cumulative event regressed')
  pending=frames['kn-thread-close-pending'];closed=frames['kn-thread-closed-native']
  need(type(pending) is list and len(pending)==110 and pending[0]==70501 and pending[12]==1 and pending[13]==0 and pending[2]==0,'no original runtime pending physical-join checkpoint')
  need(type(closed) is list and len(closed)==110 and closed[0]==70501 and [closed[i] for i in (1,2,7,12,13,72)]==[4,1,1,1,1,3],'final original Runtime physical ACK missing')
  need(frames['kn-thread-work']==[42] and frames['kn-thread-close-outcome']==[1,0],'real compute/original close outcome differs')
 except (KeyError,IndexError,TypeError,ValueError) as error:errors.append('missing/malformed thread witness: '+str(error))
 return errors
