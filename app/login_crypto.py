from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import Settings, get_settings

LOGIN_ENCRYPTION_ALGORITHM = "RSA-OAEP-256"
LOGIN_ENCRYPTION_KEY_SIZE = 3072
LOGIN_PASSWORD_MAX_LENGTH = 500
LOGIN_PASSWORD_MAX_BYTES = 318


class LoginEncryptionError(ValueError):
    """Raised when an encrypted login payload cannot be decrypted."""


class LoginEncryptionNotConfigured(LoginEncryptionError):
    """Raised when the server has no usable login encryption key."""


class LoginEncryptionKeyMismatch(LoginEncryptionError):
    """Raised when the client encrypted a password with an old key."""


@dataclass(frozen=True)
class LoginEncryptionKey:
    key_id: str
    public_key: str
    private_key: rsa.RSAPrivateKey


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_base64url(value: str) -> bytes:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    if not value or any(character not in alphabet for character in value):
        raise LoginEncryptionError("登录加密数据不合法")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as error:
        raise LoginEncryptionError("登录加密数据不合法") from error


def _decode_private_key(encoded: str) -> rsa.RSAPrivateKey:
    if not encoded:
        raise LoginEncryptionNotConfigured("登录加密密钥尚未配置")
    try:
        der = base64.b64decode(encoded, validate=True)
        private_key = serialization.load_der_private_key(der, password=None)
    except (UnsupportedAlgorithm, ValueError, TypeError, binascii.Error) as error:
        raise LoginEncryptionNotConfigured("登录加密密钥配置无效") from error
    if not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size < LOGIN_ENCRYPTION_KEY_SIZE:
        raise LoginEncryptionNotConfigured("登录加密密钥配置无效")
    return private_key


@lru_cache(maxsize=4)
def _load_private_key(encoded: str) -> rsa.RSAPrivateKey:
    return _decode_private_key(encoded)


def get_login_encryption_key(settings: Settings | None = None) -> LoginEncryptionKey:
    configured_settings = settings or get_settings()
    private_key = _load_private_key(configured_settings.login_private_key_b64.get_secret_value())
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return LoginEncryptionKey(
        key_id=hashlib.sha256(public_der).hexdigest(),
        public_key=encode_base64url(public_der),
        private_key=private_key,
    )


def decrypt_password(
    encrypted_key: LoginEncryptionKey,
    *,
    key_id: str,
    algorithm: str,
    encrypted_password: str,
) -> str:
    if algorithm != LOGIN_ENCRYPTION_ALGORITHM:
        raise LoginEncryptionError("登录加密数据不合法")
    if key_id != encrypted_key.key_id:
        raise LoginEncryptionKeyMismatch("登录加密密钥已更新，请重试")

    ciphertext_bytes = decode_base64url(encrypted_password)
    if len(ciphertext_bytes) != encrypted_key.private_key.key_size // 8:
        raise LoginEncryptionError("登录加密数据不合法")

    try:
        password_bytes = encrypted_key.private_key.decrypt(
            ciphertext_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        password = password_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise LoginEncryptionError("登录加密数据不合法") from error

    if (
        not 1 <= len(password) <= LOGIN_PASSWORD_MAX_LENGTH
        or len(password_bytes) > LOGIN_PASSWORD_MAX_BYTES
    ):
        raise LoginEncryptionError("登录加密数据不合法")
    return password
