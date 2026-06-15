# AI File Organizer

A local, open-source, AI-powered file organization utility for macOS. Clone it, drop in your Gemini API key, and run it instantly — no cloud storage, no subscriptions, no data leaves your machine.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Powered by Gemini](https://img.shields.io/badge/powered%20by-Gemini%202.5-orange.svg)

---

## Features

- **Semantic AI Categorization** — instead of sorting by file extension, Gemini reads your filenames and groups them into logical contextual categories (e.g. "Project Invoices", "Travel Photos", "Research Papers").
- **Smart AI Renaming** — reads the actual content of your files (PDF first page, Word document paragraphs, plain text, source code) and uses Gemini Vision for images to suggest clean, descriptive filenames like `q3-2024-revenue-report.pdf` instead of `scan_final_v3_REAL.pdf`.
- **Two-step interactive workflow** — always preview before committing. A confirmation modal guards the organize action; the rename step shows an editable table so you can tweak any suggestion before applying.
- **100% local** — the FastAPI backend runs on `localhost:8000`. Only filenames/content are sent to the Gemini API; nothing is stored externally.
- **Safety guardrails** — operations on `/`, `/System`, `/Applications`, `/Library`, and other critical macOS paths are blocked.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · Uvicorn |
| AI | Google Gemini 2.5 Flash (Structured Outputs + Vision) |
| Frontend | Single-file HTML · Tailwind CSS (CDN) · Vanilla JS |
| File parsing | pypdf · python-docx |

---

## Quick Start

### 1. Prerequisites

- Python 3.10 or newer
- A free Gemini API key → [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

### 2. Clone the repo

```bash
git clone https://github.com/uzairahm290/AI-File-Organizer.git
cd AI-File-Organizer
```

### 3. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Set your Gemini API key

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_api_key_here
```

Or export it in your shell for the current session:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

### 5. Start the backend server

```bash
uvicorn main:app --reload --port 8000
```

### 6. Open the UI

Double-click `index.html` or run:

```bash
open index.html
```

The **Server Online** indicator in the top-right will turn green. You're ready to go.

---

## Usage

### Organize into folders

1. Enter an absolute folder path (e.g. `~/Downloads`)
2. Click **Scan** to preview all detected files
3. Click **Organize with AI** and confirm the modal
4. Gemini groups your files into named subfolders and moves them — the UI shows a full breakdown

### Smart Rename

1. Scan a folder as above
2. Click **Smart Rename with AI**
3. The backend reads each file's content; Gemini suggests clean, descriptive names
4. An editable preview table appears — tweak any name, uncheck files to skip
5. Click **Apply Selected Renames** to commit

---

## Project Structure

```
AI-File-Organizer/
├── main.py           # FastAPI backend — all endpoints, Gemini calls, file operations
├── index.html        # Single-file frontend dashboard
├── requirements.txt  # Python dependencies
├── .env.example      # API key template (copy to .env)
└── .gitignore
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server liveness check |
| `POST` | `/api/scan` | List visible files in a directory |
| `POST` | `/api/organize` | AI categorize + move files into subfolders |
| `POST` | `/api/rename-preview` | Read file content, return AI rename suggestions |
| `POST` | `/api/rename-apply` | Apply confirmed renames |

---

## Security

- `.env` is in `.gitignore` — your API key is never committed
- Blocked paths: `/`, `/System`, `/Applications`, `/Library`, `/usr`, `/bin`, `/sbin`, `/etc`
- All file operations are local; only filenames/text snippets reach the Gemini API

---

## License

MIT — free to use, modify, and distribute.
