import calendar
import re
from decimal import Decimal

import build_all20_adjusted_v2 as m

# Correct official row-count gates after comparing the public release calendar
# with TWSE STOCK_DAY. The public release omitted the same three TWSE trading
# dates (2023-05-25, 2025-02-06, 2026-05-28) for the final three symbols.
m.TARGETS['3665'] = ('貿聯-KY','TWSE','20180102',2097)
m.TARGETS['4916'] = ('事欣科','TWSE','20180102',2097)
m.TARGETS['6770'] = ('力積電','TWSE','20211206',1138)

# Unified official source-row / tradable-price-row / no-trade-placeholder totals.
m.EXPECTED_TOTAL_SOURCE = 36939
m.EXPECTED_TOTAL_NO_TRADE = 6
m.EXPECTED_TOTAL_PRICE = 36933

# Full official corporate-action count for the last three symbols.
# 3665 has 10 events, including the 2023-04-20 cash-capital-increase ex-right event.
m.EXPECTED_LAST3_EVENTS['3665'] = 10
m.EXPECTED_LAST3_EVENTS['4916'] = 9
m.EXPECTED_LAST3_EVENTS['6770'] = 3

# TWSE rate-limits long sequences of monthly TWT49U requests. Use quarterly
# windows instead (35 requests through 2026-08-17), preserving the same
# official endpoint and event-factor methodology.
def quarterly_windows():
    for year in range(2018, 2027):
        for q_start in (1, 4, 7, 10):
            if year == 2026 and q_start == 10:
                continue
            q_end = q_start + 2
            start = f'{year:04d}{q_start:02d}01'
            last_day = calendar.monthrange(year, q_end)[1]
            end = f'{year:04d}{q_end:02d}{last_day:02d}'
            if start > m.CUTOFF:
                continue
            if end > m.CUTOFF:
                end = m.CUTOFF
            yield start, end


def parse_twse_actions_quarterly_with_split():
    events = []
    errors = []
    for start, end in quarterly_windows():
        url = (
            'https://www.twse.com.tw/rwd/zh/exRight/TWT49U'
            f'?startDate={start}&endDate={end}&response=json'
        )
        try:
            data = m.get(url, 30).json()
        except Exception as exc:
            errors.append([start, end, 'TWSE', repr(exc), url])
            continue
        for row in data.get('data', []):
            if len(row) < 5:
                continue
            event_date = m.norm_date(row[0])
            code = re.sub(r'<[^>]+>', '', str(row[1])).strip()
            previous_close = m.dec(row[3])
            reference_price = m.dec(row[4])
            if (
                code in m.TARGETS
                and m.TARGETS[code][1] == 'TWSE'
                and event_date
                and m.TARGETS[code][2] <= event_date <= m.CUTOFF
                and previous_close is not None
                and reference_price is not None
                and previous_close > 0
                and reference_price > 0
            ):
                events.append({
                    'event_date': event_date,
                    'code': code,
                    'name': m.TARGETS[code][0],
                    'market': 'TWSE',
                    'previous_close': previous_close,
                    'reference_price': reference_price,
                    'factor': reference_price / previous_close,
                    'official_source': url,
                })

    # 0050 4:1 ETF split is outside the regular TWT49U feed.
    # TWSE announcement: last pre-split close 188.65, new reference 47.16.
    pre = Decimal('188.65')
    ref = Decimal('47.16')
    events.append({
        'event_date': '20250618',
        'code': '0050',
        'name': '元大台灣50',
        'market': 'TWSE',
        'previous_close': pre,
        'reference_price': ref,
        'factor': ref / pre,
        'official_source': 'https://www.twse.com.tw/zh/ETFortune/announcement?company=A00005&date=20250617&fund=0050&seq=1&type=other',
    })
    return events, errors


m.parse_twse_actions = parse_twse_actions_quarterly_with_split

if __name__ == '__main__':
    m.main()
