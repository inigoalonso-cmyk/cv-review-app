# CV Review – Registration platform

A small FastAPI app that front-ends the HappyRobot CV-review workflow.

**What it does**

1. Shows a registration form (full name, phone number, CV upload).
2. Accepts a **PDF or DOCX**, saves it, and extracts the text.
3. Sends `full_name`, `phone_number`, `cv_text`, and `cv_file` (a public link
   to the uploaded document) to the HappyRobot workflow trigger.

The workflow then makes the outbound call, scores the candidate, and emails
the qualified ones.

## Payload sent to the workflow

```json
{
  "full_name": "Jane Doe",
  "phone_number": "+34 600 000 000",
  "cv_text": "…full extracted text of the CV…",
  "cv_file": "https://your-app.up.railway.app/files/<id>.pdf"
}
```

These match the trigger inputs in the workflow.

## Run locally

```bash
pip install -r requirements.txt
export WORKFLOW_TRIGGER_URL="https://<your-happyrobot-trigger-url>"
uvicorn main:app --reload
# open http://localhost:8000
```

`GET /health` returns whether the trigger URL is configured.

## Deploy on Railway

1. Push this folder to a GitHub repo (or use `railway up` from the Railway CLI).
2. In Railway: **New Project → Deploy from repo** (or empty service + deploy).
3. Railway auto-detects Python and installs `requirements.txt`. The `Procfile`
   starts the server. (If asked for a start command, use:
   `uvicorn main:app --host 0.0.0.0 --port $PORT`.)
4. Add the environment variable **`WORKFLOW_TRIGGER_URL`** = your HappyRobot
   trigger webhook URL.
5. Open the generated `*.up.railway.app` URL — that's your registration page.

`RAILWAY_PUBLIC_DOMAIN` is provided by Railway automatically and is used to
build the `cv_file` links, so you normally don't need to set anything else.

## Notes

- **Scanned CVs:** text extraction works on native PDFs/DOCX. Image-only
  (scanned) PDFs would need OCR — out of scope for now.
- **File persistence:** uploads are stored on the container filesystem, which
  is ephemeral on Railway (cleared on redeploy). For permanent `cv_file` links,
  attach a Railway **Volume** mounted at `/app/uploads`, or switch storage to
  S3/Cloud Storage later.
- **Allowed types:** `.pdf`, `.docx`, `.doc`. Max 10 MB.
