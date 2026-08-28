import csv, io, re, zipfile, requests
from collections import defaultdict
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0'})
repo='yukishirotsubasa/tw-stock-data-release';tag='daily-close-csv'
targets={'0050':'20180102','00400A':'20260409','009820':'20260423','2207':'20180102','2308':'20180102','2317':'20180102','2330':'20180102','2368':'20180102','2376':'20180102','2382':'20180102','2383':'20180102','2454':'20180102','2634':'20180102','2834':'20180102','2885':'20180102','3293':'20180102','3491':'20180102','3665':'20180102','4916':'20180102','6770':'20211206'}
j=S.get(f'https://api.github.com/repos/{repo}/releases/tags/{tag}',timeout=30).json();assets=[]
for a in j['assets']:
 n=a['name']
 if re.fullmatch(r'yearly_20(18|19|20|21|22|23|24|25)\.zip',n):assets.append(a)
 elif re.fullmatch(r'weekly_2026_W\d{2}\.zip',n) and int(re.search(r'W(\d+)',n).group(1))<=34:assets.append(a)
dates=defaultdict(set)
for a in assets:
 b=S.get(a['browser_download_url'],timeout=120).content
 z=zipfile.ZipFile(io.BytesIO(b))
 for fn in z.namelist():
  if not fn.endswith('.csv'):continue
  try:t=z.read(fn).decode('utf-8-sig')
  except:t=z.read(fn).decode('cp950',errors='replace')
  for r in csv.DictReader(io.StringIO(t)):
   lo={str(k).strip().lower():v for k,v in r.items()};c=str(lo.get('code') or '').strip();d=re.sub(r'\D','',str(lo.get('date') or ''))[:8]
   if c in targets and len(d)==8 and targets[c]<=d<='20260817':dates[c].add(d)
calendar=dates['3293']
print('calendar3293',len(calendar),min(calendar),max(calendar))
for c,start in targets.items():
 cand=sorted(d for d in calendar if start<=d<='20260817' and d not in dates[c])
 print(c,'release_dates',len(dates[c]),'calendar_candidates',len(cand),','.join(cand[:50]))
