#!/usr/bin/env python3
"""R147 simple shadow baselines: multinomial logistic + Ridge.

Inputs are official TWSE PIT CSVs produced by this repo.
Strict time split, no shuffle, train-only scaling and label calibration.
Shadow only: never writes Production weights/trades/cash.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, mean_absolute_error, accuracy_score

SEED=20260928
TRAIN=504
VAL=126
PURGE=10
TEST=20
STEP=20
EPS=1e-12
IN_STOCK=Path("output/a_plus_daily/a_plus_2023_2026_official.csv")
IN_MKT=Path("output/taiex_2023_2026_official.csv")
OUT=Path("output/shadow_baseline")
FEATURES=["ret1","ret5","vol20","volume_z20","mkt_ret1","mkt_ret5","mkt_vol20"]

def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def q333(x):
    return float(np.quantile(np.asarray(x,dtype=float),1/3))

def labels(ret,sigma,k):
    thr=k*sigma
    return np.where(ret>thr,"UP",np.where(ret<-thr,"DOWN","SIDE"))

def brier_multiclass(y_true, probs, classes):
    y=np.zeros_like(probs)
    pos={c:i for i,c in enumerate(classes)}
    for i,c in enumerate(y_true): y[i,pos[c]]=1
    return float(np.mean(np.sum((probs-y)**2,axis=1)))

def prep():
    x=pd.read_csv(IN_MATRIX)
    x["date"]=pd.to_datetime(x["date"])
    x=x.dropna(subset=FEATURES+["target_ret1","vol20"]).sort_values(["symbol","date"])
    x=x.rename(columns={"target_ret1":"fwd_ret1"})
    return x
#!/usr/bin/env python3
"""R147 simple shadow baselines: multinomial logistic + Ridge.

Inputs are official TWSE PIT CSVs produced by this repo.
Strict time split, no shuffle, train-only scaling and label calibration.
Shadow only: never writes Production weights/trades/cash.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, mean_absolute_error, accuracy_score

SEED=20260928
TRAIN=504
VAL=126
PURGE=10
TEST=20
STEP=20
EPS=1e-12
IN_STOCK=Path("output/a_plus_daily/a_plus_2023_2026_official.csv")
IN_MKT=Path("output/taiex_2023_2026_official.csv")
OUT=Path("output/shadow_baseline")
FEATURES=["ret1","ret5","vol20","volume_z20","mkt_ret1","mkt_ret5","mkt_vol20"]

def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def q333(x):
    return float(np.quantile(np.asarray(x,dtype=float),1/3))

def labels(ret,sigma,k):
    thr=k*sigma
    return np.where(ret>thr,"UP",np.where(ret<-thr,"DOWN","SIDE"))

def brier_multiclass(y_true, probs, classes):
    y=np.zeros_like(probs)
    pos={c:i for i,c in enumerate(classes)}
    for i,c in enumerate(y_true): y[i,pos[c]]=1
    return float(np.mean(np.sum((probs-y)**2,axis=1)))

