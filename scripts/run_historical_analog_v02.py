#!/usr/bin/env python3
"""Run frozen Historical Analog v0.2 specification.

Reads configs/historical_analog_v02_preregister.json. Uses official TWSE TAIEX and
TWSE-only breadth. Optional macro/valuation blocks are included only if their
pre-registered >=80% coverage gate passes. Results remain SHADOW / weight 0.
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT=Path('.')
CFG=ROOT/'configs/historical_analog_v02_preregister.json'
DATA=ROOT/'output/twse_official_breadth_taiex'
OUT=ROOT/'output/historical_analog_v02'
MACRO=ROOT/'output/macro_asof_history.csv'
VALUATION=ROOT/'output/valuation_asof_history.csv'


def f(x):
    if x in (None,''): return None
    try: return float(str(x).replace(',',''))
    except: return None


def load_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as fh:
        return list(csv.DictReader(fh))


def mean(xs):
    xs=[x for x in xs if x is not None and math.isfinite(x)]
    return statistics.mean(xs) if xs else None


def pstdev(xs):
    xs=[x for x in xs if x is not None and math.isfinite(x)]
    return statistics.pstdev(xs) if len(xs)>=2 else None


def resample_path(vals,n=20):
    if len(vals)<5: return None
    out=[]
    for i in range(n):
        p=i*(len(vals)-1)/(n-1); lo=int(math.floor(p)); hi=int(math.ceil(p))
        if lo==hi: out.append(vals[lo])
        else:
            a=p-lo; out.append(vals[lo]*(1-a)+vals[hi]*a)
    mu=mean(out); sd=pstdev(out)
    if sd is None or sd<1e-12: return [0.0]*n
    return [(x-mu)/sd for x in out]


def max_dd(closes):
    peak=None; dd=0.0
    for x in closes:
        peak=x if peak is None else max(peak,x)
        if peak and peak>0: dd=min(dd,x/peak-1)
    return dd


def read_optional(path, fields):
    if not path.exists(): return {},0.0
    rows=load_csv(path); mp={}
    for r in rows:
        ds=r.get('date')
        if not ds: continue
        mp[ds]={k:f(r.get(k)) for k in fields}
    return mp,1.0


def zstd(values):
    xs=[x for x in values if x is not None and math.isfinite(x)]
    if len(xs)<2: return [0.0 if x is not None else None for x in values]
    mu=statistics.mean(xs); sd=statistics.pstdev(xs)
    if sd<1e-12: return [0.0 if x is not None else None for x in values]
    return [((x-mu)/sd) if x is not None and math.isfinite(x) else None for x in values]


def load_market():
    taiex=load_csv(DATA/'twse_official_taiex_2004_2026.csv')
    breadth=load_csv(DATA/'twse_official_breadth_2004_2026.csv')
    t={r['date']:f(r['close']) for r in taiex if f(r.get('close')) is not None}
    b={r['date']:{
        'advance_share':f(r.get('advance_share')),
        'ad_ratio':f(r.get('advance_decline_ratio')),
        'limit_up':f(r.get('limit_up')) or 0.0,
        'limit_down':f(r.get('limit_down')) or 0.0,
        'breadth_n':f(r.get('breadth_n')),
    } for r in breadth}
    dates=sorted(set(t)&set(b))
    years=defaultdict(list); prev=None
    for ds in dates:
        cl=t[ds]; ret=cl/prev-1 if prev else None; prev=cl
        r={'date':ds,'close':cl,'ret':ret,**b[ds]}
        years[int(ds[:4])].append(r)
    return years


def optional_block_maps():
    macro_fields=['US10Y_20d_change_bp','Brent_20d_return','SOX_20d_return','TSM_ADR_20d_return']
    val_fields=['TAIEX_forward_PE_percentile_asof','TAIEX_forward_EPS_revision_3m_asof']
    mm,_=read_optional(MACRO,macro_fields); vm,_=read_optional(VALUATION,val_fields)
    return mm,vm,macro_fields,val_fields


def feat(rows,idx,mm,vm):
    seg=rows[:idx+1]
    closes=[r['close'] for r in seg]
    if len(closes)<61:return None
    rets=[r['ret'] for r in seg if r['ret'] is not None]
    first=closes[0]; cum=[x/first-1 for x in closes]
    def avg(field,n):return mean([r.get(field) for r in seg[-n:]])
    adv20=avg('advance_share',20); adv60=avg('advance_share',60)
    ad20=avg('ad_ratio',20); ad60=avg('ad_ratio',60)
    thrust=mean([1.0 if (r.get('advance_share') or 0)>=0.65 else 0.0 for r in seg[-20:]])
    lim=[]
    for r in seg[-20:]:
        den=r.get('breadth_n') or 0
        if den>0: lim.append(((r.get('limit_up') or 0)-(r.get('limit_down') or 0))/den)
    ds=rows[idx]['date']
    macro=mm.get(ds,{}); valuation=vm.get(ds,{})
    return {
      'path':resample_path(cum,20),'ytd_return':cum[-1],
      'tr20':closes[-1]/closes[-21]-1,'tr60':closes[-1]/closes[-61]-1,
      'vol20':(pstdev(rets[-20:])*math.sqrt(252) if pstdev(rets[-20:]) is not None else None),
      'vol60':(pstdev(rets[-60:])*math.sqrt(252) if pstdev(rets[-60:]) is not None else None),
      'mdd':max_dd(closes),'adv20':adv20,'adv60':adv60,'ad20':ad20,'ad60':ad60,
      'breadth_thrust20':thrust,'limit_net20':mean(lim),
      'macro':macro,'valuation':valuation
    }


def nearest_cut(rows,month,day):
    target=f"{rows[0]['date'][:4]}-{month:02d}-{day:02d}"; idx=None
    for i,r in enumerate(rows):
        if r['date']<=target:idx=i
        else:break
    return idx


def forward(rows,idx,h):
    j=idx+h
    return None if j>=len(rows) else rows[j]['close']/rows[idx]['close']-1


def coverage(features,block,fields):
    if not features:return 0
    ok=0
    for x in features:
        d=x.get(block,{})
        if all(d.get(k) is not None for k in fields):ok+=1
    return ok/len(features)


def distances(cur,cands,include_macro,include_val,macro_fields,val_fields):
    scalar=['ytd_return','tr20','tr60','vol20','vol60','mdd','adv20','adv60','ad20','ad60','breadth_thrust20','limit_net20']
    blocks=[('market',scalar)]
    if include_macro:blocks.append(('macro',macro_fields))
    if include_val:blocks.append(('valuation',val_fields))
    allf=[cur]+cands; z={}
    for block,names in blocks:
        for name in names:
            vals=[]
            for x in allf:
                vals.append(x.get(name) if block=='market' else x.get(block,{}).get(name))
            z[(block,name)]=zstd(vals)
    out=[]
    for ci,c in enumerate(cands,start=1):
        bdist=[]
        if cur.get('path') and c.get('path'):
            bdist.append(math.sqrt(mean([(a-b)**2 for a,b in zip(cur['path'],c['path'])])))
        for block,names in blocks:
            dif=[]
            for name in names:
                zz=z[(block,name)]; a=zz[0]; b=zz[ci]
                if a is not None and b is not None:dif.append((a-b)**2)
            if dif:bdist.append(math.sqrt(mean(dif)))
        out.append(mean(bdist) if bdist else 999)
    return out


def write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:return
    with path.open('w',encoding='utf-8-sig',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)


def bootstrap_edge(rows,h,field_a,field_b,B=5000,seed=260906):
    rr=[r for r in rows if r['horizon']==h and r['actual_return'] is not None]
    dif=[r[field_a]-r[field_b] for r in rr]
    if len(dif)<10:return None
    rng=random.Random(seed+h); sims=[];n=len(dif)
    for _ in range(B):sims.append(sum(dif[rng.randrange(n)] for __ in range(n))/n)
    sims.sort()
    return {'horizon':h,'n':n,'edge_mean':mean(dif),'ci_low':sims[int(.025*B)],'ci_high':sims[int(.975*B)-1]}


def main():
    cfg=json.loads(CFG.read_text(encoding='utf-8'))
    years=load_market(); mm,vm,mfields,vfields=optional_block_maps()
    usable={y:r for y,r in years.items() if y>=2005 and len(r)>=150}
    # Precompute all possible features to evaluate optional block coverage without future imputation.
    allfeat=[]
    for y,rows in usable.items():
        for m in range(2,13):
            inds=[i for i,r in enumerate(rows) if int(r['date'][5:7])==m]
            if inds:
                ft=feat(rows,max(inds),mm,vm)
                if ft:allfeat.append(ft)
    mcov=coverage(allfeat,'macro',mfields); vcov=coverage(allfeat,'valuation',vfields)
    include_macro=mcov>=.80; include_val=vcov>=.80
    wf=[];current=[]
    for y in sorted(usable):
        rows=usable[y]; snaps=[]
        for m in range(2,13):
            inds=[i for i,r in enumerate(rows) if int(r['date'][5:7])==m]
            if inds:snaps.append(max(inds))
        if y==2026 and (len(rows)-1) not in snaps:snaps.append(len(rows)-1)
        for idx in sorted(set(snaps)):
            cf=feat(rows,idx,mm,vm)
            if not cf:continue
            ds=rows[idx]['date'];mo=int(ds[5:7]);day=int(ds[8:10]);cand=[]
            for py in sorted(k for k in usable if k<y):
                pi=nearest_cut(usable[py],mo,day)
                if pi is None or pi<60:continue
                pf=feat(usable[py],pi,mm,vm)
                if pf:cand.append((py,pi,pf))
            if len(cand)<3:continue
            dd=distances(cf,[x[2] for x in cand],include_macro,include_val,mfields,vfields)
            top=sorted([(dd[i],cand[i]) for i in range(len(cand))],key=lambda x:x[0])[:5]
            for h in (20,60):
                vals=[];weights=[];pos=[];yrs=[]
                for dist,(py,pi,pf) in top:
                    fr=forward(usable[py],pi,h)
                    if fr is None:continue
                    w=1/max(.05,dist);vals.append(fr);weights.append(w);pos.append(1 if fr>0 else 0);yrs.append(py)
                if not vals:continue
                sw=sum(weights); pred=sum(v*w for v,w in zip(vals,weights))/sw; prob=sum(p*w for p,w in zip(pos,weights))/sw
                basevals=[forward(usable[py],pi,h) for py,pi,pf in cand];basevals=[v for v in basevals if v is not None]
                base=mean(basevals);basep=mean([1 if v>0 else 0 for v in basevals])
                past=max(0,idx-h);mom=rows[idx]['close']/rows[past]['close']-1
                actual=forward(rows,idx,h)
                wf.append({
                  'snapshot_date':ds,'year':y,'horizon':h,'top_years':'|'.join(map(str,yrs)),
                  'analog_pred_return':pred,'analog_prob_up':prob,'seasonal_pred_return':base,'seasonal_prob_up':basep,'momentum_pred_return':mom,
                  'actual_return':actual,
                  'analog_correct':int((pred>0)==(actual>0)) if actual is not None else None,
                  'seasonal_correct':int((base>0)==(actual>0)) if actual is not None else None,
                  'momentum_correct':int((mom>0)==(actual>0)) if actual is not None else None,
                  'analog_ae':abs(pred-actual) if actual is not None else None,
                  'seasonal_ae':abs(base-actual) if actual is not None else None,
                  'zero_ae':abs(actual) if actual is not None else None,
                  'analog_brier':(prob-(1 if actual>0 else 0))**2 if actual is not None else None,
                  'seasonal_brier':(basep-(1 if actual>0 else 0))**2 if actual is not None else None,
                  'macro_block':include_macro,'valuation_block':include_val
                })
            if y==2026 and idx==len(rows)-1:
                for rank,(dist,(py,pi,pf)) in enumerate(top,1):
                    current.append({'asof':ds,'rank':rank,'analog_year':py,'distance':dist,'cut_date':usable[py][pi]['date'],'forward_20d_return':forward(usable[py],pi,20),'forward_60d_return':forward(usable[py],pi,60)})
    summary=[]
    for h in (20,60):
        rr=[r for r in wf if r['horizon']==h and r['actual_return'] is not None]
        def av(k):return mean([r[k] for r in rr])
        summary.append({
          'horizon':h,'n':len(rr),'analog_direction_accuracy':av('analog_correct'),'seasonal_direction_accuracy':av('seasonal_correct'),'momentum_direction_accuracy':av('momentum_correct'),
          'analog_mae':av('analog_ae'),'seasonal_mae':av('seasonal_ae'),'zero_mae':av('zero_ae'),'analog_brier':av('analog_brier'),'seasonal_brier':av('seasonal_brier')
        })
    boot_season=[bootstrap_edge(wf,h,'analog_correct','seasonal_correct') for h in (20,60)]
    boot_mom=[bootstrap_edge(wf,h,'analog_correct','momentum_correct') for h in (20,60)]
    OUT.mkdir(parents=True,exist_ok=True);write(OUT/'historical_analog_v02_wf.csv',wf);write(OUT/'historical_analog_v02_current.csv',current);write(OUT/'historical_analog_v02_summary.csv',summary)
    man={'model_id':cfg['model_id'],'status':'SHADOW_RESEARCH_ONLY','spec_frozen':True,'macro_coverage':mcov,'valuation_coverage':vcov,'macro_included':include_macro,'valuation_included':include_val,'result_label':('v0.2-full' if include_macro and include_val else 'v0.2-market-only'),'summary':summary,'bootstrap_vs_seasonal':boot_season,'bootstrap_vs_momentum':boot_mom,'formal_weight':0,'p4':'LOCKED/no interaction'}
    (OUT/'manifest.json').write_text(json.dumps(man,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(man,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
