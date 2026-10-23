"""Look & feel (black theme) and the admin sign-in screen.

Only system fonts are used and nothing is loaded from the internet, so the page never contacts a third party.
"""
from __future__ import annotations

import html
import re
import time
from typing import Optional

import streamlit as st

from . import auth
from . import config as cfg

ACCENT = "#16B29D"

# ------------------------------------------------------------------------------------------ escaping
def esc(text: object) -> str:
    """HTML-escape text that came from settings or from the uploaded workbook."""
    return html.escape(str(text), quote=True)


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~$&])")


def md_esc(text: object) -> str:
    """Make workbook text safe to show inside st.markdown (no links, images, HTML or formatting)."""
    return _MD_SPECIAL.sub(r"\\\1", str(text)).replace("\n", " ")


# ------------------------------------------------------------------------------------------ theme
CSS = """
<style>
:root{
  --bg:#000000; --surface:#09090A; --raised:#111113; --line:#222226; --line-soft:#17171A;
  --text:#ECECEE; --muted:#8B8B95; --accent:#16B29D; --accent-soft:rgba(22,178,157,.14);
  --danger:#F0616D; --warn:#E8B04A;
  --mono: ui-monospace, "SF Mono", "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas, monospace;
}
html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"]{ background:var(--bg) !important; color:var(--text); }
[data-testid="stHeader"]{ background:rgba(0,0,0,.72); backdrop-filter:blur(8px); border-bottom:1px solid var(--line-soft); }
[data-testid="stDecoration"]{ display:none; }
.block-container{ max-width:1240px; padding-top:4.6rem; padding-bottom:5rem; }
h1,h2,h3,h4{ letter-spacing:-.01em; }
p, li, label, [data-testid="stMarkdownContainer"]{ line-height:1.55; }
::selection{ background:var(--accent); color:#001; }
a{ color:var(--accent); }

/* keyboard focus must always be visible */
*:focus-visible{ outline:2px solid var(--accent) !important; outline-offset:2px; border-radius:6px; }

/* sidebar */
[data-testid="stSidebar"]{ background:var(--surface); border-right:1px solid var(--line); }
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{ padding-top:1.4rem; }

/* header block */
.ps-brand{ display:flex; align-items:center; gap:1.1rem; padding:0 0 1.1rem 0; border-bottom:1px solid var(--line); margin-bottom:.6rem; }
.ps-brand img{ height:56px; width:auto; border-radius:8px; background:#fff; padding:6px; }
.ps-title{ font-size:1.9rem; font-weight:700; line-height:1.1; letter-spacing:-.02em; }
.ps-sub{ color:var(--muted); font-size:.95rem; margin-top:.25rem; max-width:62ch; }

/* steps are a real sequence, so they are numbered */
.step-title{ display:flex; align-items:center; gap:.7rem; font-size:1.2rem; font-weight:650; margin:2.1rem 0 .55rem 0; }
.step{ flex:none; width:1.75rem; height:1.75rem; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
       font-weight:700; font-size:.9rem; color:#001; background:var(--accent); font-variant-numeric:tabular-nums; }

/* inputs */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div, [data-baseweb="textarea"],
[data-testid="stTextInputRootElement"], [data-testid="stNumberInputContainer"]{
  background:var(--raised) !important; border:1px solid #34343b !important; border-radius:10px !important; }
[data-baseweb="base-input"]{ border:0 !important; }
[data-baseweb="input"] input, [data-baseweb="base-input"] input{ background:transparent !important; color:var(--text) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-testid="stTextInputRootElement"]:focus-within{
  border-color:var(--accent) !important; box-shadow:0 0 0 3px var(--accent-soft); }
[data-testid="stFileUploaderDropzone"]{ background:var(--surface); border:1.5px dashed #34343a; border-radius:14px; padding:1.4rem; }
[data-testid="stFileUploaderDropzone"]:hover{ border-color:var(--accent); background:#0b1412; }

/* buttons */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button{
  border-radius:10px; border:1px solid var(--line); background:var(--raised); color:var(--text); font-weight:600;
  transition:border-color .15s, background .15s, transform .05s; }
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover{ border-color:var(--accent); color:#fff; }
.stButton > button:active, .stDownloadButton > button:active{ transform:translateY(1px); }
button[kind="primary"], button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"]{
  background:var(--accent) !important; border-color:var(--accent) !important; color:#00110e !important; }
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover{ filter:brightness(1.1); color:#00110e !important; }
button:disabled{ opacity:.45 !important; }

/* metrics */
[data-testid="stMetric"]{ background:var(--surface); border:1px solid var(--line); border-radius:14px; padding:.9rem 1.1rem; }
[data-testid="stMetricLabel"]{ color:var(--muted); }
[data-testid="stMetricValue"]{ font-variant-numeric:tabular-nums; font-weight:700; letter-spacing:-.01em; font-size:1.35rem; }
[data-testid="stMetricValue"] > div{ white-space:normal !important; overflow:visible !important; text-overflow:clip !important; }

/* tables - money lines up */
[data-testid="stDataFrame"], [data-testid="stDataEditor"]{ border:1px solid var(--line); border-radius:12px; overflow:hidden; }

/* expanders, tabs, alerts */
[data-testid="stExpander"]{ background:var(--surface); border:1px solid var(--line) !important; border-radius:12px; }
[data-testid="stExpander"] summary{ font-weight:600; }
[data-baseweb="tab-list"]{ gap:.3rem; border-bottom:1px solid var(--line); }
[data-baseweb="tab"]{ border-radius:8px 8px 0 0; }
[data-testid="stAlert"]{ border-radius:12px; border:1px solid var(--line); background:var(--surface); }
[data-testid="stForm"]{ border:1px solid var(--line); border-radius:14px; background:var(--surface); }
hr{ border-color:var(--line) !important; }
code{ background:var(--raised); color:#9be7dc; border-radius:6px; padding:.1em .4em; }
[data-testid="stCaptionContainer"]{ color:var(--muted); }

/* account chip in the sidebar */
.ps-chip{ display:flex; align-items:center; gap:.6rem; padding:.65rem .8rem; border:1px solid var(--line); border-radius:12px; background:var(--raised); margin-bottom:.6rem; }
.ps-dot{ width:.55rem; height:.55rem; border-radius:50%; background:var(--accent); box-shadow:0 0 0 4px var(--accent-soft); }
.ps-chip small{ color:var(--muted); display:block; line-height:1.2; }

@media (max-width: 700px){ .block-container{ padding-left:1rem; padding-right:1rem; } .ps-title{ font-size:1.5rem; } }
@media (prefers-reduced-motion: reduce){ *{ transition:none !important; animation:none !important; } }
</style>
"""

LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stToolbar"]{ display:none !important; }
[data-testid="stAppViewContainer"]{
  background: radial-gradient(900px 420px at 50% -8%, rgba(22,178,157,.16), transparent 70%), #000 !important; }
.block-container{ max-width:430px !important; padding-top:10vh !important; }
.ps-login-head{ text-align:center; margin-bottom:1.4rem; }
.ps-login-head img{ height:64px; width:auto; background:#fff; padding:8px; border-radius:14px; margin-bottom:1.1rem; }
.ps-login-head h1{ font-size:1.7rem; margin:0 0 .35rem 0; font-weight:700; }
.ps-login-head p{ color:var(--muted); margin:0; font-size:.95rem; }
.ps-login-foot{ text-align:center; color:var(--muted); font-size:.82rem; margin-top:1.2rem; }
</style>
"""


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def step(n: int, title: str) -> None:
    st.markdown(f'<div class="step-title"><span class="step">{int(n)}</span><span>{esc(title)}</span></div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------ logo as data URI
def _logo_data_uri() -> Optional[str]:
    import base64
    p = cfg.resolve_site_logo()
    if not p:
        return None
    try:
        if p.stat().st_size > 2_000_000:
            return None
        ext = "png" if p.suffix.lower() == ".png" else "jpeg"
        return f"data:image/{ext};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return None


def brand_header(firm_name: str) -> None:
    uri = _logo_data_uri()
    img = f'<img src="{uri}" alt="">' if uri else ""
    st.markdown(
        f'<div class="ps-brand">{img}<div><div class="ps-title">Payslip Manager</div>'
        f'<div class="ps-sub">{esc(firm_name)} - upload the salary workbook, review the figures, create PDF payslips.</div>'
        f'</div></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------------------------------ sign-in gate
def _setup_needed_screen() -> None:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown('<div class="ps-login-head"><h1>Admin account not set up</h1>'
                '<p>The app stays locked until you create the admin account.</p></div>', unsafe_allow_html=True)
    st.markdown("Run this once on the computer or server where the app is installed:")
    st.code("python scripts/set_admin.py", language="bash")
    st.caption("It asks for a username and a strong password, and can add an authenticator-app code. "
               "Then reload this page.")


def _login_screen(creds: auth.Credentials) -> None:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    uri = _logo_data_uri()
    img = f'<img src="{uri}" alt="">' if uri else ""
    st.markdown(f'<div class="ps-login-head">{img}<h1>Admin sign-in</h1>'
                f'<p>Payslip Manager holds salary data. Only the administrator can enter.</p></div>',
                unsafe_allow_html=True)
    wait = auth.lock_remaining()
    if wait:
        st.error(f"Too many failed attempts. Sign-in is paused for {auth._fmt_wait(wait)}.")
        st.caption("This pause protects the account from password guessing.")
        return
    if st.session_state.pop("_ps_timeout", False):
        st.info("You were signed out because the session was idle or too old. Sign in again to continue.")
    with st.form("admin_login", clear_on_submit=False):
        user = st.text_input("Username", autocomplete="username", max_chars=64)
        pw = st.text_input("Password", type="password", autocomplete="current-password", max_chars=256)
        code = ""
        if creds.totp_secret:
            code = st.text_input("Authenticator code", max_chars=7, placeholder="6 digits",
                                 autocomplete="one-time-code")
        go = st.form_submit_button("Sign in", type="primary", width="stretch")
    if go:
        ok, msg = auth.check_login(user, pw, code, creds)
        if ok:
            st.session_state[auth.SESSION_KEY] = auth.new_session()
            st.rerun()
        else:
            st.error(msg)
    st.markdown('<div class="ps-login-foot">Sessions end after '
                f'{auth.IDLE_TIMEOUT_S // 60} idle minutes.</div>', unsafe_allow_html=True)


def logout() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    try:
        st.cache_data.clear()
    except Exception:
        pass
    st.rerun()


def require_login() -> None:
    """Call right after set_page_config. Renders the sign-in page and stops the script unless signed in."""
    creds = auth.load_credentials()
    inject_theme()
    if creds is None:
        _setup_needed_screen()
        st.stop()
    state = st.session_state.get(auth.SESSION_KEY)
    now = time.time()
    if state and not auth.session_state_valid(state, now):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.session_state["_ps_timeout"] = True
        state = None
    if not auth.session_state_valid(state, now):
        _login_screen(creds)
        st.stop()
    state["last"] = now


@st.fragment(run_every="30s")
def _idle_watch() -> None:
    state = st.session_state.get(auth.SESSION_KEY)
    if state and not auth.session_state_valid(state):
        st.rerun()  # full rerun -> require_login() signs the user out


def sidebar_account() -> None:
    st.markdown(f'<div class="ps-chip"><span class="ps-dot"></span><div><b>Admin</b>'
                f'<small>Signed in - auto sign-out after {auth.IDLE_TIMEOUT_S // 60} min idle</small></div></div>',
                unsafe_allow_html=True)
    if st.button("Sign out", width="stretch", key="signout"):
        logout()
    _idle_watch()
