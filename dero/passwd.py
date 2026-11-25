"""Create a users-file line:  python -m dero.passwd [--file users.txt] alice --role admin"""
import argparse
import getpass
import re
import sys

from werkzeug.security import generate_password_hash

USERNAME_RE = re.compile(r"[A-Za-z0-9._@-]{1,64}")


def make_line(username: str, role: str, password: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Username may contain letters, digits and . _ @ - (max 64).")
    if role not in ("admin", "user"):
        raise ValueError("Role must be 'admin' or 'user'.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return f"{username}:{role}:{generate_password_hash(password)}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dero.passwd", description=__doc__)
    ap.add_argument("username")
    ap.add_argument("--role", choices=["admin", "user"], default="user")
    ap.add_argument("--file", help="append the line to this users file instead of printing it")
    ap.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    args = ap.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
    try:
        line = make_line(args.username, args.role, password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.file:
        with open(args.file, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(f"Added {args.username} ({args.role}) to {args.file}. A later line for the same user overrides an earlier one.")
    else:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
