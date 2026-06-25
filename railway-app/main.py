"""
CV Review - registration platform (Railway).

Flow:
  1. Candidate opens "/" and submits name + country prefix + phone + CV (PDF/DOCX).
  2. We save the file, extract its text, and build a public URL for it.
  3. We POST { full_name, phone_number, cv_text, cv_file } to the
     HappyRobot workflow trigger (WORKFLOW_TRIGGER_URL).

Env vars:
  WORKFLOW_TRIGGER_URL   (required in prod) the HappyRobot trigger webhook URL
  RAILWAY_PUBLIC_DOMAIN  (set automatically by Railway) used to build cv_file URL
  PUBLIC_BASE_URL        (optional) override for the public base URL
"""

import os
import re
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

STATIC_DIR = pathlib.Path("static")
STATIC_DIR.mkdir(exist_ok=True)

WORKFLOW_TRIGGER_URL = os.environ.get("WORKFLOW_TRIGGER_URL", "").strip()
ALLOWED_EXT = {".pdf", ".docx", ".doc"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# (label, dial code) — shown in the prefix dropdown
COUNTRIES = [
    ("Spain", "+34"),
    ("United Kingdom", "+44"),
    ("USA / Canada", "+1"),
    ("France", "+33"),
    ("Germany", "+49"),
    ("Italy", "+39"),
    ("Portugal", "+351"),
    ("Netherlands", "+31"),
    ("Mexico", "+52"),
    ("Colombia", "+57"),
]

app = FastAPI(title="CV Review Registration")
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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


def to_e164(country_code: str, local: str) -> str:
    """Combine a dial code and a local number into E.164 (e.g. +34689329343)."""
    cc = country_code if country_code.startswith("+") else "+" + country_code
    digits = re.sub(r"\D", "", local).lstrip("0")
    return f"{cc}{digits}"


def public_base(request: Request) -> str:
    override = os.environ.get("PUBLIC_BASE_URL")
    if override:
        return override.rstrip("/")
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}"
    return str(request.base_url).rstrip("/")


def _country_options() -> str:
    opts = []
    for label, code in COUNTRIES:
        sel = " selected" if code == "+34" else ""
        opts.append(f'<option value="{code}"{sel}>{label} ({code})</option>')
    return "".join(opts)


PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HappyRobot — Upload your CV</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#2b2620; --muted:#8a8275; --line:#d9cfbd;
    --card:#ece3d2; --field:#f6f0e4; --accent:#2b2620;
  }
  *{box-sizing:border-box;}
  body{margin:0;font-family:'Inter',-apple-system,Segoe UI,Roboto,Arial,sans-serif;
       color:var(--ink);min-height:100vh;
       background:#2b2825 url('/static/bg.png') center center / cover no-repeat fixed;
       display:flex;flex-direction:column;align-items:center;justify-content:center;}
  .wrap{flex:1;width:100%;display:flex;align-items:center;justify-content:center;padding:24px;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:20px;
        padding:40px;width:100%;max-width:470px;
        box-shadow:0 24px 60px rgba(0,0,0,.45);}
  .eyebrow{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
           color:var(--muted);margin:0 0 10px;}
  h1{font-size:32px;line-height:1.1;letter-spacing:-.02em;margin:0 0 8px;font-weight:600;}
  h1 em{font-family:'Instrument Serif',Georgia,serif;font-style:italic;font-weight:400;}
  p.sub{color:#6f665a;margin:0 0 28px;font-size:15px;line-height:1.5;}
  label{display:block;font-size:13px;font-weight:600;margin:18px 0 7px;}
  input[type=text],input[type=tel],select{width:100%;padding:12px 13px;font-size:15px;
        font-family:inherit;border:1px solid var(--line);border-radius:11px;background:var(--field);
        color:var(--ink);outline:none;transition:border-color .15s;}
  input:focus,select:focus{border-color:var(--ink);}
  .phone-row{display:flex;gap:10px;}
  .phone-row select{flex:0 0 42%;}
  .phone-row input{flex:1;}
  .file-field{margin-top:7px;border:1px dashed var(--line);border-radius:11px;padding:14px;
              background:var(--field);}
  .file-field input{font-size:14px;width:100%;}
  .hint{color:var(--muted);font-size:12px;margin-top:7px;}
  button{margin-top:28px;width:100%;padding:14px;font-size:15px;font-weight:600;
         color:#f6f0e4;background:var(--accent);border:none;border-radius:12px;cursor:pointer;
         transition:opacity .15s;}
  button:hover{opacity:.88;}
  button:disabled{opacity:.5;cursor:default;}
  .foot{color:rgba(246,240,228,.6);font-size:12px;padding:20px;text-align:center;}
</style>
</head>
<body>
  <div class="wrap">
"""

PAGE_FOOT = """
  </div>
  <div class="foot">Powered by HappyRobot · AI workers handle end-to-end tasks at scale</div>
</body>
</html>"""


def form_html() -> str:
    return PAGE_HEAD + """
    <form class="card" action="/submit" method="post" enctype="multipart/form-data"
          onsubmit="var b=this.querySelector('button');b.disabled=true;b.textContent='Uploading…';">
      <p class="eyebrow">Candidate registration</p>
      <h1>Upload your <em>CV</em></h1>
      <p class="sub">Register below and one of our AI recruiters will give you a quick call to say hi.</p>

      <label for="full_name">Full name</label>
      <input id="full_name" name="full_name" type="text" required placeholder="Jane Doe">

      <label for="phone_number">Phone number</label>
      <div class="phone-row">
        <select id="country_code" name="country_code" aria-label="Country code">__COUNTRIES__</select>
        <input id="phone_number" name="phone_number" type="tel" required placeholder="600 000 000">
      </div>
      <div class="hint">We&#8217;ll call this number, so make sure it&#8217;s correct.</div>

      <label>Your CV</label>
      <div class="file-field">
        <input id="cv" name="cv" type="file" accept=".pdf,.docx,.doc" required>
      </div>
      <div class="hint">PDF or DOCX, up to 10&#8202;MB.</div>

      <button type="submit">Submit application</button>
    </form>
    """.replace("__COUNTRIES__", _country_options()) + PAGE_FOOT


def result_html(name: str, sent: bool, error: str, phone: str) -> str:
    if sent:
        title = "You&#8217;re all set, {0}.".format(name)
        sub = "We received your CV. Expect a quick call from our AI recruiter at {0} soon.".format(phone)
    else:
        title = "We saved your CV, {0}.".format(name)
        sub = "But we couldn&#8217;t reach the recruiting workflow just now. Please try again shortly."
    body = """
    <div class="card" style="text-align:center;">
      <p class="eyebrow">Application received</p>
      <h1>{title}</h1>
      <p class="sub">{sub}</p>
      <a href="/" style="color:#0a0a0a;font-weight:600;text-decoration:none;font-size:14px;">&#8592; Submit another</a>
    </div>
    """.format(title=title, sub=sub)
    return PAGE_HEAD + body + PAGE_FOOT


@app.get("/", response_class=HTMLResponse)
def index():
    return form_html()


@app.get("/health")
def health():
    return {"ok": True, "trigger_configured": bool(WORKFLOW_TRIGGER_URL)}


@app.post("/submit")
async def submit(
    request: Request,
    full_name: str = Form(...),
    country_code: str = Form("+34"),
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

    phone_e164 = to_e164(country_code, phone_number)
    cv_file_url = f"{public_base(request)}/files/{saved.name}"

    payload = {
        "full_name": full_name,
        "phone_number": phone_e164,
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

    return HTMLResponse(result_html(full_name, sent, error, phone_e164))