def prep():
    s=pd.read_csv(IN_STOCK)
    m=pd.read_csv(IN_MKT)
    for df in (s,m): df["date"]=pd.to_datetime(df["date"])
    m=m.sort_values("date").copy()
    m["mkt_ret1"]=m["close"].pct_change()
    m["mkt_ret5"]=m["close"].pct_change(5)
    m["mkt_vol20"]=np.log(m["close"]).diff().rolling(20).std()
    out=[]
    for sym,g in s.groupby("symbol"):
        g=g.sort_values("date").copy()
        g["ret1"]=g["close"].pct_change()
        g["ret5"]=g["close"].pct_change(5)
        g["vol20"]=np.log(g["close"]).diff().rolling(20).std()
        lv=np.log1p(g["volume"].replace(0,np.nan))
        g["volume_z20"]=(lv-lv.rolling(20).mean())/lv.rolling(20).std()
        g["fwd_ret1"]=g["close"].shift(-1)/g["close"]-1
        g=g.merge(m[["date","mkt_ret1","mkt_ret5","mkt_vol20"]],on="date",how="left")
        g["symbol"]=sym
        out.append(g)
    x=pd.concat(out,ignore_index=True)
    x=x.dropna(subset=FEATURES+["fwd_ret1","vol20"]).sort_values(["symbol","date"])
    return x

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not IN_STOCK.exists() or not IN_MKT.exists():
        raise SystemExit("official PIT inputs missing")
    data=prep()
    folds=[]
    coefs=[]
    for sym,g in data.groupby("symbol"):
        g=g.reset_index(drop=True)
        start=0
        fold_no=0
        while start+TRAIN+VAL+PURGE+TEST <= len(g):
            tr=g.iloc[start:start+TRAIN].copy()
            va=g.iloc[start+TRAIN:start+TRAIN+VAL].copy()
            te=g.iloc[start+TRAIN+VAL+PURGE:start+TRAIN+VAL+PURGE+TEST].copy()
            k=q333(np.abs(tr["fwd_ret1"]/tr["vol20"]))
            ytr=labels(tr["fwd_ret1"].values,tr["vol20"].values,k)
            yva=labels(va["fwd_ret1"].values,va["vol20"].values,k)
            yte=labels(te["fwd_ret1"].values,te["vol20"].values,k)
            if len(set(ytr))<3:
                start+=STEP; continue
            scaler=StandardScaler().fit(tr[FEATURES])
            Xtr=scaler.transform(tr[FEATURES]); Xva=scaler.transform(va[FEATURES]); Xte=scaler.transform(te[FEATURES])
            clf=LogisticRegression(multi_class="multinomial",solver="lbfgs",max_iter=2000,random_state=SEED)
            clf.fit(Xtr,ytr)
            ridge=Ridge(alpha=20.0)
            ridge.fit(Xtr,tr["fwd_ret1"].values)
            p=clf.predict_proba(Xte); pred=clf.classes_[np.argmax(p,axis=1)]
            rhat=ridge.predict(Xte)
            ll=float(log_loss(yte,np.clip(p,EPS,1-EPS),labels=clf.classes_))
            br=brier_multiclass(yte,p,clf.classes_)
            acc=float(accuracy_score(yte,pred))
            mae=float(mean_absolute_error(te["fwd_ret1"],rhat))
            folds.append({
                "symbol":str(sym),"fold":fold_no,
                "train_start":tr["date"].iloc[0].date().isoformat(),"train_end":tr["date"].iloc[-1].date().isoformat(),
                "val_start":va["date"].iloc[0].date().isoformat(),"val_end":va["date"].iloc[-1].date().isoformat(),
                "test_start":te["date"].iloc[0].date().isoformat(),"test_end":te["date"].iloc[-1].date().isoformat(),
                "k_train_q333":k,"direction_accuracy":acc,"brier":br,"log_loss":ll,"mae_return":mae,
                "test_n":len(te),"seed":SEED,
            })
            coefs.append({
                "symbol":str(sym),"fold":fold_no,"classes":clf.classes_.tolist(),
                "features":FEATURES,"logistic_coef":clf.coef_.tolist(),"logistic_intercept":clf.intercept_.tolist(),
                "ridge_coef":ridge.coef_.tolist(),"ridge_intercept":float(ridge.intercept_),
                "scaler_mean":scaler.mean_.tolist(),"scaler_scale":scaler.scale_.tolist(),
            })
            fold_no+=1; start+=STEP
    if not folds:
        raise RuntimeError("no eligible walk-forward folds; coverage still insufficient")
    df=pd.DataFrame(folds)
    df.to_csv(OUT/"fold_metrics.csv",index=False,encoding="utf-8-sig")
    (OUT/"model_receipts.json").write_text(json.dumps(coefs,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={
      "status":"PASS_SHADOW_BASELINE","seed":SEED,
      "split":{"train":TRAIN,"validation":VAL,"purge":PURGE,"test":TEST,"step":STEP,"shuffle":False},
      "features":FEATURES,"folds":len(folds),"symbols":sorted(df.symbol.unique().tolist()),
      "mean_direction_accuracy":float(df.direction_accuracy.mean()),
      "mean_brier":float(df.brier.mean()),"mean_log_loss":float(df.log_loss.mean()),
      "mean_mae_return":float(df.mae_return.mean()),
      "feature_store_sha256":sha256_file(IN_MATRIX),
      "production":"NO_INTERACTION","auto_promotion":False
    }
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__": main()
