from __future__ import annotations

import uuid

from scripts.migrate_memos import ATTACHMENT_NAMESPACE, MEMO_NAMESPACE, stable_uuid


def test_migration_ids_are_stable_and_distinct() -> None:
    memo_id = stable_uuid(MEMO_NAMESPACE, "cuid-1")
    assert memo_id == stable_uuid(MEMO_NAMESPACE, "cuid-1")
    assert memo_id != stable_uuid(ATTACHMENT_NAMESPACE, "cuid-1")
    assert isinstance(memo_id, uuid.UUID)
