"""
CV Review – registration platform (Railway).

Flow:
  1. Candidate opens "/" and submits name + phone + CV (PDF or DOCX).
  2. We save the file, extract its text, and build a public URL for it.
  3. We POST { full_name, phone_number, cv_text, cv_file } to the
     HappyRobot workflow trigger (WORKFLOW_TRIGGER_URL).

Env vars:
  WORKFLOW_TRIGGER_URL   (required in prod) the HappyRobot trigger webhook URL
  RAILWAY_PUBLIC_DOMAIN  (set automatically by Railway) used to build cv_file URL
  PUBLIC_BASE_URL        (optional) override for the public base URL
"""

import os
import uuid
import pathlib

import httpx
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import fitz  # PyMuPDF
import docx2txt

UPLOAD_DIR = pathlib.Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

WORKFLOW_TRIGGER_URL = os.environ.get("WORKFLOW_TRIGGER_URL", "").strip()
ALLOWED_EXT = {".pdf", ".docx", ".doc"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB

app = FastAPI(title="CV Review Registration")
# Serve uploaded CVs so cv_file is a downloadable URL
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")


def extract_text(path: pathlib.Path, ext: str) -> str:
    """Extract plain text from a PDF or DOCX file."""
    if ext == ".pdf":
        chunks = []
        with fitz.open(path) as doc:
            for page in doc:
                chunks.append(page.get_text())
        return "\n".join(chunks).strip()
    if ext in (".docx", ".doc"):
        return (docx2txt.process(str(path)) or "").strip()
    return ""


def public_base(request: Request) -> str:
    """Best public base URL for building file links."""
    override = os.environ.get("PUBLIC_BASE_URL")
    if override:
        return override.rstrip("/")
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}"
    return str(request.base_url).rstrip("/")


FORM_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upload your CV</title>
<style>
  :root { --ink:#1d1d1f; --sub:#6e6e73; --line:#e3e3e0; --accent:#3b7dd8; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
         color:var(--ink); background:#f6f7f9; display:flex; min-height:100vh;
         align-items:center; justify-content:center; padding:24px; }
  .card { background:#fff; border:1px solid var(--line); border-radius:16px;
          padding:32px; width:100%; max-width:440px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
  h1 { font-size:22px; margin:0 0 4px; }
  p.sub { color:var(--sub); margin:0 0 24px; font-size:14px; }
  label { display:block; font-size:13px; font-weight:600; margin:16px 0 6px; }
  input[type=text], input[type=tel] { width:100%; padding:11px 12px; font-size:15px;
          border:1px solid var(--line); border-radius:9px; }
  input[type=file] { width:100%; font-size:14px; margin-top:4px; }
  .hint { color:var(--sub); font-size:12px; margin-top:6px; }
  button { margin-top:24px; width:100%; padding:13px; font-size:15px; font-weight:600;
           color:#fff; background:var(--accent); border:none; border-radius:10px; cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
</style>
</head>
<body>
  <form class="card" action="/submit" method="post" enctype="multipart/form-data"
        onsubmit="this.querySelector('button').disabled=true; this.querySelector('button').textContent='Uploading…';">
    <h1>Upload my CV</h1>
    <p class="sub">Register and we&#8217;ll be in touch shortly.</p>

    <label for="full_name">Full name</label>
    <input id="full_name" name="full_name" type="text" required placeholder="Jane Doe">

    <label for="phone_number">Phone number</label>
    <input id="phone_number" name="phone_number" type="tel" required placeholder="+34 600 000 000">

    <label for="cv">Your CV</label>
    <input id="cv" name="cv" type="file" accept=".pdf,.docx,.doc" required>
    <div class="hint">PDF or DOCX, up to 10&#8202;MB.</div>

    <button type="submit">Submit</button>
  </form>
</body>
</html>"""


def result_html(name: str, sent: bool, error: str, chars: int) -> str:
    if sent:
        msg = "Thanks, {0} &#8212; your CV was received. We&#8217;ll be in touch soon.".format(name)
        tone = "#1a7f3c"
    elif error:
        msg = "We saved your CV but couldn&#8217;t notify the team yet. Please try again later."
        tone = "#b3261e"
    else:
        msg = "Thanks, {0} &#8212; your CV was received.".format(name)
        tone = "#1a7f3c"
    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Received</title>
<style>body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
background:#f6f7f9;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;}}
.card{{background:#fff;border:1px solid #e3e3e0;border-radius:16px;padding:32px;max-width:440px;text-align:center;}}
h1{{color:{tone};font-size:20px;margin:0 0 10px;}} p{{color:#6e6e73;font-size:14px;}}
a{{color:#3b7dd8;text-decoration:none;font-size:14px;}}</style></head>
<body><div class="card"><h1>{msg}</h1>
<p>Extracted {chars} characters from your CV.</p>
<a href="/">Submit another</a></div></body></html>""".format(tone=tone, msg=msg, chars=chars)


@app.get("/", response_class=HTMLResponse)
def index():
    return FORM_HTML


@app.get("/health")
def health():
    return {"ok": True, "trigger_configured": bool(WORKFLOW_TRIGGER_URL)}


@app.post("/submit")
async def submit(
    request: Request,
    full_name: str = Form(...),
    phone_number: str = Form(...),
    cv: UploadFile = File(...),
):
    ext = pathlib.Path(cv.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        return JSONResponse({"error": "Only PDF or DOCX files are allowed."}, status_code=400)

    content = await cv.read()
    if len(content) > MAX_BYTES:
        return JSONResponse({"error": "File too large (max 10 MB)."}, status_code=400)

    file_id = uuid.uuid4().hex
    saved = UPLOAD_DIR / f"{file_id}{ext}"
    saved.write_bytes(content)

    try:
        cv_text = extract_text(saved, ext)
    except Exception:
        cv_text = ""

    cv_file_url = f"{public_base(request)}/files/{saved.name}"

    payload = {
        "full_name": full_name,
        "phone_number": phone_number,
        "cv_text": cv_text,
        "cv_file": cv_file_url,
    }

    sent, error = False, ""
    if WORKFLOW_TRIGGER_URL:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(WORKFLOW_TRIGGER_URL, json=payload)
                resp.raise_for_status()
                sent = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    else:
        error = "WORKFLOW_TRIGGER_URL not set"

    return HTMLResponse(result_html(full_name, sent, error, len(cv_text)))
