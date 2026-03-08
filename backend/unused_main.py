from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os

app = FastAPI(title="Metronome App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "songs.db")

# --- DB Setup ---

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
    # Seed some sample songs if empty
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

# --- Models ---

class SongCreate(BaseModel):
    title: str
    bpm: int
    fade_out_seconds: int = 30

class SongUpdate(BaseModel):
    title: Optional[str] = None
    bpm: Optional[int] = None
    fade_out_seconds: Optional[int] = None

# --- Song Routes ---

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
        # Simple fuzzy: match each character sequence as substring, scored by relevance
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

@app.post("/api/songs", status_code=201)
def create_song(song: SongCreate):
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
def update_song(song_id: int, song: SongUpdate):
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
def delete_song(song_id: int):
    conn = get_db()
    existing = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Song not found")
    conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
    conn.commit()
    conn.close()

# --- Serve Frontend ---

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")

@app.get("/admin", response_class=FileResponse)
def serve_admin():
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

@app.get("/", response_class=FileResponse)
def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))
