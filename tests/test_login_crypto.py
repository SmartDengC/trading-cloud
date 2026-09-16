from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Response
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.login_crypto import (
    LOGIN_ENCRYPTION_ALGORITHM,
    LoginEncryptionError,
    LoginEncryptionKeyMismatch,
    LoginEncryptionNotConfigured,
    decrypt_password,
    encode_base64url,
    get_login_encryption_key,
)
from app.routers import auth as auth_router
from app.schemas import LoginInput


@pytest.fixture(scope="module")
def login_key() -> tuple[Settings, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    settings = Settings(login_private_key_b64=SecretStr(base64.b64encode(der).decode("ascii")))
    return settings, private_key


def encrypted_password_payload(
    settings: Settings,
    private_key: rsa.RSAPrivateKey,
    password: str,
) -> dict[str, str]:
    key = get_login_encryption_key(settings)
    ciphertext = private_key.public_key().encrypt(
        password.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "algorithm": LOGIN_ENCRYPTION_ALGORITHM,
        "key_id": key.key_id,
        "ciphertext": encode_base64url(ciphertext),
    }


def test_public_key_is_stable_and_decrypts_password(login_key: tuple[Settings, rsa.RSAPrivateKey]) -> None:
    settings, private_key = login_key
    first = get_login_encryption_key(settings)
    second = get_login_encryption_key(settings)

    assert first.key_id == second.key_id
    public_key = serialization.load_der_public_key(
        base64.urlsafe_b64decode(first.public_key + "=" * (-len(first.public_key) % 4))
    )
    assert isinstance(public_key, rsa.RSAPublicKey)
    payload = encrypted_password_payload(settings, private_key, "secret")

    assert decrypt_password(
        first,
        key_id=payload["key_id"],
        algorithm=payload["algorithm"],
        encrypted_password=payload["ciphertext"],
    ) == "secret"


@pytest.mark.asyncio
async def test_encryption_key_endpoint_disables_caching(
    login_key: tuple[Settings, rsa.RSAPrivateKey],
) -> None:
    response = Response()
    view = await auth_router.encryption_key(response, login_key[0])

    assert view.algorithm == LOGIN_ENCRYPTION_ALGORITHM
    assert view.key_id == get_login_encryption_key(login_key[0]).key_id
    assert response.headers["cache-control"] == "private, no-store"


def test_tampered_ciphertext_and_key_id_are_rejected(
    login_key: tuple[Settings, rsa.RSAPrivateKey],
) -> None:
    settings, private_key = login_key
    key = get_login_encryption_key(settings)
    payload = encrypted_password_payload(settings, private_key, "secret")

    tampered = dict(payload)
    tampered["ciphertext"] = payload["ciphertext"][:-1] + ("A" if payload["ciphertext"][-1] != "A" else "B")
    with pytest.raises(LoginEncryptionError):
        decrypt_password(
            key,
            key_id=payload["key_id"],
            algorithm=payload["algorithm"],
            encrypted_password=tampered["ciphertext"],
        )
    with pytest.raises(LoginEncryptionKeyMismatch):
        decrypt_password(
            key,
            key_id="b" * 64,
            algorithm=payload["algorithm"],
            encrypted_password=payload["ciphertext"],
        )


def test_password_at_rsa_plaintext_limit_is_accepted(
    login_key: tuple[Settings, rsa.RSAPrivateKey],
) -> None:
    settings, private_key = login_key
    payload = encrypted_password_payload(settings, private_key, "a" * 318)
    key = get_login_encryption_key(settings)

    assert decrypt_password(
        key,
        key_id=payload["key_id"],
        algorithm=payload["algorithm"],
        encrypted_password=payload["ciphertext"],
    ) == "a" * 318


def test_plaintext_login_payload_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LoginInput.model_validate({"username": "admin", "password": "secret"})


def test_legacy_hybrid_login_payload_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LoginInput.model_validate(
            {
                "username": "admin",
                "encryptedPassword": {
                    "algorithm": "RSA-OAEP-256+A256GCM",
                    "keyId": "a" * 64,
                    "encryptedKey": "encrypted-key",
                    "iv": "iv",
                    "ciphertext": "ciphertext",
                },
            }
        )


def test_missing_private_key_is_not_usable() -> None:
    with pytest.raises(LoginEncryptionNotConfigured):
        get_login_encryption_key(Settings())
