"""Administrator CLI for provisioning and maintaining EYRES accounts."""

import argparse
import getpass

from app_core.rbac import ROLES
from db import Database
from app_core.audit import record_audit_event


def main():
    parser = argparse.ArgumentParser(description="EYRES managed user administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("username")
    create.add_argument("--email", default="")
    create.add_argument("--role", choices=ROLES, required=True)
    sub.add_parser("list")
    role = sub.add_parser("set-role")
    role.add_argument("username")
    role.add_argument("role", choices=ROLES)
    for command in ("enable", "disable"):
        item = sub.add_parser(command)
        item.add_argument("username")
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    args = parser.parse_args()
    db = Database()
    if args.command == "create":
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match")
        db.create_managed_user(args.username, password, args.email, args.role)
        record_audit_event("user_created", actor="administrator-cli",
                           details={"target_user": args.username, "role": args.role})
        print("User created")
    elif args.command == "list":
        for user in db.list_users():
            print(f"{user.get('username')}\t{user.get('role', 'operator')}\t"
                  f"{'active' if user.get('active', True) else 'disabled'}")
    elif args.command == "set-role":
        db.set_user_role(args.username, args.role)
        record_audit_event("user_role_changed", actor="administrator-cli",
                           details={"target_user": args.username, "role": args.role})
        print("Role updated")
    elif args.command in ("enable", "disable"):
        db.set_user_active(args.username, args.command == "enable")
        record_audit_event("user_status_changed", actor="administrator-cli",
                           details={"target_user": args.username, "active": args.command == "enable"})
        print("User status updated")
    else:
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match")
        db.admin_reset_password(args.username, password)
        record_audit_event("password_reset", actor="administrator-cli",
                           details={"target_user": args.username})
        print("Password reset and account lockout cleared")


if __name__ == "__main__":
    main()
