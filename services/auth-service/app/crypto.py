import base64
import hashlib
import logging
import os
import pathlib

import bcrypt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common.security import encode_token, public_jwk

logger = logging.getLogger(__name__)


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def load_or_create_private_key(path: str) -> rsa.RSAPrivateKey:
    """The signing key lives on a volume so tokens survive restarts; generated on first start."""
    key_path = pathlib.Path(path)
    if key_path.exists():
        return serialization.load_pem_private_key(key_path.read_bytes(), password=None)  # type: ignore[return-value]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    os.chmod(key_path, 0o600)
    logger.info("Generated new JWT signing key", extra={"path": str(key_path)})
    return key


class TokenSigner:
    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        self.private_key = private_key
        der = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.kid = base64.urlsafe_b64encode(hashlib.sha256(der).digest()).decode()[:16]

    @property
    def public_key(self):
        return self.private_key.public_key()

    def jwks(self) -> dict:
        return {"keys": [public_jwk(self.public_key, self.kid)]}

    def access_token(self, *, user_id: str, role: str, email: str, ttl_seconds: int) -> str:
        return encode_token(self.private_key, self.kid, subject=user_id, role=role, email=email, ttl_seconds=ttl_seconds)
