from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings

if TYPE_CHECKING:
    from minio import Minio


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]


TABLES = (
    TableSpec(
        "research_reviews",
        (
            "id",
            "kind",
            "slug",
            "title",
            "date_label",
            "content",
            "version",
            "deleted_at",
            "created_at",
            "updated_at",
        ),
    ),
    TableSpec(
        "trades",
        (
            "id",
            "status",
            "trade_date",
            "instrument_code",
            "symbol",
            "market",
            "side",
            "strategy",
            "timeframe",
            "entry_at",
            "exit_at",
            "entry_reason",
            "exit_reason",
            "entry_price",
            "exit_price",
            "position_size",
            "position_basis",
            "settlement_currency",
            "planned_risk_amount",
            "fees",
            "fx_to_cny",
            "gross_pnl",
            "net_pnl",
            "pnl_cny",
            "r_multiple",
            "hold_minutes",
            "is_winning",
            "execution_grade",
            "emotion",
            "error_notes",
            "did_well",
            "next_improvement",
            "source_file_hash",
            "source_row",
            "deleted_at",
            "version",
            "created_at",
            "updated_at",
        ),
    ),
    TableSpec(
        "daily_reviews",
        (
            "id",
            "review_date",
            "market_plan",
            "daily_summary",
            "best_trade_id",
            "biggest_mistake",
            "tomorrow_one_thing",
            "planned_only",
            "followed_stops",
            "avoided_impulse_adds",
            "avoided_revenge_trading",
            "exited_as_planned",
            "priority_fix",
            "notes",
            "deleted_at",
            "version",
            "created_at",
            "updated_at",
        ),
    ),
    TableSpec("trading_options", ("id", "kind", "label", "active", "sort_order", "created_at", "updated_at")),
    TableSpec("trade_error_tags", ("trade_id", "option_id")),
    TableSpec("trading_settings", ("key", "value", "updated_at")),
    TableSpec(
        "import_batches",
        (
            "id",
            "source_hash",
            "source_name",
            "status",
            "row_count",
            "attachment_count",
            "warnings",
            "completed_at",
            "created_at",
        ),
    ),
)

ATTACHMENT_SOURCE_COLUMNS = (
    "id",
    "trade_id",
    "pathname",
    "blob_url",
    "file_name",
    "content_type",
    "size",
    "width",
    "height",
    "sort_order",
    "is_cover",
    "created_at",
    "updated_at",
)
ATTACHMENT_TARGET_COLUMNS = (
    "id",
    "trade_id",
    "object_key",
    "file_name",
    "content_type",
    "size",
    "width",
    "height",
    "sort_order",
    "is_cover",
    "created_at",
    "updated_at",
)
BUSINESS_TABLE_NAMES = tuple(spec.name for spec in TABLES) + ("trade_attachments",)


