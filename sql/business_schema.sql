BEGIN;

CREATE TABLE research_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind varchar(8) NOT NULL,
    slug varchar(20) NOT NULL,
    title varchar(200) NOT NULL,
    date_label varchar(80) NOT NULL,
    content text NOT NULL,
    version integer NOT NULL DEFAULT 1,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX research_reviews_kind_slug_uidx ON research_reviews (kind, slug);
CREATE INDEX research_reviews_kind_date_idx ON research_reviews (kind, date_label);

CREATE TABLE trades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status varchar(16) NOT NULL,
    trade_date date NOT NULL,
    instrument_code varchar(80),
    symbol varchar(160) NOT NULL,
    market varchar(24) NOT NULL,
    side varchar(16) NOT NULL,
    strategy varchar(120) NOT NULL,
    timeframe varchar(40) NOT NULL,
    entry_at timestamptz NOT NULL,
    exit_at timestamptz,
    entry_reason text NOT NULL,
    exit_reason text,
    entry_price numeric(30, 10) NOT NULL,
    exit_price numeric(30, 10),
    position_size numeric(30, 10) NOT NULL,
    position_basis varchar(16) NOT NULL,
    settlement_currency varchar(12) NOT NULL,
    planned_risk_amount numeric(30, 10),
    fees numeric(30, 10) NOT NULL DEFAULT 0,
    fx_to_cny numeric(30, 10) NOT NULL,
    gross_pnl numeric(30, 10),
    net_pnl numeric(30, 10),
    pnl_cny numeric(30, 10),
    r_multiple numeric(30, 10),
    hold_minutes integer,
    is_winning boolean,
    execution_grade varchar(4),
    emotion varchar(80),
    error_notes text,
    did_well text,
    next_improvement text,
    source_file_hash varchar(64),
    source_row integer,
    deleted_at timestamptz,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX trades_trade_date_idx ON trades (trade_date);
CREATE INDEX trades_market_idx ON trades (market);
CREATE INDEX trades_status_idx ON trades (status);
CREATE INDEX trades_date_entry_idx ON trades (trade_date DESC, entry_at DESC);
CREATE UNIQUE INDEX trades_source_row_uidx ON trades (source_file_hash, source_row);

CREATE TABLE daily_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    review_date date NOT NULL,
    market_plan text,
    daily_summary text,
    best_trade_id uuid REFERENCES trades(id) ON DELETE SET NULL,
    biggest_mistake text,
    tomorrow_one_thing text,
    planned_only boolean,
    followed_stops boolean,
    avoided_impulse_adds boolean,
    avoided_revenge_trading boolean,
    exited_as_planned boolean,
    priority_fix text,
    notes text,
    deleted_at timestamptz,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX daily_reviews_date_uidx ON daily_reviews (review_date);

CREATE TABLE trading_options (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind varchar(24) NOT NULL,
    label varchar(120) NOT NULL,
    active boolean NOT NULL DEFAULT true,
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX trading_options_kind_label_uidx ON trading_options (kind, label);

CREATE TABLE trade_error_tags (
    trade_id uuid NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    option_id uuid NOT NULL REFERENCES trading_options(id) ON DELETE CASCADE,
    PRIMARY KEY (trade_id, option_id)
);

CREATE TABLE trade_attachments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id uuid NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    object_key text NOT NULL,
    file_name varchar(255) NOT NULL,
    content_type varchar(80) NOT NULL,
    size integer NOT NULL,
    width integer,
    height integer,
    sort_order integer NOT NULL DEFAULT 0,
    is_cover boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX trade_attachments_trade_idx ON trade_attachments (trade_id, sort_order);
CREATE UNIQUE INDEX trade_attachments_object_key_uidx ON trade_attachments (object_key);

CREATE TABLE trading_settings (
    key varchar(80) PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_hash varchar(64) NOT NULL,
    source_name varchar(255) NOT NULL,
    status varchar(24) NOT NULL,
    row_count integer NOT NULL DEFAULT 0,
    attachment_count integer NOT NULL DEFAULT 0,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX import_batches_source_uidx ON import_batches (source_hash);

CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash char(64) NOT NULL,
    username varchar(120) NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX auth_sessions_token_hash_uidx ON auth_sessions (token_hash);
CREATE INDEX auth_sessions_expires_at_idx ON auth_sessions (expires_at);

COMMIT;
