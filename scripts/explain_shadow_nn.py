#!/usr/bin/env python3
"""Integrated Gradients receipts for the trained TCN+MLP shadow model.

Reads canonical PIT matrix and existing shadow weights. Writes explanation artifacts only.
No Production interaction and no model retraining/tuning.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from torch import nn

SEED=20260928
LOOKBACK=60
FEATURES=["ret1","ret5","vol20","volume_z20","mkt_ret1","mkt_ret5","mkt_vol20"]
MATRIX=Path("output/shadow_feature_store/pit_matrix.csv")
METRICS=Path("output/shadow_nn/fold_metrics.csv")
MODEL_DIR=Path("output/shadow_nn")
OUT=Path("output/shadow_explain")
STEPS=16

torch.manual_seed(SEED)
np.random.seed(SEED)

class ShadowNet(nn.Module):
    def __init__(self,nf):
        super().__init__()
        self.tcn=nn.Sequential(
            nn.Conv1d(nf,32,3,padding=2,dilation=1),nn.ReLU(),nn.Dropout(.1),
            nn.Conv1d(32,32,3,padding=4,dilation=2),nn.ReLU(),nn.Dropout(.1),
        )
        self.static=nn.Sequential(nn.Linear(nf,32),nn.ReLU())
        self.fusion=nn.Sequential(nn.Linear(64,64),nn.ReLU(),nn.Dropout(.1))
        self.dir=nn.Linear(64,3); self.ret=nn.Linear(64,1); self.quant=nn.Linear(64,3)
    def forward(self,x):
        z=self.tcn(x.transpose(1,2))[:,:,-1]
        s=self.static(x[:,-1,:])
        h=self.fusion(torch.cat([z,s],dim=1))
        return self.dir(h),self.ret(h).squeeze(1),self.quant(h),h

def make_sequences(g):
    x=g[FEATURES].to_numpy(float)
    dates=pd.to_datetime(g["date"]).to_numpy()
    seq=[];dd=[]
    for i in range(LOOKBACK-1,len(g)):
        w=x[i-LOOKBACK+1:i+1]
        if np.isnan(w).any(): continue
        seq.append(w);dd.append(dates[i])
    return np.asarray(seq),np.asarray(dd)

def integrated_gradients(model,x,baseline,target,steps=STEPS):
    x=x.detach()
    total=torch.zeros_like(x)
    for a in torch.linspace(1/steps,1,steps):
        xi=(baseline+a*(x-baseline)).clone().detach().requires_grad_(True)
        logits,_,_,_=model(xi)
        score=logits[0,target]
        grad=torch.autograd.grad(score,xi,retain_graph=False,create_graph=False)[0]
        total+=grad.detach()
    return (x-baseline)*(total/steps)

def main():
    if not MATRIX.exists() or not METRICS.exists():
        raise SystemExit("canonical feature matrix or neural fold metrics missing")
    df=pd.read_csv(MATRIX);df["date"]=pd.to_datetime(df["date"])
    fm=pd.read_csv(METRICS)
    rows=[];samples_total=0
    for _,r in fm.iterrows():
        sym=str(r["symbol"]); fold=int(r["fold"])
        gp=df[df["symbol"].astype(str)==sym].sort_values("date").dropna(subset=FEATURES)
        X,D=make_sequences(gp)
        tr=(D>=np.datetime64(r["train_start"]))&(D<=np.datetime64(r["train_end"]))
        te=(D>=np.datetime64(r["test_start"]))&(D<=np.datetime64(r["test_end"]))
        if not tr.any() or not te.any(): continue
        model_path=MODEL_DIR/f"{sym}_fold{fold}.pt"
        if not model_path.exists(): continue
        rec=torch.load(model_path,map_location="cpu",weights_only=False)
        mean=np.asarray(rec["scaler_mean"],float);scale=np.asarray(rec["scaler_scale"],float)
        Xs=(X-mean.reshape(1,1,-1))/scale.reshape(1,1,-1)
        Xtr=Xs[tr];Xte=Xs[te]
        base_vec=np.median(Xtr.reshape(-1,len(FEATURES)),axis=0).astype("float32")
        baseline=torch.tensor(np.tile(base_vec,(LOOKBACK,1))[None,:,:])
        model=ShadowNet(len(FEATURES));model.load_state_dict(rec["state_dict"]);model.eval()
        signed=[];absolute=[]
        for xx in Xte:
            xt=torch.tensor(xx[None,:,:].astype("float32"))
            with torch.no_grad():
                pred=int(torch.argmax(model(xt)[0],dim=1).item())
            ig=integrated_gradients(model,xt,baseline,pred)[0].numpy()
            contrib=ig.sum(axis=0)
            signed.append(contrib);absolute.append(np.abs(ig).sum(axis=0))
            samples_total+=1
        s=np.mean(np.asarray(signed),axis=0);a=np.mean(np.asarray(absolute),axis=0)
        ranks=(-a).argsort().argsort()+1
        for i,f in enumerate(FEATURES):
            rows.append({"symbol":sym,"fold":fold,"feature":f,"mean_signed_ig":float(s[i]),
                         "mean_abs_ig":float(a[i]),"rank_abs":int(ranks[i]),"test_samples":int(len(Xte)),
                         "baseline_rule":"train_only_median_scaled","target_rule":"predicted_direction_logit"})
    OUT.mkdir(parents=True,exist_ok=True)
    out=pd.DataFrame(rows)
    out.to_csv(OUT/"ig_fold_attribution.csv",index=False,encoding="utf-8-sig")
    summary={"status":"PASS_SHADOW_EXPLAINABILITY","method":"Integrated Gradients","steps":STEPS,
             "baseline":"train-only median in scaled feature space","features":FEATURES,
             "folds_explained":int(out[["symbol","fold"]].drop_duplicates().shape[0]) if len(out) else 0,
             "samples_explained":samples_total,"production":"NO_INTERACTION","causal_claim":False}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__": main()
