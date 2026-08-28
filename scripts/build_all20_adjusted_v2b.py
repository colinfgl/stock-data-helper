import build_all20_adjusted_v2 as m
from decimal import Decimal

# Correct official row-count gates after comparing the public release calendar
# with TWSE STOCK_DAY. The release omitted the same three TWSE trading dates
# (2023-05-25, 2025-02-06, 2026-05-28) for these final three symbols.
m.TARGETS['3665'] = ('貿聯-KY','TWSE','20180102',2097)
m.TARGETS['4916'] = ('事欣科','TWSE','20180102',2097)
m.TARGETS['6770'] = ('力積電','TWSE','20211206',1138)

# Unified official source-row / tradable-price-row / no-trade-placeholder totals.
m.EXPECTED_TOTAL_SOURCE = 36939
m.EXPECTED_TOTAL_NO_TRADE = 6
m.EXPECTED_TOTAL_PRICE = 36933

# TWSE ETF split is a corporate action outside the regular ex-right/ex-dividend
# TWT49U feed. Official announcement: 0050 split 4:1, new units trade 2025-06-18;
# last pre-split close 188.65 and post-split reference price 47.16.
_original_parse_twse_actions = m.parse_twse_actions

def parse_twse_actions_with_0050_split():
    events, errors = _original_parse_twse_actions()
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

m.parse_twse_actions = parse_twse_actions_with_0050_split

if __name__ == '__main__':
    m.main()
