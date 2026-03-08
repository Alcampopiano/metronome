from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import sqlite3
import os
import hmac
import pyotp

app = FastAPI(title="Metronome App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth config — set all of these as environment variables before deploying!
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
MFA_SECRET = os.environ.get("MFA_SECRET")  # Generate with: pyotp.random_base32()

if not all([SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, MFA_SECRET]):
    raise RuntimeError("SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD and MFA_SECRET must all be set")

COOKIE_NAME = "metronome_session"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours
MFA_PENDING_COOKIE = "metronome_mfa_pending"
MFA_PENDING_MAX_AGE = 60 * 5  # 5 minutes to enter MFA code

totp = pyotp.TOTP(MFA_SECRET)
serializer = URLSafeTimedSerializer(SECRET_KEY)

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def create_session_cookie(username: str) -> str:
    return serializer.dumps({"user": username})

def verify_session_cookie(token: str) -> Optional[str]:
    try:
        data = serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None

def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_session_cookie(token)

def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user

def check_credentials(username: str, password: str) -> bool:
    username_ok = hmac.compare_digest(username, ADMIN_USERNAME)
    password_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return username_ok and password_ok

def create_mfa_pending_cookie(username: str) -> str:
    """Short-lived cookie: password verified, MFA step still pending."""
    return serializer.dumps({"mfa_pending": username})

def verify_mfa_pending_cookie(token: str) -> Optional[str]:
    try:
        data = serializer.loads(token, max_age=MFA_PENDING_MAX_AGE)
        return data.get("mfa_pending")
    except (BadSignature, SignatureExpired):
        return None

# ---------------------------------------------------------------------------
# Shared page styles (used in login and MFA pages)
# ---------------------------------------------------------------------------

PAGE_STYLES = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0e0e0e; --surface: #161616; --border: #272727;
    --accent: #e8c97d; --text: #f0ede6; --text-muted: #5a5a5a; --red: #e07070;
  }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'DM Mono', monospace;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
  }
  .card {
    width: 360px; max-width: 94vw;
    background: var(--surface); border: 1px solid var(--border);
    padding: 40px 32px; display: flex; flex-direction: column; gap: 28px;
  }
  h1 { font-family: 'Instrument Serif', serif; font-style: italic; font-size: 1.9rem; color: var(--text); }
  .field { display: flex; flex-direction: column; gap: 6px; }
  .field label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-muted); }
  .field input {
    background: var(--bg); border: 1px solid var(--border);
    color: var(--text); font-family: 'DM Mono', monospace; font-size: 0.9rem;
    padding: 12px 14px; outline: none; width: 100%; transition: border-color 0.2s;
  }
  .field input:focus { border-color: #7a6b3a; }
  button {
    background: var(--accent); color: #0e0e0e; border: none;
    font-family: 'DM Mono', monospace; font-size: 0.82rem; font-weight: 500;
    letter-spacing: 0.08em; text-transform: uppercase;
    padding: 14px; cursor: pointer; transition: background 0.2s; width: 100%;
  }
  button:hover { background: #f0d890; }
  .error { color: var(--red); font-size: 0.78rem; letter-spacing: 0.04em; }
  .hint { font-size: 0.72rem; color: var(--text-muted); line-height: 1.5; }
"""

FONT_LINK = '<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">'

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = os.path.join(os.path.dirname(__file__), "songs.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            bpm INTEGER NOT NULL,
            fade_out_seconds INTEGER NOT NULL DEFAULT 30
        )
    """)
    count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    if count == 0:
        seeds = [
            ("Bohemian Rhapsody", 72, 45),
            ("Stayin' Alive", 104, 30),
            ("Sweet Home Alabama", 96, 40),
            ("Hotel California", 75, 60),
            ("Billie Jean", 117, 35),
            ("Yesterday", 96, 50),
            ("Roxanne", 132, 25),
            ("Wonderwall", 87, 40),
        ]
        conn.executemany("INSERT INTO songs (title, bpm, fade_out_seconds) VALUES (?, ?, ?)", seeds)
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SongCreate(BaseModel):
    title: str
    bpm: int
    fade_out_seconds: int = 30

class SongUpdate(BaseModel):
    title: Optional[str] = None
    bpm: Optional[int] = None
    fade_out_seconds: Optional[int] = None

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if get_current_user(request):
        return RedirectResponse("/admin", status_code=302)
    error_html = f'<p class="error">{error}</p>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login — Metronome</title>{FONT_LINK}
<style>{PAGE_STYLES}</style>
</head>
<body>
<div class="card">
  <h1>Metronome</h1>
  {error_html}
  <form method="post" action="/login">
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="field">
        <label>Username</label>
        <input type="text" name="username" autocomplete="username" required autofocus />
      </div>
      <div class="field">
        <label>Password</label>
        <input type="password" name="password" autocomplete="current-password" required />
      </div>
      <button type="submit" style="margin-top:8px">Continue →</button>
    </div>
  </form>
</div>
</body></html>""")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not check_credentials(username, password):
        return RedirectResponse("/login?error=Invalid+username+or+password", status_code=302)

    # Password correct — set short-lived pending cookie and go to MFA step
    pending_token = create_mfa_pending_cookie(username)
    response = RedirectResponse("/mfa", status_code=302)
    response.set_cookie(
        key=MFA_PENDING_COOKIE,
        value=pending_token,
        httponly=True,
        secure=False,   # Set to True in production
        samesite="lax",
        max_age=MFA_PENDING_MAX_AGE,
    )
    return response


@app.get("/mfa", response_class=HTMLResponse)
def mfa_page(request: Request, error: str = ""):
    # Must have a valid pending cookie to reach this page
    pending_token = request.cookies.get(MFA_PENDING_COOKIE)
    if not pending_token or not verify_mfa_pending_cookie(pending_token):
        return RedirectResponse("/login", status_code=302)

    error_html = f'<p class="error">{error}</p>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Two-Factor Auth — Metronome</title>{FONT_LINK}
<style>{PAGE_STYLES}</style>
</head>
<body>
<div class="card">
  <h1>Metronome</h1>
  {error_html}
  <p class="hint">Enter the 6-digit code from your authenticator app.</p>
  <form method="post" action="/mfa">
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="field">
        <label>Authenticator Code</label>
        <input type="text" name="code" inputmode="numeric" pattern="[0-9]*"
               maxlength="6" autocomplete="one-time-code" required autofocus
               style="font-size:1.4rem;letter-spacing:0.3em;text-align:center" />
      </div>
      <button type="submit" style="margin-top:8px">Sign in →</button>
    </div>
  </form>
</div>
</body></html>""")


