import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_accepts_one_symbols_placeholder_in_quotes_url() -> None:
    settings = Settings(sina_quotes_url="http://relay.test/sina-quotes/{symbols}")

    assert settings.sina_quotes_url == "http://relay.test/sina-quotes/{symbols}"


def test_settings_defaults_to_direct_sina_quotes_url() -> None:
    assert Settings().sina_quotes_url == "https://hq.sinajs.cn/list={symbols}"


@pytest.mark.parametrize(
    "quotes_url",
    [
        "http://relay.test/sina-quotes",
        "http://relay.test/sina-quotes/{symbols}/{symbols}",
        "http://relay.test/sina-quotes/{symbol}",
        "http://relay.test/sina-quotes/{symbols:>10}",
        "http://relay.test/sina-quotes/{symbols!r}",
    ],
)
def test_settings_rejects_invalid_symbols_placeholder(quotes_url: str) -> None:
    with pytest.raises(ValidationError, match=r"exactly one \{symbols\}"):
        Settings(sina_quotes_url=quotes_url)
