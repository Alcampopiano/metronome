# Metronome App

A web-based metronome with song library, fuzzy search, and auto fade-out.

## Project Structure

```
metronome/
├── backend/
│   └── main.py          # FastAPI app + SQLite database
├── frontend/
│   ├── index.html       # Main metronome page
│   └── admin.html       # CRUD admin page
├── requirements.txt
└── README.md
```

## Setup & Run

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. Open in browser

- **Metronome**: http://localhost:8000
- **Admin**: http://localhost:8000/admin

## Features

- **Search**: Fuzzy search box to find songs by title
- **Metronome**: Visual pendulum, beat indicators, and audio click
- **Fade Out**: Each song has a configurable fade-out duration — the metronome gradually fades after that many seconds
- **Restart**: Clicking Play again restarts the metronome and resets the fade-out timer
- **Admin CRUD**: Add, edit, and delete songs with title, BPM, and fade-out time

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/songs | List all songs |
| GET | /api/songs/search?q= | Search songs by title |
| GET | /api/songs/{id} | Get one song |
| POST | /api/songs | Create a song |
| PUT | /api/songs/{id} | Update a song |
| DELETE | /api/songs/{id} | Delete a song |

## Database

SQLite database (`songs.db`) is created automatically in the `backend/` folder on first run, pre-seeded with 8 sample songs.