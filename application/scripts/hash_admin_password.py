"""
Generate the bcrypt hash for ADMIN_PASSWORD_HASH.

Usage (from the application directory):
    python scripts/hash_admin_password.py

The password is read without echo and never printed. Copy the printed hash into
the ADMIN_PASSWORD_HASH variable on Railway, and set ADMIN_USERNAME as well.
Use a long, unique password (for example, five or more random words).
"""
import getpass
import sys

import bcrypt

MIN_LENGTH = 16


def main() -> int:
    password = getpass.getpass("New admin password: ")
    if len(password) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    if len(password.encode("utf-8")) > 72:
        print("Password must be at most 72 bytes (bcrypt limit).", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    print(bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
