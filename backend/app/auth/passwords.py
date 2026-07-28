"""Argon2 password hashing (ADR 0007).

Separate from ``app.auth.tokens``: those are SHA-256 digests of high-entropy
random tokens the server itself minted, where a fast hash is correct. A
user-chosen password is low-entropy, so it needs a deliberately slow,
memory-hard hash instead.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError

# argon2-cffi's defaults track the library's current recommended parameters;
# tracking them is better than pinning numbers here that go stale.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash (self-describing: parameters and salt included)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return whether ``password`` matches ``password_hash``.

    Returns False rather than raising for any failure — including a stored hash
    argon2 can't parse at all, which must read as a failed login, not a 500.
    ``VerifyMismatchError`` is a ``VerificationError`` subclass, so the wrong
    password is covered by the first arm.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False
