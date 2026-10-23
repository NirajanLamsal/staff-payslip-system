#!/usr/bin/env python3
"""Create or change the admin account for Payslip Manager.

    python scripts/set_admin.py            # saves config/admin.json (kept out of git)
    python scripts/set_admin.py --print    # also prints values for hosting 'Secrets' / environment variables

The password is never saved - only a salted scrypt hash.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from payslip_core import auth  # noqa: E402


def ask_password() -> str:
    while True:
        pw = getpass.getpass("New password (typing is hidden): ")
        problem = auth.password_problem(pw)
        if problem:
            print("  ->", problem)
            continue
        if getpass.getpass("Repeat password: ") != pw:
            print("  -> The two passwords differ. Try again.")
            continue
        return pw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the values to paste into hosting secrets / environment variables")
    ap.add_argument("--no-2fa", action="store_true", help="skip the authenticator-app code (not recommended)")
    args = ap.parse_args()

    print("Payslip Manager - admin account\n")
    user = input("Admin username: ").strip()
    if len(user) < 3:
        print("The username needs at least 3 characters.")
        return 1
    pw = ask_password()
    totp = "" if args.no_2fa else auth.new_totp_secret()
    creds = auth.Credentials(user, auth.hash_password(pw), totp)
    path = auth.save_credentials_file(creds)
    auth.STATE_FILE.unlink(missing_ok=True)  # clear any old lockout
    print(f"\nSaved to {path} (owner-only file, ignored by git).")

    if totp:
        uri = auth.otpauth_uri(totp, user)
        print("\nTwo-step sign-in is ON. Add this account to an authenticator app "
              "(Google Authenticator, Microsoft Authenticator, Aegis, 2FAS, ...):")
        try:
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(uri)
            qr.print_ascii(invert=True)
        except Exception:
            print("  (install 'qrcode' to see a QR code here)")
        print(f"\n  Or type this key in manually: {totp}\n  (time-based, 6 digits, 30 seconds)")
        print("  Keep a copy of the key somewhere safe: it is the only way to rebuild the code generator "
              "if you lose your phone.")

    if args.show:
        print("\n--- For hosting (Streamlit Cloud 'Secrets' uses this TOML form) ---")
        print(f'PAYSLIP_ADMIN_USER = "{user}"')
        print(f'PAYSLIP_ADMIN_HASH = "{creds.password_hash}"')
        if totp:
            print(f'PAYSLIP_ADMIN_TOTP = "{totp}"')
        print("--- Never commit these lines to git. ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