def normalized_url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg_async://", "postgresql://"
    )


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, Decimal, UUID)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_hash(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> str:
    normalized = [{column: row.get(column) for column in columns} for row in rows]
    normalized.sort(key=lambda row: json.dumps(row, default=json_value, ensure_ascii=False, sort_keys=True))
    payload = json.dumps(
        normalized, default=json_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_source_integrity(
    source_data: dict[str, list[dict[str, Any]]], attachments: list[dict[str, Any]]
) -> dict[str, list[str]]:
    duplicate_keys: list[str] = []
    orphan_records: list[str] = []

    unique_specs = (
        ("research_reviews", ("kind", "slug")),
        ("daily_reviews", ("review_date",)),
        ("trading_options", ("kind", "label")),
        ("import_batches", ("source_hash",)),
    )
    for table, columns in unique_specs:
        seen: set[tuple[Any, ...]] = set()
        for row in source_data[table]:
            unique_key = tuple(row[column] for column in columns)
            if unique_key in seen:
                duplicate_keys.append(f"{table}:{unique_key}")
            seen.add(unique_key)

    seen_trade_sources: set[tuple[Any, Any]] = set()
    for row in source_data["trades"]:
        trade_source_key = (row["source_file_hash"], row["source_row"])
        if None not in trade_source_key:
            if trade_source_key in seen_trade_sources:
                duplicate_keys.append(f"trades:{trade_source_key}")
            seen_trade_sources.add(trade_source_key)

    attachment_keys: set[str] = set()
    for row in attachments:
        attachment_key = str(row["pathname"])
        if attachment_key in attachment_keys:
            duplicate_keys.append(f"trade_attachments:{attachment_key}")
        attachment_keys.add(attachment_key)

    trade_ids = {row["id"] for row in source_data["trades"]}
    option_ids = {row["id"] for row in source_data["trading_options"]}
    for row in source_data["daily_reviews"]:
        if row["best_trade_id"] is not None and row["best_trade_id"] not in trade_ids:
            orphan_records.append(f"daily_reviews:{row['id']}:best_trade_id")
    for row in source_data["trade_error_tags"]:
        if row["trade_id"] not in trade_ids or row["option_id"] not in option_ids:
            orphan_records.append(f"trade_error_tags:{row['trade_id']}:{row['option_id']}")
    for row in attachments:
        if row["trade_id"] not in trade_ids:
            orphan_records.append(f"trade_attachments:{row['id']}:trade_id")

    if duplicate_keys or orphan_records:
        raise RuntimeError(f"源数据完整性检查失败: duplicates={duplicate_keys}, orphans={orphan_records}")
    return {"duplicateKeys": duplicate_keys, "orphanRecords": orphan_records}


def read_rows(
    connection: psycopg.Connection[Any], table: str, columns: tuple[str, ...]
) -> list[dict[str, Any]]:
    statement = sql.SQL("SELECT {} FROM {} ORDER BY 1").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table)
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement)
        return list(cursor.fetchall())


def blob_bytes(url: str, token: str) -> bytes:
    response = httpx.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Vercel Blob 读取失败 ({response.status_code}): {url}")
    return response.content


