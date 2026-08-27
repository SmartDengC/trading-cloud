from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.memo_service import build_memo_view, validate_memo_files


def test_validate_memo_files_rejects_empty_memo() -> None:
    with pytest.raises(ValueError, match="正文或附件至少填写一项"):
        validate_memo_files("", [])


def test_validate_memo_files_rejects_audio_and_oversized_files() -> None:
    audio = SimpleNamespace(filename="record.webm", content_type="audio/webm", size=10)
    with pytest.raises(ValueError, match="不支持音频附件"):
        validate_memo_files("memo", [audio])

    large = SimpleNamespace(filename="large.pdf", content_type="application/pdf", size=20 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="不能超过 20 MB"):
        validate_memo_files("memo", [large])


def test_validate_memo_files_counts_existing_attachments() -> None:
    file = SimpleNamespace(filename="chart.png", content_type="image/png", size=10)
    with pytest.raises(ValueError, match="每条 Memo 最多上传 12 个附件"):
        validate_memo_files("memo", [file], existing_count=12)


def test_build_memo_view_serializes_attachment_access_url() -> None:
    memo = SimpleNamespace(
        id="memo-1",
        owner_username="admin",
        text="hello",
        version=1,
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-27T00:00:00+00:00"),
        updated_at=SimpleNamespace(isoformat=lambda: "2026-08-27T00:00:00+00:00"),
    )
    attachment = SimpleNamespace(
        id="file-1",
        file_name="note.txt",
        content_type="text/plain",
        size=5,
        created_at=SimpleNamespace(isoformat=lambda: "2026-08-27T00:00:00+00:00"),
    )

    result = build_memo_view(memo, [attachment])

    assert result["id"] == "memo-1"
    assert result["attachments"][0]["access_url"] == "/api/memos/attachments/file-1"