@app.post("/mfa")
def mfa_verify(request: Request, code: str = Form(...)):
    pending_token = request.cookies.get(MFA_PENDING_COOKIE)
    if not pending_token:
        return RedirectResponse("/login", status_code=302)

    username = verify_mfa_pending_cookie(pending_token)
    if not username:
        return RedirectResponse("/login?error=Session+expired,+please+sign+in+again", status_code=302)

    if not totp.verify(code.strip(), valid_window=1):
        return RedirectResponse("/mfa?error=Invalid+code,+please+try+again", status_code=302)

    # MFA passed — issue full session cookie and clear pending cookie
    session_token = create_session_cookie(username)
    response = RedirectResponse("/admin", status_code=302)
    response.delete_cookie(MFA_PENDING_COOKIE)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=False,   # Set to True in production
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
    )
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(MFA_PENDING_COOKIE)
    return response

# ---------------------------------------------------------------------------
# Public song API
# ---------------------------------------------------------------------------

@app.get("/api/songs")
def list_songs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM songs ORDER BY title").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/songs/search")
def search_songs(q: str = ""):
    conn = get_db()
    if not q.strip():
        rows = conn.execute("SELECT * FROM songs ORDER BY title").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM songs WHERE LOWER(title) LIKE ? ORDER BY title",
            (f"%{q.lower()}%",)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/songs/{song_id}")
def get_song(song_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Song not found")
    return dict(row)

# ---------------------------------------------------------------------------
# Protected admin API
# ---------------------------------------------------------------------------

@app.post("/api/songs", status_code=201)
def create_song(song: SongCreate, user: str = Depends(require_auth)):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO songs (title, bpm, fade_out_seconds) VALUES (?, ?, ?)",
        (song.title, song.bpm, song.fade_out_seconds)
    )
    conn.commit()
    new_id = cur.lastrowid
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return dict(row)

@app.put("/api/songs/{song_id}")
def update_song(song_id: int, song: SongUpdate, user: str = Depends(require_auth)):
    conn = get_db()
    existing = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Song not found")
    updated = dict(existing)
    if song.title is not None:
        updated["title"] = song.title
    if song.bpm is not None:
        updated["bpm"] = song.bpm
    if song.fade_out_seconds is not None:
        updated["fade_out_seconds"] = song.fade_out_seconds
    conn.execute(
        "UPDATE songs SET title=?, bpm=?, fade_out_seconds=? WHERE id=?",
        (updated["title"], updated["bpm"], updated["fade_out_seconds"], song_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/songs/{song_id}", status_code=204)
def delete_song(song_id: int, user: str = Depends(require_auth)):
    conn = get_db()
    existing = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Song not found")
    conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")

@app.get("/admin")
def serve_admin(user: str = Depends(require_auth)):
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))