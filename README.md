# Payslip Manager

A website that turns your monthly Excel salary workbook into one PDF payslip per employee
(plus one combined PDF and a ZIP). It has a **black theme** and an **admin-only sign-in**
(username + password + optional authenticator code - no Google account needed).
There is no telemetry, and the uploaded workbook is only kept in memory (never saved or changed).
Read **SECURITY.md** before putting it online.

## First time: create the admin account
- Windows: double-click `setup_admin.bat` (or run `python scripts/set_admin.py`)
- Linux/Mac: `python3 scripts/set_admin.py` (`./start.sh` asks for it automatically on first start)

It asks for a username and a strong password (12+ characters) and shows a QR code for an authenticator app.
Until an admin exists, the app shows nothing but a "not set up" page.

For local and hosted deployments, credentials are saved securely in `.env` (git-ignored and protected)
instead of storing credentials in `config/admin.json`: `PAYSLIP_ADMIN_USER`, `PAYSLIP_ADMIN_HASH`, and optionally
`PAYSLIP_ADMIN_TOTP`. Run `python scripts/set_admin.py --print` to generate or print the values. Environment
variables / `.env` take precedence and keep your secrets safe.

## Start (Ubuntu / Linux)
1. Extract the ZIP (right-click -> Extract Here), open a terminal in the extracted folder `PayslipWebsite`.
2. Run: `./start.sh`
   - First start only: it creates a private Python environment and installs the libraries (internet needed once, a few minutes).
   - Needs Python 3.10+. If it asks, run `sudo apt install python3 python3-venv python3-pip` and start again.
   - Other Linux distributions: install python3, python3-venv and pip with your package manager, then `./start.sh`.
3. The browser opens at **http://127.0.0.1:8501** (if not, open that address yourself).
   If port 8501 is busy it uses the next free port and prints it.
4. To close: run `./stop.sh`. To reopen later: `./start.sh` again (safe to repeat).
   Optional: `./install_desktop_shortcut.sh` adds a "Payslip Manager" entry to your applications menu.

## Start (Windows)
Double-click `start_windows.bat` (needs Python 3.10+ and `pip install -r requirements.txt` once), then open http://127.0.0.1:8501 and sign in.

## Monthly use
1. **Upload** your .xlsx workbook (step 1).
2. **Worksheet and month** (step 2): the month is pre-filled from the sheet name (e.g. "bhadra 8384" -> Bhadra 2083). Check it and tick the confirmation box. Bikram Sambat months are kept as BS; nothing is converted to English dates.
3. **Review** (step 4): see every employee's income, deductions, net salary, paid-leave comments and any warnings.
   - Employees with a red error must be ticked *Reviewed* (or unticked *Include*) before PDFs can be made.
   - *Optional corrections* lets you split a paid-leave line (e.g. into Earned Leave / Restricted Leave) or add a line by hand.
4. **Create** (step 5): *Review summary & generate* -> *Confirm and create PDFs* (or *Go back*).
5. **Download** the combined PDF, the ZIP, or each person's PDF. Use *Open output folder* to see the files.

## Where files are saved
```
output/2083-05/individual/Anish_Bhandari_Payslip_2083-05.pdf
output/2083-05/combined/All_Payslips_2083-05.pdf
output/2083-05/payslips.zip
```
If the month folder already exists you choose: keep the old files (new run goes to `2083-05_v2`) or replace same-named files.
Older month folders are never deleted. Errors are logged (without salary figures) in `logs/`.

## How the payslip is built
- Only components that have a non-zero amount for that employee are printed (blank or 0 = not shown).
- Income on the left, deductions on the right. Net = Total Income - Total Deductions, every line counted once.
- Paid leave: the amount comes from the *Paid leave* cell; the cell comment gives the names. If the comment itself has
  amounts ("Earned Leave: Rs. 500") and they match the cell, they are printed as separate lines (counted once).
- Each employee's result is compared with the workbook's own *Total Amount* and *PayCheque*; differences are flagged, never silently fixed.
- Firm name, address, logo and options are in the sidebar and are remembered (`config/settings.json`).
- Column roles (which column is an earning/deduction) can be changed in step 3 if your workbook changes.

## Limits
- Names must be in English letters (Devanagari cannot be printed by the PDF font; the app flags it).
- `.xls` files must be re-saved as `.xlsx`.
- If a workbook has formulas without stored results, the app recalculates with LibreOffice when it is installed; otherwise it flags those cells.
