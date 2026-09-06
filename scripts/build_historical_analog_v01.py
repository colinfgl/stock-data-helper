#!/usr/bin/env python3
"""Build Taiwan broad-market breadth history and strict walk-forward historical analog v0.1.

Research only / SHADOW. It MUST NOT update P4 or production model weights.

Sources:
- Public release archive: yukishirotsubasa/tw-stock-data-release, built from TWSE MI_INDEX + TPEX OTC.
- TAIEX: TWSE official MI_5MINS_HIST monthly endpoint.

Breadth scope is TWSE+TPEX ordinary 4-digit common-stock codes (^[1-9][0-9]{3}$),
not official TWSE-only breadth. This is intentional and explicitly labeled.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(os.environ.get("ANALOG_OUT", "output/historical_analog_v01"))
OUT.mkdir(parents=True, exist_ok=True)
UA = "stock-data-helper historical-analog-v01/1.0"
RELEASE_API = "https://api.github.com/repos/yukishirotsubasa/tw-stock-data-release/releases/tags/daily-close-csv"
COMMON_RE = re.compile(r"^[1-9][0-9]{3}$")


def get_bytes(url: str, retries: int = 4) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"download failed {url}: {last}")


def get_json(url: str, retries: int = 4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json, application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"json failed {url}: {last}")


def fnum(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if not s or s in {"--", "---", "-", "null", "None"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def roc_to_iso(s: str) -> str:
    s = s.strip()
    parts = re.split(r"[/.-]", s)
    if len(parts) != 3:
        return s
    y, m, d = map(int, parts)
    if y < 1911:
        y += 1911
    return f"{y:04d}-{m:02d}-{d:02d}"


def fetch_release_assets():
    rel = get_json(RELEASE_API)
    assets = rel.get("assets", [])
    chosen = []
    for a in assets:
        name = a.get("name", "")
        if re.fullmatch(r"yearly_20(?:0[4-9]|1[0-9]|2[0-5])\.zip", name):
            chosen.append((name, a["browser_download_url"]))
        elif re.fullmatch(r"weekly_2026_W\d{2}\.zip", name):
            chosen.append((name, a["browser_download_url"]))
    def key(item):
        n = item[0]
        if n.startswith("yearly_"):
            return (int(n[7:11]), 0)
        m = re.search(r"W(\d{2})", n)
        return (2026, int(m.group(1)) if m else 99)
    chosen.sort(key=key)
    if not chosen:
        raise RuntimeError("No release assets selected")
    return rel, chosen


def iter_daily_csv_from_zip(name: str, url: str):
    raw = get_bytes(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        entries = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        entries.sort()
        for entry in entries:
            with zf.open(entry) as bf:
                text = io.TextIOWrapper(bf, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                rows = list(reader)
            if not rows:
                continue
            d = str(rows[0].get("date", "")).strip()
            if re.fullmatch(r"\d{8}", d):
                iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            else:
                iso = d
            yield iso, rows


def fetch_taiex():
    out = {}
    today_max = date(2026, 9, 4)
    for y in range(2004, 2027):
        max_m = 12 if y < 2026 else 9
        for m in range(1, max_m + 1):
            if y == 2004 and m == 1:
                continue
            ym = f"{y:04d}{m:02d}01"
            urls = [
                f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={ym}&response=json",
                f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date={ym}",
            ]
            payload = None
            for u in urls:
                try:
                    payload = get_json(u, retries=2)
                    if payload.get("data"):
                        break
                except Exception:
                    payload = None
            if not payload or not payload.get("data"):
                continue
            fields = payload.get("fields", [])
            # Usually: 日期, 開盤指數, 最高指數, 最低指數, 收盤指數
            close_idx = 4
            for i, f in enumerate(fields):
                if "收盤" in str(f):
                    close_idx = i
                    break
            for row in payload.get("data", []):
                if len(row) <= close_idx:
                    continue
                ds = roc_to_iso(str(row[0]))
                try:
                    dt = datetime.strptime(ds, "%Y-%m-%d").date()
                except Exception:
                    continue
                if dt > today_max:
                    continue
                cl = fnum(row[close_idx])
                if cl is not None:
                    out[ds] = cl
            time.sleep(0.03)
    return out


def median(vals):
    return statistics.median(vals) if vals else None


def build_breadth(assets):
    prev_close = {}
    hist = defaultdict(lambda: deque(maxlen=252))
    volume_hist = deque(maxlen=60)
    results = []
    seen_dates = set()
    asset_log = []

    for asset_name, url in assets:
        nday = 0
        nrow = 0
        for ds, rows in iter_daily_csv_from_zip(asset_name, url):
            if ds in seen_dates:
                continue
            seen_dates.add(ds)
            returns = []
            up = down = flat = 0
            nh = nl = 0
            eligible_hilo = 0
            total_vol = 0.0
            current = []
            for r in rows:
                code = str(r.get("code", "")).strip()
                if not COMMON_RE.fullmatch(code):
                    continue
                cl = fnum(r.get("close"))
                vol = fnum(r.get("volume"))
                if cl is None or cl <= 0:
                    continue
                nrow += 1
                if vol is not None and vol >= 0:
                    total_vol += vol
                pc = prev_close.get(code)
                ret = None
                if pc is not None and pc > 0:
                    ret = cl / pc - 1.0
                    returns.append(ret)
                    if ret > 1e-10:
                        up += 1
                    elif ret < -1e-10:
                        down += 1
                    else:
                        flat += 1
                hq = hist[code]
                if len(hq) >= 252:
                    eligible_hilo += 1
                    old = list(hq)
                    if cl > max(old):
                        nh += 1
                    if cl < min(old):
                        nl += 1
                current.append((code, cl))
            adv_dec = (up / down) if down > 0 else (float("inf") if up > 0 else None)
            med = median(returns)
            nret = len(returns)
            adv_share = up / nret if nret else None
            high_share = nh / eligible_hilo if eligible_hilo else None
            low_share = nl / eligible_hilo if eligible_hilo else None
            vr20 = None
            vr60 = None
            if volume_hist:
                last20 = list(volume_hist)[-20:]
                if last20 and statistics.mean(last20) > 0:
                    vr20 = total_vol / statistics.mean(last20)
                if len(volume_hist) >= 20 and statistics.mean(volume_hist) > 0:
                    vr60 = total_vol / statistics.mean(volume_hist)
            results.append({
                "date": ds,
                "scope": "TWSE+TPEX ordinary 4-digit common-stock codes",
                "universe_n": len(current),
                "return_n": nret,
                "up": up,
                "down": down,
                "flat": flat,
                "advance_decline_ratio": adv_dec,
                "advance_share": adv_share,
                "median_return": med,
                "new_252d_high": nh,
                "new_252d_low": nl,
                "hilo_eligible_n": eligible_hilo,
                "new_high_share": high_share,
                "new_low_share": low_share,
                "total_share_volume": total_vol,
                "volume_ratio_20d": vr20,
                "volume_ratio_60d": vr60,
                "source_asset": asset_name,
            })
            volume_hist.append(total_vol)
            for code, cl in current:
                prev_close[code] = cl
                hist[code].append(cl)
            nday += 1
        asset_log.append((asset_name, nday, nrow))
        print(f"processed {asset_name}: days={nday}, common rows={nrow}", flush=True)
    results.sort(key=lambda r: r["date"])
    return results, asset_log


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def pct_rank_z(values):
    # stable standardization; missing stays None. Use mean/std over available current+candidates.
    xs = [x for x in values if x is not None and math.isfinite(x)]
    if len(xs) < 2:
        return [0.0 if x is not None else None for x in values]
    mu = statistics.mean(xs)
    sd = statistics.pstdev(xs)
    if sd < 1e-12:
        return [0.0 if x is not None else None for x in values]
    return [((x - mu) / sd) if x is not None and math.isfinite(x) else None for x in values]


def max_drawdown(closes):
    peak = -1.0
    mdd = 0.0
    for x in closes:
        peak = max(peak, x)
        if peak > 0:
            mdd = min(mdd, x / peak - 1.0)
    return mdd


def realized_vol(rets):
    if len(rets) < 5:
        return None
    return statistics.pstdev(rets) * math.sqrt(252)


def resample_path(cum, n=20):
    if len(cum) < 5:
        return None
    vals=[]
    for i in range(n):
        pos=i*(len(cum)-1)/(n-1)
        lo=int(math.floor(pos)); hi=int(math.ceil(pos))
        if hi==lo:
            vals.append(cum[lo])
        else:
            a=pos-lo
            vals.append(cum[lo]*(1-a)+cum[hi]*a)
    mu=statistics.mean(vals); sd=statistics.pstdev(vals)
    if sd < 1e-12:
        return [0.0]*n
    return [(v-mu)/sd for v in vals]


def build_year_series(taiex, breadth):
    bmap={r["date"]:r for r in breadth}
    years=defaultdict(list)
    dates=sorted(set(taiex).intersection(bmap))
    prev_idx=None
    for ds in dates:
        cl=taiex[ds]
        ret=(cl/prev_idx-1) if prev_idx else None
        prev_idx=cl
        y=int(ds[:4])
        row={"date":ds,"close":cl,"ret":ret, **bmap[ds]}
        years[y].append(row)
    return years


def feature_at(rows, idx):
    seg=rows[:idx+1]
    closes=[r["close"] for r in seg]
    if len(closes)<20:
        return None
    rets=[r["ret"] for r in seg if r.get("ret") is not None]
    first=closes[0]
    cum=[x/first-1 for x in closes]
    path=resample_path(cum,20)
    tr20=closes[-1]/closes[max(0,len(closes)-21)]-1 if len(closes)>=21 else None
    tr60=closes[-1]/closes[max(0,len(closes)-61)]-1 if len(closes)>=61 else None
    v20=realized_vol(rets[-20:]) if len(rets)>=20 else None
    v60=realized_vol(rets[-60:]) if len(rets)>=60 else None
    def avg(field,n):
        xs=[r.get(field) for r in seg[-n:] if r.get(field) is not None and math.isfinite(r.get(field))]
        return statistics.mean(xs) if xs else None
    return {
        "path":path,
        "ytd_return":cum[-1],
        "tr20":tr20,
        "tr60":tr60,
        "vol20":v20,
        "vol60":v60,
        "mdd":max_drawdown(closes),
        "adv20":avg("advance_share",20),
        "adv60":avg("advance_share",60),
        "med20":avg("median_return",20),
        "med60":avg("median_return",60),
        "hl20": (avg("new_high_share",20)-avg("new_low_share",20)) if avg("new_high_share",20) is not None and avg("new_low_share",20) is not None else None,
        "vr20":avg("volume_ratio_20d",20),
    }


def nearest_cut(rows, month, day):
    target=f"{rows[0]['date'][:4]}-{month:02d}-{day:02d}"
    idx=None
    for i,r in enumerate(rows):
        if r["date"]<=target:
            idx=i
        else:
            break
    return idx


def forward_return(rows, idx, horizon):
    j=idx+horizon
    if j>=len(rows):
        return None
    return rows[j]["close"]/rows[idx]["close"]-1


def analog_distance(current, candidates):
    # path shape is its own block, scalar features standardized cross-sectionally.
    scalar_names=["ytd_return","tr20","tr60","vol20","vol60","mdd","adv20","adv60","med20","med60","hl20","vr20"]
    z_by_name={}
    allf=[current]+candidates
    for name in scalar_names:
        z_by_name[name]=pct_rank_z([f.get(name) for f in allf])
    d=[]
    for ci,c in enumerate(candidates, start=1):
        blocks=[]
        if current.get("path") and c.get("path"):
            p=math.sqrt(sum((a-b)**2 for a,b in zip(current["path"],c["path"]))/len(current["path"]))
            blocks.append(p)
        scal=[]
        for name in scalar_names:
            zs=z_by_name[name]
            a=zs[0]; b=zs[ci]
            if a is not None and b is not None:
                scal.append((a-b)**2)
        if scal:
            blocks.append(math.sqrt(sum(scal)/len(scal)))
        d.append(statistics.mean(blocks) if blocks else 999.0)
    return d


def build_analog(years):
    usable={y:r for y,r in years.items() if y>=2005 and len(r)>=150}
    wf=[]
    current_analog=[]
    for y in sorted(usable):
        rows=usable[y]
        # month-end snapshots, plus current last date for 2026
        snap_idx=[]
        for m in range(2,13):
            inds=[i for i,r in enumerate(rows) if int(r["date"][5:7])==m]
            if inds:
                snap_idx.append(max(inds))
        if y==2026 and (len(rows)-1) not in snap_idx:
            snap_idx.append(len(rows)-1)
        for idx in sorted(set(snap_idx)):
            ds=rows[idx]["date"]
            month=int(ds[5:7]); day=int(ds[8:10])
            cf=feature_at(rows,idx)
            if not cf:
                continue
            cand=[]
            for py in sorted(k for k in usable if k<y):
                prow=usable[py]
                pi=nearest_cut(prow,month,day)
                if pi is None or pi<60:
                    continue
                pf=feature_at(prow,pi)
                if pf:
                    cand.append((py,pi,pf))
            if len(cand)<3:
                continue
            distances=analog_distance(cf,[x[2] for x in cand])
            ranked=sorted([(distances[i],cand[i]) for i in range(len(cand))], key=lambda x:x[0])
            top=ranked[:min(5,len(ranked))]
            for horizon in (20,60):
                vals=[]; pos=[]; weights=[]; yrs=[]
                for dist,(py,pi,pf) in top:
                    fr=forward_return(usable[py],pi,horizon)
                    if fr is None:
                        continue
                    w=1.0/max(0.05,dist)
                    vals.append(fr); pos.append(1.0 if fr>0 else 0.0); weights.append(w); yrs.append(py)
                if not vals:
                    continue
                sw=sum(weights)
                pred=sum(v*w for v,w in zip(vals,weights))/sw
                prob=sum(p*w for p,w in zip(pos,weights))/sw
                actual=forward_return(rows,idx,horizon)
                # seasonality baseline = all prior years at same cutoff, not only top analogs
                bvals=[]
                for py,pi,pf in cand:
                    fr=forward_return(usable[py],pi,horizon)
                    if fr is not None:
                        bvals.append(fr)
                base=sum(bvals)/len(bvals) if bvals else 0.0
                base_prob=sum(1 for v in bvals if v>0)/len(bvals) if bvals else 0.5
                # momentum baseline direction uses trailing horizon return; predicted return = trailing horizon return
                past_idx=max(0,idx-horizon)
                mom=rows[idx]["close"]/rows[past_idx]["close"]-1 if idx>past_idx else 0.0
                wf.append({
                    "snapshot_date":ds,"year":y,"horizon":horizon,
                    "top_years":"|".join(map(str,yrs)),
                    "top_distances":"|".join(f"{d:.4f}" for d,_ in top[:len(yrs)]),
                    "analog_pred_return":pred,"analog_prob_up":prob,
                    "seasonal_pred_return":base,"seasonal_prob_up":base_prob,
                    "momentum_pred_return":mom,
                    "actual_return":actual,
                    "analog_correct": (int((pred>0)==(actual>0)) if actual is not None else None),
                    "seasonal_correct": (int((base>0)==(actual>0)) if actual is not None else None),
                    "momentum_correct": (int((mom>0)==(actual>0)) if actual is not None else None),
                    "analog_abs_error": (abs(pred-actual) if actual is not None else None),
                    "seasonal_abs_error": (abs(base-actual) if actual is not None else None),
                    "zero_abs_error": (abs(actual) if actual is not None else None),
                    "analog_brier": ((prob-(1 if actual>0 else 0))**2 if actual is not None else None),
                    "seasonal_brier": ((base_prob-(1 if actual>0 else 0))**2 if actual is not None else None),
                })
            if y==2026 and idx==len(rows)-1:
                for rank,(dist,(py,pi,pf)) in enumerate(top,1):
                    current_analog.append({
                        "asof":ds,"rank":rank,"analog_year":py,"distance":dist,
                        "cut_date":usable[py][pi]["date"],
                        "analog_ytd_return":pf["ytd_return"],
                        "forward_20d_return":forward_return(usable[py],pi,20),
                        "forward_60d_return":forward_return(usable[py],pi,60),
                    })
    return wf,current_analog


def summarize_wf(wf):
    out=[]
    for h in (20,60):
        rows=[r for r in wf if r["horizon"]==h and r["actual_return"] is not None]
        if not rows:
            continue
        def mean_field(k):
            xs=[r[k] for r in rows if r[k] is not None]
            return statistics.mean(xs) if xs else None
        out.append({
            "horizon":h,"n":len(rows),
            "analog_direction_accuracy":mean_field("analog_correct"),
            "seasonal_direction_accuracy":mean_field("seasonal_correct"),
            "momentum_direction_accuracy":mean_field("momentum_correct"),
            "analog_mae":mean_field("analog_abs_error"),
            "seasonal_mae":mean_field("seasonal_abs_error"),
            "zero_mae":mean_field("zero_abs_error"),
            "analog_brier":mean_field("analog_brier"),
            "seasonal_brier":mean_field("seasonal_brier"),
        })
    return out


def bootstrap_accuracy_edge(wf, horizon, b=5000, seed=20260906):
    import random
    rng=random.Random(seed+horizon)
    rows=[r for r in wf if r["horizon"]==horizon and r["actual_return"] is not None]
    diffs=[r["analog_correct"]-r["seasonal_correct"] for r in rows]
    if len(diffs)<10:
        return None
    sims=[]
    n=len(diffs)
    for _ in range(b):
        sims.append(sum(diffs[rng.randrange(n)] for __ in range(n))/n)
    sims.sort()
    return {"horizon":horizon,"n":n,"edge_mean":statistics.mean(diffs),"ci_low":sims[int(.025*b)],"ci_high":sims[int(.975*b)-1]}


def main():
    rel, assets=fetch_release_assets()
    print(f"selected assets={len(assets)} release={rel.get('name')}", flush=True)
    breadth, asset_log=build_breadth(assets)
    print(f"breadth days={len(breadth)} {breadth[0]['date'] if breadth else '?'}..{breadth[-1]['date'] if breadth else '?'}", flush=True)
    taiex=fetch_taiex()
    print(f"TAIEX days={len(taiex)}", flush=True)
    years=build_year_series(taiex,breadth)
    wf,current=build_analog(years)
    summary=summarize_wf(wf)
    boot=[bootstrap_accuracy_edge(wf,h) for h in (20,60)]

    bfields=list(breadth[0].keys()) if breadth else []
    write_csv(OUT/"market_breadth_full_history.csv",breadth,bfields)
    wf_fields=list(wf[0].keys()) if wf else []
    if wf:
        write_csv(OUT/"historical_analog_v01_wf.csv",wf,wf_fields)
    if current:
        write_csv(OUT/"historical_analog_v01_current.csv",current,list(current[0].keys()))
    if summary:
        write_csv(OUT/"historical_analog_v01_summary.csv",summary,list(summary[0].keys()))
    with open(OUT/"historical_analog_v01_manifest.json","w",encoding="utf-8") as f:
        json.dump({
            "generated_at":datetime.utcnow().isoformat()+"Z",
            "status":"SHADOW_RESEARCH_ONLY",
            "source_release":rel.get("html_url"),
            "source_release_name":rel.get("name"),
            "breadth_scope":"TWSE+TPEX ordinary 4-digit common-stock codes; raw close returns; excludes ETFs/warrants; NOT official TWSE-only breadth",
            "breadth_start":breadth[0]["date"] if breadth else None,
            "breadth_end":breadth[-1]["date"] if breadth else None,
            "breadth_rows":len(breadth),
            "taiex_rows":len(taiex),
            "assets":asset_log,
            "analog_rules":{"top_k":5,"path_points":20,"horizons":[20,60],"candidate_years":"strictly earlier years only","snapshot":"month-end","formal_weight":0,"p4":"LOCKED/no interaction"},
            "wf_summary":summary,
            "bootstrap_accuracy_edge_vs_seasonal":boot,
            "limitations":[
                "Breadth is combined TWSE+TPEX common stocks, not official TWSE-only counts.",
                "Returns are raw close-to-close and are not corporate-action adjusted; ex-right/dividend days can affect individual returns.",
                "Market universe changes over time; ratios/medians are preferred to raw counts for analog distance.",
                "No model tuning was performed after viewing 2026; v0.1 uses fixed equal feature blocks and remains Shadow.",
            ],
        },f,ensure_ascii=False,indent=2)
    print(json.dumps({"summary":summary,"bootstrap":boot,"current":current},ensure_ascii=False,indent=2), flush=True)

if __name__=="__main__":
    main()
