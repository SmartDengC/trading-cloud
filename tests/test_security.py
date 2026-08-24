from app.security import hash_session_token, new_session_token


def test_session_tokens_are_random_and_only_hash_is_persisted() -> None:
    first = new_session_token()
    second = new_session_token()
    assert first != second
    assert len(hash_session_token(first)) == 64
    assert first not in hash_session_token(first)