def minio_client() -> Minio:
    from minio import Minio

    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def insert_rows(
    connection: psycopg.Connection[Any], table: str, columns: tuple[str, ...], rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    values = []
    for row in rows:
        values.append(
            tuple(Jsonb(row[column]) if column == "warnings" else row[column] for column in columns)
        )
    with connection.cursor() as cursor:
        cursor.executemany(statement, values)


def table_counts(connection: psycopg.Connection[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in BUSINESS_TABLE_NAMES:
            cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            result = cursor.fetchone()
            if result is None:
                raise RuntimeError(f"无法读取目标表行数: {table}")
            counts[table] = int(result[0])
    return counts


def migrate(
    *, source_url: str, target_url: str, blob_token: str, apply: bool, replace: bool
) -> dict[str, Any]:
    settings = get_settings()
    source = psycopg.connect(normalized_url(source_url))
    target = psycopg.connect(normalized_url(target_url))
    storage = minio_client()
    try:
        source.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        source_data = {spec.name: read_rows(source, spec.name, spec.columns) for spec in TABLES}
        source_attachments = read_rows(source, "trade_attachments", ATTACHMENT_SOURCE_COLUMNS)
        source_integrity = validate_source_integrity(source_data, source_attachments)
        target_before = table_counts(target)
        bucket_exists = storage.bucket_exists(settings.minio_bucket)
        target_object_keys = (
            {
                item.object_name
                for item in storage.list_objects(settings.minio_bucket, recursive=True)
                if item.object_name
            }
            if bucket_exists
            else set()
        )
        if apply and (any(target_before.values()) or target_object_keys) and not replace:
            raise RuntimeError("目标业务表非空；确认覆盖时请显式使用 --replace")

        attachment_payloads: dict[str, bytes] = {}
        attachment_checksums: dict[str, str] = {}
        total_bytes = 0
        for row in source_attachments:
            key = str(row["pathname"])
            payload = blob_bytes(str(row["blob_url"]), blob_token)
            if len(payload) != row["size"]:
                raise RuntimeError(f"附件大小不一致: {key}")
            attachment_payloads[key] = payload
            attachment_checksums[key] = hashlib.sha256(payload).hexdigest()
            total_bytes += len(payload)

        attachment_rows = [
            {
                "id": row["id"],
                "trade_id": row["trade_id"],
                "object_key": row["pathname"],
                "file_name": row["file_name"],
                "content_type": row["content_type"],
                "size": row["size"],
                "width": row["width"],
                "height": row["height"],
                "sort_order": row["sort_order"],
                "is_cover": row["is_cover"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in source_attachments
        ]
        source_hashes = {
            name: canonical_hash(rows, next(spec.columns for spec in TABLES if spec.name == name))
            for name, rows in source_data.items()
        }
        source_hashes["trade_attachments"] = canonical_hash(attachment_rows, ATTACHMENT_TARGET_COLUMNS)

        report: dict[str, Any] = {
            "mode": "apply" if apply else "dry-run",
            "sourceCounts": {
                **{name: len(rows) for name, rows in source_data.items()},
                "trade_attachments": len(source_attachments),
            },
            "targetCountsBefore": target_before,
            "targetObjectsBefore": len(target_object_keys),
            "sourceIntegrity": source_integrity,
            "sourceHashes": source_hashes,
            "attachments": {
                "count": len(source_attachments),
                "bytes": total_bytes,
                "sha256": attachment_checksums,
            },
        }
        if not apply:
            return report

        if not bucket_exists:
            storage.make_bucket(settings.minio_bucket)
        for row in source_attachments:
            key = str(row["pathname"])
            payload = attachment_payloads[key]
            storage.put_object(
                settings.minio_bucket,
                key,
                BytesIO(payload),
                len(payload),
                content_type=str(row["content_type"]),
            )

        target.rollback()
        with target.transaction():
            if replace:
                target.execute(
                    "TRUNCATE trade_error_tags, trade_attachments, daily_reviews, trades, research_reviews, "
                    "trading_options, trading_settings, import_batches CASCADE"
                )
            for spec in TABLES:
                insert_rows(target, spec.name, spec.columns, source_data[spec.name])
            insert_rows(target, "trade_attachments", ATTACHMENT_TARGET_COLUMNS, attachment_rows)

        target_after = table_counts(target)
        if report["sourceCounts"] != target_after:
            raise RuntimeError(f"源目标行数不一致: {report['sourceCounts']} != {target_after}")
        target_hashes = {
            spec.name: canonical_hash(read_rows(target, spec.name, spec.columns), spec.columns)
            for spec in TABLES
        }
        target_hashes["trade_attachments"] = canonical_hash(
            read_rows(target, "trade_attachments", ATTACHMENT_TARGET_COLUMNS),
            ATTACHMENT_TARGET_COLUMNS,
        )
        if source_hashes != target_hashes:
            raise RuntimeError(f"源目标数据摘要不一致: {source_hashes} != {target_hashes}")
        for key, expected in attachment_checksums.items():
            response = storage.get_object(settings.minio_bucket, key)
            try:
                actual = hashlib.sha256(response.read()).hexdigest()
            finally:
                response.close()
                response.release_conn()
            if actual != expected:
                raise RuntimeError(f"MinIO 附件哈希不一致: {key}")
        if replace:
            source_object_keys = set(attachment_payloads)
            for stale_key in target_object_keys - source_object_keys:
                storage.remove_object(settings.minio_bucket, stale_key)
        report["targetCountsAfter"] = target_after
        report["targetHashes"] = target_hashes
        report["targetObjectsAfter"] = len(attachment_payloads)
        report["verified"] = True
        return report
    finally:
        source.close()
        target.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Neon and Vercel Blob data into Trading Cloud")
    parser.add_argument("--source", default=os.getenv("LEGACY_DATABASE_URL"))
    parser.add_argument("--target", default=os.getenv("TRADING_DATABASE_URL"))
    parser.add_argument("--blob-token", default=os.getenv("BLOB_READ_WRITE_TOKEN"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--report", default="migration-report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.source or not args.target or not args.blob_token:
        raise SystemExit("缺少 --source、--target 或 --blob-token")
    if args.replace and not args.apply:
        raise SystemExit("--replace 必须与 --apply 一起使用")
    report = migrate(
        source_url=args.source,
        target_url=args.target,
        blob_token=args.blob_token,
        apply=args.apply,
        replace=args.replace,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    Path(args.report).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
