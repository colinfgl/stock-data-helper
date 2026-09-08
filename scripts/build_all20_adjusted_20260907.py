from pathlib import Path
import re

import build_all20_adjusted_v2 as m
import build_all20_adjusted_v2b  # applies robust TWSE month fetch + quarterly TWT49U + corrected R45 gates

# Incremental extension of the R45 canonical logic.  Do not mutate the original
# R45 scripts/cutoff; this wrapper builds a separate artifact through 2026-09-07.
m.CUTOFF = '20260907'
m.OUT = Path('output_all20_20260907')
m.OUT.mkdir(exist_ok=True)

# R45 ended 2026-08-17. There are 15 Taiwan trading dates from 8/18 through 9/7:
# 8/18-21 (4), 8/24-28 (5), 8/31-9/4 (5), 9/7 (1).
for code, (name, market, start, expected) in list(m.TARGETS.items()):
    m.TARGETS[code] = (name, market, start, expected + 15)

m.EXPECTED_TOTAL_SOURCE = 37239  # 36939 + 20*15
m.EXPECTED_TOTAL_NO_TRADE = 6
m.EXPECTED_TOTAL_PRICE = 37233   # 36933 + 20*15
m.EXPECTED_LAST3_EVENTS['3665'] = 10
m.EXPECTED_LAST3_EVENTS['4916'] = 9
m.EXPECTED_LAST3_EVENTS['6770'] = 4  # 2026-08-27 cash dividend adds one event


def release_assets_through_w36():
    rel = m.get(
        f'https://api.github.com/repos/{m.SOURCE_REPO}/releases/tags/{m.SOURCE_TAG}'
    ).json()
    out = []
    for asset in rel.get('assets', []):
        name = asset['name']
        if re.fullmatch(r'yearly_20(18|19|20|21|22|23|24|25)\.zip', name):
            out.append(asset)
        elif re.fullmatch(r'weekly_2026_W\d{2}\.zip', name):
            week = int(re.search(r'W(\d+)', name).group(1))
            if week <= 36:
                out.append(asset)
    return sorted(out, key=lambda a: a['name'])


m.release_assets = release_assets_through_w36
_original_build_release = m.build_release


def build_release_plus_20260907():
    by, manifest = _original_build_release()
    official_added = 0
    official_urls = set()
    for code, (name, market, start, expected) in m.TARGETS.items():
        if market == 'TWSE':
            month_rows, url = m.twse_month_rows(code, '202609')
            row = month_rows.get('20260907')
        else:
            row, url = m.tpex_daily_row(code, '20260907')
        official_urls.add(url)
        if row is None:
            raise RuntimeError(f'missing official 20260907 row for {code}')
        old = by[code].get('20260907')
        if old and any(old[k] != row[k] for k in ('volume', 'open', 'high', 'low', 'close')):
            raise RuntimeError(f'20260907 conflict {code}: release={old} official={row}')
        if not old:
            by[code]['20260907'] = row
            official_added += 1
    manifest.append([
        'OFFICIAL_20260907_ALL20', 0, '', '', True, official_added,
        ' | '.join(sorted(official_urls))
    ])
    return by, manifest


m.build_release = build_release_plus_20260907

if __name__ == '__main__':
    m.main()
