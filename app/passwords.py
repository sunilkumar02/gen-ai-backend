from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash("authentication timing check")


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        matches = password_hasher.verify(password, stored_hash or dummy_hash)
        return bool(stored_hash) and matches
    except (UnknownHashError, ValueError):
        return False
