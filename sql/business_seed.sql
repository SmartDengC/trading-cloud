BEGIN;

INSERT INTO trading_options (kind, label, sort_order) VALUES
    ('strategy', '趋势突破', 10),
    ('strategy', '回调低吸', 20),
    ('strategy', '区间反转', 30),
    ('strategy', '情绪龙头', 40),
    ('strategy', '其他', 90),
    ('timeframe', '1分', 10),
    ('timeframe', '5分', 20),
    ('timeframe', '15分', 30),
    ('timeframe', '1小时', 40),
    ('timeframe', '日线', 50),
    ('emotion', '平静', 10),
    ('emotion', '自信', 20),
    ('emotion', '犹豫', 30),
    ('emotion', '急躁', 40),
    ('emotion', '恐惧', 50),
    ('emotion', '报复性', 60),
    ('error_tag', '追涨杀跌', 10),
    ('error_tag', '计划外交易', 20),
    ('error_tag', '止损犹豫', 30),
    ('error_tag', '过早止盈', 40),
    ('error_tag', '冲动加仓', 50),
    ('error_tag', '报复性交易', 60),
    ('error_tag', '仓位过重', 70),
    ('error_tag', '逆势交易', 80),
    ('error_tag', '未按计划离场', 90)
ON CONFLICT (kind, label) DO NOTHING;

INSERT INTO trading_settings (key, value)
VALUES ('default_usdt_cny_rate', '7.2')
ON CONFLICT (key) DO NOTHING;

COMMIT;

