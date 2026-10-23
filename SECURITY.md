# Security guide

This app handles salary figures, names and PAN numbers. Treat it like a bank login.

## What is protected now
| Risk | Protection |
|---|---|
| Strangers opening the site | Everything sits behind an admin sign-in. If no admin exists the app stays **locked** (it never falls back to "open"). |
| Password theft from the server | The password is never stored - only a salted **scrypt** hash. Secrets are protected in `.env` (owner-only permissions, git-ignored) instead of storing credentials in `config/admin.json`. |
| Password guessing | After 5 wrong attempts sign-in pauses (30 s, doubling up to 1 h). The pause is global and survives restarts, so opening new tabs does not help. Wrong user and wrong password give the same message and take the same time. |
| Stolen password | Optional **authenticator-app code** (TOTP). Each code works once (replay blocked). Strongly recommended. |
| Walk-away / shared computer | Auto sign-out after 20 idle minutes, hard limit 8 hours, **Sign out** button wipes the session and cached workbook. Refreshing the page also signs you out (deliberate). |
| Malicious Excel file | Size cap 10 MB, zip-bomb and odd-path checks, XML parsed with `defusedxml`, never executed or saved. |
| Injected text (names, firm name) | Escaped before display; PDF text was already escaped. |
| Logo upload | PNG/JPG only, 2 MB cap, pixel cap, re-encoded (metadata removed). |
| Salary PDFs left on a server | With `PAYSLIP_HOSTED=1` generated files are auto-deleted after 24 h (`PAYSLIP_PURGE_HOURS`). **Delete all generated payslips now** is always in the sidebar. |
| Secrets in git | `.gitignore` blocks `.env`, `*.env`, `output/`, `logs/`, `*.xlsx`, `*.pdf`, `admin.json`, `secrets.toml`. |
| Logs | Record only that a sign-in failed/succeeded - never passwords, names or amounts. |

## Before you push to GitHub
1. Make the repository **private**.
2. Copy this folder over your repo and run:
   `git rm -r --cached payslip_core/__pycache__ logs output config/admin.json 2>/dev/null; git add -A; git status`
   Check that no `.xlsx`, `.pdf`, `admin.json` or log file is listed.
3. Your earlier commit contains `.pyc` files and a log with your Windows paths (`C:\Users\...`, `D:\PayslipWebsite`).
   For a perfectly clean history create a fresh repo (`rm -rf .git; git init`) before the first push.

## Putting it online
The sign-in page is then the only lock, so:
- Use a **long unique password + authenticator code**. Run `python scripts/set_admin.py --print`.
- Do **not** upload `config/admin.json`. Put the three printed values in the host's *Secrets / Environment variables*:
  `PAYSLIP_ADMIN_USER`, `PAYSLIP_ADMIN_HASH`, `PAYSLIP_ADMIN_TOTP`. Also set `PAYSLIP_HOSTED=1`.
- Only serve over **HTTPS** (every normal host does; never plain http on the internet).
- Streamlit Community Cloud works without a credit card (repo must be connected to GitHub; use a private repo and the Secrets box).
  If the host complains about the address, remove `address = "127.0.0.1"` from `.streamlit/config.toml`.
- Safest option of all: keep running it on your own PC and reach it from your phone/laptop through a private
  network tool such as Tailscale (free, no card). Then it is never on the public internet.

### Be aware
A hosted copy means salary data passes through someone else's server while you work. The app does not save the
workbook and deletes PDFs automatically, but you are still trusting the host. If your policy requires payroll
to stay in-house, keep it on your own computer.

## Limits (honest list)
- A login screen cannot stop someone who already controls the server or your computer.
- Free hosts may restart and reset the lockout counter file; keep the password strong and 2FA on.
- If you lose your phone and the TOTP key, run `python scripts/set_admin.py` again on the server.
- Rotate the password if you ever shared it. Pre-existing payroll-logic test failures are listed in TEST_REPORT.md.
