# Test report (this version)

Run on Linux, Python 3.13, Streamlit 1.65, headless Chromium.

**Automated** (`python -m pytest tests`): 25 passed, 2 failed, 1 skipped.
- New `tests/test_auth.py` (12 tests): password hashing and rules, wrong user/password, lockout and growth, TOTP (incl. RFC 6238 vector and replay), session timeouts, fail-closed when no admin, private credentials file, escaping, safe purge.
- The 2 failures (`test_employee_specific_allowances`, `test_comment_parser_variants`) are in the **original** payroll logic and fail identically on the untouched upload (they were already in its `.pytest_cache`). I did not change payroll calculations. Please review them separately.

**Browser run (real app)**: page shows only the sign-in before login (verified the app content is absent from the HTML); wrong password rejected; correct password accepted; upload workbook -> confirm month -> review -> generate 5/5 payslips -> sign out returns to the sign-in; reload stays locked.

**Not tested**: 2FA in the browser (logic unit-tested), deployment on a real host, Windows batch files, Devanagari names (unsupported by the PDF font).
