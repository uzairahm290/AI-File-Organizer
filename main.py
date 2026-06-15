import json
import os
import shutil
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from google import genai
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# App & CORS
# ---------------------------------------------------------------------------

app = FastAPI(title="AI File Organizer", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Gemini client — lazy singleton
# ---------------------------------------------------------------------------

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail=(
                    "GEMINI_API_KEY is not set. "
                    "Export it in your shell: export GEMINI_API_KEY='your_key' "
                    "or add it to a .env file in the project directory."
                ),
            )
        _client = genai.Client(api_key=api_key)
    return _client


def call_gemini_with_retry(contents, response_schema):
    """Shared Gemini caller with exponential backoff on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            return get_client().models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.2,
                ),
            )
        except Exception as exc:
            last_exc = exc
            err = str(exc)
            if "503" in err or "UNAVAILABLE" in err or "429" in err:
                time.sleep(2 ** attempt)
                continue
            break
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

BLOCKED_PATHS = {"/", "/System", "/Applications", "/Library", "/usr", "/bin", "/sbin", "/etc"}


def resolve_and_validate(raw_path: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw_path.strip()))
    path = Path(expanded).resolve()

    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

    path_str = str(path)
    for blocked in BLOCKED_PATHS:
        if path_str == blocked or path_str.startswith(blocked + "/"):
            raise HTTPException(
                status_code=403,
                detail=f"Operations on '{blocked}' are blocked for safety.",
            )

    return path


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

HIDDEN_PREFIXES = (".", "~$")
HIDDEN_NAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}

IMAGE_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml", ".xml",
    ".html", ".css", ".js", ".ts", ".py", ".rb", ".go", ".java",
    ".swift", ".kt", ".rs", ".c", ".cpp", ".h", ".sh", ".sql", ".rtf",
}

MAX_SNIPPET_CHARS = 900
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_IMAGES_PER_BATCH = 8


def collect_files(directory: Path) -> List[str]:
    files = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if name in HIDDEN_NAMES:
            continue
        if any(name.startswith(p) for p in HIDDEN_PREFIXES):
            continue
        files.append(name)
    return files


def extract_file_snippet(path: Path) -> tuple[str, str]:
    """Return (text_snippet, label) for a file. Returns ('', 'image') for images."""
    ext = path.suffix.lower()

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = reader.pages[0].extract_text() or "" if reader.pages else ""
            return text[:MAX_SNIPPET_CHARS].strip(), "PDF first page"
        except Exception:
            return "", "PDF"

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs[:20] if p.text.strip())
            return text[:MAX_SNIPPET_CHARS].strip(), "Word document"
        except Exception:
            return "", "Word document"

    if ext in TEXT_EXTENSIONS:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(MAX_SNIPPET_CHARS).strip(), "text file"
        except Exception:
            return "", "text file"

    if ext in IMAGE_MIME_TYPES:
        return "", "image"

    return "", "unknown"


# ---------------------------------------------------------------------------
# Pydantic schemas — organize
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def path_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


class ScanResponse(BaseModel):
    resolved_path: str
    files: List[str]
    total: int


class OrganizeRequest(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def path_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


class CategoryItem(BaseModel):
    category: str
    files: List[str]


class OrganizationPlan(BaseModel):
    categories: List[CategoryItem]


class MoveResult(BaseModel):
    category: str
    folder: str
    files: List[str]


class OrganizeResponse(BaseModel):
    resolved_path: str
    results: List[MoveResult]
    total_moved: int


# ---------------------------------------------------------------------------
# Pydantic schemas — rename
# ---------------------------------------------------------------------------

class FileSuggestion(BaseModel):
    original: str
    suggested: str
    reason: str


class RenamePlan(BaseModel):
    suggestions: List[FileSuggestion]


class RenamePreviewResponse(BaseModel):
    resolved_path: str
    suggestions: List[FileSuggestion]


class ApplyRenameItem(BaseModel):
    original: str
    new_name: str


class ApplyRenameRequest(BaseModel):
    path: str
    renames: List[ApplyRenameItem]

    @field_validator("path")
    @classmethod
    def path_must_be_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("path must not be empty")
        return v


class RenameResult(BaseModel):
    original: str
    new_name: str
    status: str


class ApplyRenameResponse(BaseModel):
    resolved_path: str
    renamed: int
    results: List[RenameResult]


# ---------------------------------------------------------------------------
# Endpoints — scan
# ---------------------------------------------------------------------------

@app.post("/api/scan", response_model=ScanResponse)
async def scan_directory(request: ScanRequest) -> ScanResponse:
    directory = resolve_and_validate(request.path)
    files = collect_files(directory)
    if not files:
        raise HTTPException(status_code=404, detail="No visible files found in the directory.")
    return ScanResponse(resolved_path=str(directory), files=files, total=len(files))


# ---------------------------------------------------------------------------
# Endpoints — organize (move into categorised subfolders)
# ---------------------------------------------------------------------------

def _build_organize_prompt(filenames: List[str]) -> str:
    file_list = "\n".join(f"- {f}" for f in filenames)
    return (
        "You are a file organization assistant. Analyze the following list of filenames "
        "and group them into logical, descriptive semantic categories. "
        "Each category name should be concise (2-4 words, Title Case, filesystem-safe — no slashes or special chars). "
        "Every filename must appear in exactly one category. "
        "Do not invent filenames that are not in the list.\n\n"
        f"Files to categorize:\n{file_list}\n\n"
        "Return a JSON object with a 'categories' array. Each element must have "
        "'category' (string) and 'files' (array of strings)."
    )


@app.post("/api/organize", response_model=OrganizeResponse)
async def organize_directory(request: OrganizeRequest) -> OrganizeResponse:
    directory = resolve_and_validate(request.path)
    filenames = collect_files(directory)
    if not filenames:
        raise HTTPException(status_code=404, detail="No visible files found in the directory.")

    try:
        response = call_gemini_with_retry(_build_organize_prompt(filenames), OrganizationPlan)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}")

    try:
        plan: OrganizationPlan = response.parsed
        if plan is None:
            raise ValueError("parsed response is None")
    except Exception:
        try:
            plan = OrganizationPlan.model_validate(json.loads(response.text))
        except Exception as parse_exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to parse Gemini response: {parse_exc}. Raw: {response.text[:500]}",
            )

    existing_files = set(filenames)
    results: List[MoveResult] = []
    total_moved = 0

    for item in plan.categories:
        safe_folder = (
            item.category.strip()
            .replace("/", "-").replace("\\", "-").replace(":", "-")
        )
        dest_folder = directory / safe_folder
        os.makedirs(dest_folder, exist_ok=True)

        moved: List[str] = []
        for filename in item.files:
            if filename not in existing_files:
                continue
            src = directory / filename
            dst = dest_folder / filename
            if src.exists():
                shutil.move(str(src), str(dst))
                moved.append(filename)
                total_moved += 1

        if moved:
            results.append(MoveResult(category=item.category, folder=safe_folder, files=moved))

    return OrganizeResponse(resolved_path=str(directory), results=results, total_moved=total_moved)


# ---------------------------------------------------------------------------
# Endpoints — rename (read content → AI suggest → apply)
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    return name.strip().replace("/", "-").replace("\\", "-").replace(":", "-")


@app.post("/api/rename-preview", response_model=RenamePreviewResponse)
async def rename_preview(request: ScanRequest) -> RenamePreviewResponse:
    """
    Read file contents (first page for PDFs, first paragraphs for DOCX,
    vision for images) then ask Gemini to suggest clean descriptive filenames.
    """
    directory = resolve_and_validate(request.path)
    filenames = collect_files(directory)
    if not filenames:
        raise HTTPException(status_code=404, detail="No visible files found.")

    image_files = [f for f in filenames if Path(f).suffix.lower() in IMAGE_MIME_TYPES]
    text_files = [f for f in filenames if f not in set(image_files)]

    all_suggestions: List[FileSuggestion] = []

    # ── Batch call for all non-image files ──────────────────────────────────
    if text_files:
        entries: List[str] = []
        for name in text_files:
            snippet, label = extract_file_snippet(directory / name)
            entry = f"File: {name}"
            if snippet:
                entry += f"\n{label} content:\n{snippet}"
            entries.append(entry)

        prompt = (
            "You are a file renaming expert. For each file below, suggest a clean, descriptive filename.\n\n"
            "Rules:\n"
            "- Use the file CONTENT as the primary signal — not the original filename\n"
            "- Lowercase only, hyphens instead of spaces, no special characters except hyphens and dots\n"
            "- Preserve the EXACT original file extension\n"
            "- Maximum 60 characters total (including extension)\n"
            "- Be specific: 'q3-2024-revenue-report.pdf' beats 'report.pdf'\n"
            "- If no content is available, clean up and improve the existing filename\n"
            "- The 'original' field must exactly match the filename as given\n\n"
            + "\n\n".join(f"---\n{e}" for e in entries)
            + "\n\nReturn JSON with a 'suggestions' array."
        )

        try:
            resp = call_gemini_with_retry(prompt, RenamePlan)
            plan: RenamePlan = resp.parsed or RenamePlan(suggestions=[])
            known = set(text_files)
            for s in plan.suggestions:
                if s.original in known:
                    all_suggestions.append(s)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}")

    # ── Individual vision call per image (capped at MAX_IMAGES_PER_BATCH) ──
    for name in image_files[:MAX_IMAGES_PER_BATCH]:
        file_path = directory / name
        ext = Path(name).suffix.lower()
        mime = IMAGE_MIME_TYPES.get(ext, "image/jpeg")

        try:
            if file_path.stat().st_size > MAX_IMAGE_BYTES:
                all_suggestions.append(FileSuggestion(
                    original=name, suggested=name,
                    reason="Image exceeds 5 MB; keeping original name",
                ))
                continue

            image_bytes = file_path.read_bytes()
            resp = call_gemini_with_retry(
                [
                    types.Part.from_bytes(data=image_bytes, mime_type=mime),
                    (
                        f"This image file is currently named '{name}'. "
                        "Describe what you see and suggest a clean, descriptive filename. "
                        f"Rules: lowercase, hyphens, keep '{ext}' extension exactly, max 50 chars, be specific. "
                        f"The 'original' field must be exactly: {name}"
                    ),
                ],
                FileSuggestion,
            )
            if resp.parsed:
                all_suggestions.append(resp.parsed)
            else:
                all_suggestions.append(FileSuggestion(
                    original=name, suggested=name, reason="No suggestion returned",
                ))
        except Exception:
            all_suggestions.append(FileSuggestion(
                original=name, suggested=name, reason="Could not analyze image",
            ))

    for name in image_files[MAX_IMAGES_PER_BATCH:]:
        all_suggestions.append(FileSuggestion(
            original=name, suggested=name,
            reason=f"Exceeded {MAX_IMAGES_PER_BATCH}-image analysis limit; kept original",
        ))

    return RenamePreviewResponse(resolved_path=str(directory), suggestions=all_suggestions)


@app.post("/api/rename-apply", response_model=ApplyRenameResponse)
async def rename_apply(request: ApplyRenameRequest) -> ApplyRenameResponse:
    """Physically rename files based on the user-confirmed list."""
    directory = resolve_and_validate(request.path)
    renamed = 0
    results: List[RenameResult] = []

    for item in request.renames:
        src = directory / item.original
        if not src.exists():
            results.append(RenameResult(
                original=item.original, new_name=item.new_name,
                status="skipped — source not found",
            ))
            continue

        safe_name = _safe_filename(item.new_name)
        dst = directory / safe_name

        # Avoid silently overwriting another file
        if dst.exists() and dst.resolve() != src.resolve():
            stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
            counter = 1
            while dst.exists():
                dst = directory / f"{stem}-{counter}{suffix}"
                counter += 1

        try:
            shutil.move(str(src), str(dst))
            renamed += 1
            results.append(RenameResult(
                original=item.original, new_name=dst.name, status="renamed",
            ))
        except Exception as exc:
            results.append(RenameResult(
                original=item.original, new_name=item.new_name,
                status=f"error: {exc}",
            ))

    return ApplyRenameResponse(resolved_path=str(directory), renamed=renamed, results=results)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
