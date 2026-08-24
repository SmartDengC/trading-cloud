from pathlib import Path

import pytest

from app.migration.legacy import BUSINESS_TABLE_NAMES, canonical_hash, validate_source_integrity

ROOT = Path(__file__).resolve().parents[1]


def test_business_ddl_contains_every_migrated_table() -> None:
    ddl = (ROOT / "sql/business_schema.sql").read_text(encoding="utf-8")
    for table in (*BUSINESS_TABLE_NAMES, "auth_sessions"):
        assert f"CREATE TABLE {table} (" in ddl
    assert "blob_url" not in ddl
    assert "object_key text NOT NULL" in ddl


def test_seed_is_separate_and_idempotent() -> None:
    ddl = (ROOT / "sql/business_schema.sql").read_text(encoding="utf-8")
    seed = (ROOT / "sql/business_seed.sql").read_text(encoding="utf-8")
    assert "趋势突破" not in ddl
    assert "趋势突破" in seed
    assert "ON CONFLICT" in seed


def test_canonical_hash_is_order_independent() -> None:
    rows = [{"id": 2, "value": "b"}, {"id": 1, "value": "a"}]
    assert canonical_hash(rows, ("id", "value")) == canonical_hash(list(reversed(rows)), ("id", "value"))


def test_source_integrity_rejects_orphan_attachments() -> None:
    source = {
        "research_reviews": [],
        "trades": [],
        "daily_reviews": [],
        "trading_options": [],
        "trade_error_tags": [],
        "trading_settings": [],
        "import_batches": [],
    }
    attachments = [{"id": "attachment", "trade_id": "missing", "pathname": "legacy/path.png"}]
    with pytest.raises(RuntimeError, match="trade_attachments:attachment:trade_id"):
        validate_source_integrity(source, attachments)
