from app.config import Settings
from app.security import hash_session_token, new_session_token


def test_session_tokens_are_random_and_only_hash_is_persisted() -> None:
    first = new_session_token()
    second = new_session_token()
    assert first != second
    assert len(hash_session_token(first)) == 64
    assert first not in hash_session_token(first)


def test_empty_session_cookie_domain_is_disabled() -> None:
    assert Settings(session_cookie_domain="").session_cookie_domain is None
    assert Settings(session_cookie_domain="example.com").session_cookie_domain == "example.com"
