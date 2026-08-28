import build_all20_adjusted_v2 as m

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

if __name__ == '__main__':
    m.main()
