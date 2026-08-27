from __future__ import annotations

import argparse
import io
import os
import sys
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

import psycopg
from minio import Minio
from psycopg.rows import dict_row

# Allow direct execution from the repository root without requiring PYTHONPATH=.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

MEMO_NAMESPACE = uuid.UUID("9c4b3b1e-9d11-4c9d-9d4f-41afc70e8b13")
ATTACHMENT_NAMESPACE = uuid.UUID("e48a8ae0-f9b5-48bd-91be-6f8f8ed7d44e")
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024


def stable_uuid(namespace: uuid.UUID, source_id: str) -> uuid.UUID:
    return uuid.uuid5(namespace, source_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Memo Cloud records into Trading Cloud.")
    parser.add_argument("--source-database-url", default=os.getenv("MEMO_DATABASE_URL"))
    parser.add_argument("--source-root", default=os.getenv("MEMO_UPLOAD_DIR", ""))
    parser.add_argument("--source-blob-base-url", default=os.getenv("MEMO_BLOB_BASE_URL", ""))
    parser.add_argument("--target-username", default=get_settings().admin_username)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def source_bytes(attachment: dict[str, Any], source_root: str, blob_base_url: str) -> bytes:
    provider = attachment.get("storageProvider", "local")
    if provider == "local":
        if not source_root:
            raise RuntimeError("local attachment requires --source-root or MEMO_UPLOAD_DIR")
        path = Path(source_root, str(attachment["storagePath"])).resolve()
        root = Path(source_root).resolve()
        if root not in path.parents:
            raise RuntimeError(f"attachment escapes source root: {attachment['id']}")
        return path.read_bytes()
    if provider == "vercelBlob":
        if not blob_base_url:
            raise RuntimeError("Blob attachment requires --source-blob-base-url or MEMO_BLOB_BASE_URL")
        pathname = str(attachment.get("blobPath") or attachment["storagePath"]).lstrip("/")
        request = Request(f"{blob_base_url.rstrip('/')}/{pathname}")
        token = os.getenv("BLOB_READ_WRITE_TOKEN", "")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return cast(bytes, response.read(MAX_ATTACHMENT_SIZE + 1))
    raise RuntimeError(f"unsupported attachment provider: {provider}")


def migrate(args: argparse.Namespace) -> dict[str, int]:
    if not args.source_database_url:
        raise RuntimeError("source database URL is required")
    target = get_settings()
    target_url = target.sync_database_url.replace("postgresql+psycopg://", "postgresql://")
    client = Minio(
        target.minio_endpoint,
        access_key=target.minio_access_key,
        secret_key=target.minio_secret_key,
        secure=target.minio_secure,
    )
    stats = {"memos": 0, "attachments": 0}
    with (
        psycopg.connect(args.source_database_url, row_factory=dict_row) as source,
        psycopg.connect(target_url) as destination,
    ):
        with source.cursor() as cursor:
            cursor.execute('SELECT "id", "username" FROM "User" ORDER BY "id"')
            users = {row["id"]: row["username"] for row in cursor.fetchall()}
            cursor.execute(
                'SELECT "id", "createdAt", "updatedAt", "text", "userId" '
                'FROM "MemoEntry" ORDER BY "createdAt"'
            )
            memos = cursor.fetchall()
            cursor.execute(
                'SELECT "id", "createdAt", "memoEntryId", "originalName", "mimeType", "size", '
                '"storagePath", "storageProvider", "blobPath" FROM "Attachment" ORDER BY "createdAt"'
            )
            attachments = cursor.fetchall()
        attachments_by_memo: dict[str, list[dict[str, Any]]] = {}
        for attachment in attachments:
            attachments_by_memo.setdefault(attachment["memoEntryId"], []).append(attachment)
        for memo in memos:
            owner = users.get(memo["userId"])
            if owner != args.target_username:
                raise RuntimeError(f"source user does not match target username: {owner!r}")
            memo_id = stable_uuid(MEMO_NAMESPACE, memo["id"])
            memo_attachments = attachments_by_memo.get(memo["id"], [])
            if len(memo_attachments) > 12:
                raise RuntimeError(f"Memo {memo['id']} has more than 12 attachments")
            if not memo["text"].strip() and not memo_attachments:
                raise RuntimeError(f"Memo {memo['id']} has neither text nor attachments")
            destination.execute(
                """
                INSERT INTO memos (id, owner_username, text, source_type, version, created_at, updated_at)
                VALUES (%s, %s, %s, 'text', 1, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (memo_id, owner, memo["text"], memo["createdAt"], memo["updatedAt"]),
            )
            stats["memos"] += 1
            for attachment in memo_attachments:
                data = source_bytes(attachment, args.source_root, args.source_blob_base_url)
                if len(data) > MAX_ATTACHMENT_SIZE:
                    raise RuntimeError(f"attachment {attachment['id']} exceeds 20 MB")
                attachment_id = stable_uuid(ATTACHMENT_NAMESPACE, attachment["id"])
                object_key = f"memos/{memo_id}/{attachment_id}"
                if not args.dry_run:
                    client.put_object(
                        target.minio_bucket,
                        object_key,
                        io.BytesIO(data),
                        len(data),
                        content_type=attachment["mimeType"] or "application/octet-stream",
                    )
                    destination.execute(
                        """
                        INSERT INTO memo_attachments (
                            id, memo_id, object_key, file_name, content_type, size, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            attachment_id,
                            memo_id,
                            object_key,
                            attachment["originalName"][:255],
                            attachment["mimeType"] or "application/octet-stream",
                            len(data),
                            attachment["createdAt"],
                            attachment["createdAt"],
                        ),
                    )
                stats["attachments"] += 1
        if args.dry_run:
            destination.rollback()
        else:
            destination.commit()
    return stats


if __name__ == "__main__":
    print(migrate(parse_args()))
