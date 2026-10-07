_CLI_DESCRIPTION = """Experimental count-space repair, without using agent outputs."""
import json, functools, math, time, sys, argparse
from pathlib import Path
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import lil_matrix
parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
parser.add_argument('--work-dir', required=True)
args = parser.parse_args()
r = Path(args.work_dir).resolve()
d = json.loads((r/'instance.json').read_text(encoding='utf-8'))
exp = json.loads((r/'expert.json').read_text(encoding='utf-8'))
pt=d['product_time']; pm=d['production_order_matrix']; tm=d['transformation_matrix']; N=d['machine_num']; totals=[sum(x[p] for x in d['demand']) for p in range(5)]
def event(a,b):return int((a==1 and b in (1,2,3)) or (a in (2,3) and b==1))
def step(pos,prev,p):
 if pos<10 and pm[p][pos] and (prev<0 or tm[prev][p]):return pos+1,p,0,event(prev,p)
 if pos<10 and pm[5][pos] and pm[p][0] and tm[5][p] and (prev<0 or tm[prev][5]):return 1,p,1,0
 return None
@functools.lru_cache(None)
def dp(rem,pos,prev,hleft):
 if not any(rem):return (0,()) if hleft==0 else None
 if hleft<0:return None
 best=None
 for p in range(5):
  if rem[p]==0:continue
  tr=step(pos,prev,p)
  if tr is None:continue
  np_,nprev,h,e=tr
  if h>hleft:continue
  rr=list(rem);rr[p]-=1
  res=dp(tuple(rr),np_,nprev,hleft-h)
  if res is None:continue
  cand=(e+res[0],(p,)+res[1])
  if best is None or cand[0]<best[0]:best=cand
 return best

def schedule(ct,m):
 best=None;s=d['machine_state'][m];app=s!=0 and d['yesterday_product'][m]!=1
 for a in range(5):
  if ct[a]==0:continue
  t0=step(s,-1,a)
  if t0 is None:continue
  rem=list(ct);rem[a]-=1
  for b in range(5):
   if rem[b]==0:continue
   t1=step(t0[0],a,b)
   if t1 is None:continue
   rem[b]-=1;res=dp(tuple(rem),t1[0],b,1-t0[2]-t1[2]);rem[b]+=1
   if res is None:continue
   v1=t0[3]+t1[3]+res[0];v2=int(app and not t0[2] and a!=1)
   r1=int(a not in (0,1,2))+int(b not in (0,1,2));r2=int(a not in (0,1,2) or b not in (0,1,2) or a==b);r3=int(a!=1 and b!=1)
   pref=v1/7+6*v2+.5*r1+r2+r3
   cand=(pref,(a,b)+res[1],v1,v2,r1,r2,r3)
   if best is None or cand[0]<best[0]:best=cand
 return best

def run(target):
 pats=[];count=0
 lower=sum(totals[j]*pt[j] for j in range(5))+N*pt[5]-(N-1)*target
 for m,s in enumerate(d['machine_state']):
  these=[]
  orig=[sum(z['product']==d['product_names'][p] for z in exp['machines'][m]['rounds']) for p in range(5)]
  for a in range(13):
   for b in range(13-a):
    for c in range(min(7,13-a-b)):
     for dd in range(min(7,13-a-b-c)):
      ad=a+b+c+dd
      if not 7-s<=ad<=12-s:continue
      for e in range(7 if ad==12-s else 4):
       ct=(a,b,c,dd,e);w=sum(ct[p]*pt[p] for p in range(5))+30
       if not lower<=w<=target:continue
       val=schedule(ct,m)
       if val is None:continue
       dist=sum(abs(ct[j]-orig[j]) for j in range(5))
       these.append(dict(m=m,counts=ct,work=w,seq=val[1],v1=val[2],v2=val[3],r1=val[4],r2=val[5],r3=val[6],dist=dist))
  pats+=these;print('target',target,'machine',m+1,'patterns',len(these),'cache',dp.cache_info(),flush=True)
 n=len(pats);A=lil_matrix((N+5+3,n+1),dtype=float);lo=np.zeros(N+8);hi=np.zeros(N+8)
 lo[:N]=hi[:N]=1;lo[N:N+5]=hi[N:N+5]=totals;lo[N+5:]=-np.inf
 costs=np.zeros(n+1);costs[n]=1
 for j,p in enumerate(pats):
  A[p['m'],j]=1
  for k in range(5):A[N+k,j]=p['counts'][k]
  A[N+5,j]=p['v1']/7;A[N+6,j]=p['v2']*6;A[N+7,j]=p['r1']*.5+p['r2']+p['r3'];costs[j]=.0001*p['dist']
 for row in range(N+5,N+8):A[row,n]=-1
 bounds=Bounds(np.zeros(n+1),np.r_[np.ones(n),30]);integrality=np.r_[np.ones(n,dtype=int),0]
 res=milp(costs,integrality=integrality,bounds=bounds,constraints=LinearConstraint(A.tocsc(),lo,hi),options={'time_limit':30,'mip_rel_gap':0.0})
 print('MILP target',target,res.message,'fun',res.fun,flush=True)
 out={'target':target,'status':int(res.status),'message':res.message,'pattern_count':n,'seed_uses':'expert only; no agent output','minimum_penalty_plus_count_distance':None if res.fun is None else float(res.fun)}
 if res.x is not None:
  selected=sorted([p for j,p in enumerate(pats) if res.x[j]>.5],key=lambda p:p['m'])
  out['selected_patterns']=selected
  text=(r/'expert_search_input.txt').read_text().splitlines();base=text[:1+3+len(d['demand'])+6+6]
  assert len(base)==21
  output=r/f'count_seed_{target}.txt'
  output.write_text('\n'.join(base+[str(len(p['seq']))+' '+' '.join(map(str,p['seq'])) for p in selected])+'\n')
 (r/f'count_repair_{target}.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
 return out
initial_ad_capacity = sum(6 - x for x in d['machine_state'])
minimum_changes = max(0, math.ceil((sum(totals[:4]) - initial_ad_capacity) / 6))
assert minimum_changes == N
minimum_work = sum(totals[j]*pt[j] for j in range(5)) + minimum_changes*pt[5]
lower_bound = math.ceil(minimum_work/N)
for target in (lower_bound, lower_bound+1):
    run(target)
