#!/usr/bin/env python3
"""R147 TCN+MLP neural shadow challenger.

Consumes the canonical PIT feature-store matrix only.
Purged walk-forward, train-only scaling, validation-frozen OOD thresholds.
Shadow only. Never writes Production weights/trades/cash.
"""
from __future__ import annotations
import hashlib, io, json, math
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error

SEED=20260928
LOOKBACK=60
TRAIN=504
VAL=126
PURGE=10
TEST=20
STEP=20
EPOCHS=35
BATCH=64
LR=1e-3
FEATURES=["ret1","ret5","vol20","volume_z20","mkt_ret1","mkt_ret5","mkt_vol20"]
IN_MATRIX=Path("output/shadow_feature_store/pit_matrix.csv")
OUT=Path("output/shadow_nn")

torch.manual_seed(SEED); np.random.seed(SEED)
try:
    torch.use_deterministic_algorithms(True)
except Exception:
    pass

def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def q333(x): return float(np.quantile(np.asarray(x,float),1/3))
def labels(ret,sigma,k):
    thr=k*sigma
    return np.where(ret>thr,2,np.where(ret<-thr,0,1))  # DOWN=0 SIDE=1 UP=2
def entropy(p):
    p=np.clip(p,1e-12,1)
    return -(p*np.log(p)).sum(axis=1)
def brier(y,p):
    oh=np.eye(3)[y]
    return float(np.mean(np.sum((p-oh)**2,axis=1)))
def pinball(pred,y,qs=(.2,.5,.8)):
    losses=[]
    for i,q in enumerate(qs):
        e=y-pred[:,i]
        losses.append(torch.maximum(q*e,(q-1)*e))
    return torch.stack(losses,dim=1).mean()

class ShadowNet(nn.Module):
    def __init__(self,nf):
        super().__init__()
        self.tcn=nn.Sequential(
            nn.Conv1d(nf,32,3,padding=2,dilation=1),nn.ReLU(),nn.Dropout(.1),
            nn.Conv1d(32,32,3,padding=4,dilation=2),nn.ReLU(),nn.Dropout(.1),
        )
        self.static=nn.Sequential(nn.Linear(nf,32),nn.ReLU())
        self.fusion=nn.Sequential(nn.Linear(64,64),nn.ReLU(),nn.Dropout(.1))
        self.dir=nn.Linear(64,3)
        self.ret=nn.Linear(64,1)
        self.quant=nn.Linear(64,3)
    def forward(self,x):
        z=self.tcn(x.transpose(1,2))[:,:,-1]
        s=self.static(x[:,-1,:])
        h=self.fusion(torch.cat([z,s],dim=1))
        return self.dir(h),self.ret(h).squeeze(1),self.quant(h),h

def make_sequences(g):
    X=g[FEATURES].to_numpy(float)
    ret=g["target_ret1"].to_numpy(float)
    sig=g["vol20"].to_numpy(float)
    dates=pd.to_datetime(g["date"]).to_numpy()
    seq=[]; rr=[]; ss=[]; dd=[]
    for i in range(LOOKBACK-1,len(g)):
        if np.isnan(X[i-LOOKBACK+1:i+1]).any() or np.isnan(ret[i]) or np.isnan(sig[i]): continue
        seq.append(X[i-LOOKBACK+1:i+1]); rr.append(ret[i]); ss.append(sig[i]); dd.append(dates[i])
    return np.asarray(seq),np.asarray(rr),np.asarray(ss),np.asarray(dd)

def train_fold(sym,fold_no,X,ret,sig,dates,start):
    a=start;b=a+TRAIN;c=b+VAL;d=c+PURGE;e=d+TEST
    Xtr,Xva,Xte=X[a:b],X[b:c],X[d:e]
    rtr,rva,rte=ret[a:b],ret[b:c],ret[d:e]
    str_,sva,ste=sig[a:b],sig[b:c],sig[d:e]
    k=q333(np.abs(rtr/str_))
    ytr,yva,yte=labels(rtr,str_,k),labels(rva,sva,k),labels(rte,ste,k)
    scaler=StandardScaler().fit(Xtr.reshape(-1,len(FEATURES)))
    def tx(x):
        shp=x.shape
        return scaler.transform(x.reshape(-1,shp[-1])).reshape(shp).astype("float32")
    Xtr,Xva,Xte=map(tx,(Xtr,Xva,Xte))
    trds=TensorDataset(torch.tensor(Xtr),torch.tensor(ytr).long(),torch.tensor(rtr).float())
    loader=DataLoader(trds,batch_size=BATCH,shuffle=False)
    model=ShadowNet(len(FEATURES))
    opt=torch.optim.Adam(model.parameters(),lr=LR,weight_decay=1e-4)
    ce=nn.CrossEntropyLoss(); mse=nn.MSELoss()
    best=None;best_ll=1e9;bad=0
    for ep in range(EPOCHS):
        model.train()
        for xb,yb,rb in loader:
            opt.zero_grad()
            lg,rh,qh,_=model(xb)
            loss=ce(lg,yb)+.35*mse(rh,rb)+.35*pinball(qh,rb)
            loss.backward();opt.step()
        model.eval()
        with torch.no_grad():
            lg,_,qh,h=model(torch.tensor(Xva))
            pv=torch.softmax(lg,1).numpy()
            ll=log_loss(yva,pv,labels=[0,1,2])
        if ll<best_ll-1e-5:
            best_ll=ll;bad=0
            best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        else:
            bad+=1
            if bad>=6:break
    model.load_state_dict(best);model.eval()
    with torch.no_grad():
        lgv,_,qv,hv=model(torch.tensor(Xva)); pv=torch.softmax(lgv,1).numpy(); hv=hv.numpy(); qv=qv.numpy()
        lgt,rt,qt,ht=model(torch.tensor(Xte)); pt=torch.softmax(lgt,1).numpy(); ht=ht.numpy(); rt=rt.numpy(); qt=qt.numpy()
    ent_thr=float(np.quantile(entropy(pv),.95))
    width_thr=float(np.quantile(qv[:,2]-qv[:,0],.95))
    mu=hv.mean(0);cov=np.cov(hv,rowvar=False)+np.eye(hv.shape[1])*1e-5;inv=np.linalg.pinv(cov)
    def md(h):
        d=h-mu;return np.sqrt(np.einsum("ij,jk,ik->i",d,inv,d))
    mdv=md(hv);mdt=md(ht);md_thr=float(np.quantile(mdv,.995))
    abst=(entropy(pt)>ent_thr)|((qt[:,2]-qt[:,0])>width_thr)|(mdt>md_thr)
    keep=~abst
    acc=bri=ll=mae=None
    if keep.any():
        pred=np.argmax(pt[keep],1)
        acc=float(accuracy_score(yte[keep],pred))
        bri=brier(yte[keep],pt[keep])
        ll=float(log_loss(yte[keep],pt[keep],labels=[0,1,2]))
        mae=float(mean_absolute_error(rte[keep],rt[keep]))
    OUT.mkdir(parents=True,exist_ok=True)
    model_path=OUT/f"{sym}_fold{fold_no}.pt"
    torch.save({"state_dict":model.state_dict(),"scaler_mean":scaler.mean_,"scaler_scale":scaler.scale_,"features":FEATURES},model_path)
    return {
      "symbol":str(sym),"fold":fold_no,
      "train_start":str(pd.Timestamp(dates[a]).date()),"train_end":str(pd.Timestamp(dates[b-1]).date()),
      "val_start":str(pd.Timestamp(dates[b]).date()),"val_end":str(pd.Timestamp(dates[c-1]).date()),
      "test_start":str(pd.Timestamp(dates[d]).date()),"test_end":str(pd.Timestamp(dates[e-1]).date()),
      "k_train_q333":k,"direction_accuracy":acc,"brier":bri,"log_loss":ll,"mae_return":mae,
      "coverage":float(keep.mean()),"abstain_count":int(abst.sum()),"test_n":len(yte),
      "entropy_q95":ent_thr,"quantile_width_q95":width_thr,"latent_md_q995":md_thr,
      "model_sha256":sha256_file(model_path),"seed":SEED
    }

def main():
    if not IN_MATRIX.exists(): raise SystemExit("canonical PIT matrix missing")
    df=pd.read_csv(IN_MATRIX);df["date"]=pd.to_datetime(df["date"])
    metrics=[]
    for sym,g in df.groupby("symbol"):
        g=g.sort_values("date").dropna(subset=FEATURES+["target_ret1","vol20"])
        X,r,s,d=make_sequences(g)
        start=0;fold=0
        while start+TRAIN+VAL+PURGE+TEST<=len(X):
            metrics.append(train_fold(sym,fold,X,r,s,d,start))
            fold+=1;start+=STEP
    if not metrics: raise RuntimeError("no eligible neural shadow folds")
    m=pd.DataFrame(metrics)
    m.to_csv(OUT/"fold_metrics.csv",index=False,encoding="utf-8-sig")
    summary={
      "status":"PASS_SHADOW_NN","architecture":"TCN32x2+MLP32->Fusion64",
      "lookback":LOOKBACK,"split":{"train":TRAIN,"validation":VAL,"purge":PURGE,"test":TEST,"step":STEP},
      "feature_store_sha256":sha256_file(IN_MATRIX),"features":FEATURES,"seed":SEED,
      "folds":len(m),"symbols":sorted(m.symbol.unique().astype(str).tolist()),
      "mean_coverage":float(m.coverage.mean()),
      "mean_direction_accuracy":float(m.direction_accuracy.dropna().mean()),
      "mean_brier":float(m.brier.dropna().mean()),"mean_log_loss":float(m.log_loss.dropna().mean()),
      "mean_mae_return":float(m.mae_return.dropna().mean()),
      "production":"NO_INTERACTION","auto_promotion":False
    }
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__":main()
