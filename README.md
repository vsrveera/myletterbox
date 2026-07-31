# Life Cabinet (myletterbox)

An AI-powered personal document cabinet. Documents arrive either by forwarding an
email to an AgentMail inbox (auto-replied with a summary) or by uploading directly
from the web UI. Either way, Claude reads the document, summarises it in English,
and classifies it into a category, an asset (e.g. "BMW iX3", "Frankfurt Apartment"),
tags, and any relevant dates — so the web UI can present it as a browsable cabinet
with a dashboard, category/asset filters, and a workflow board, not just a flat
inbox.

This is Phase 1 of the product described in `ProductRequirementsDocument.md` —
data model, AI classification, and the web UI; still single-user and web-only
(no semantic search, AI chat, sharing, or mobile apps yet).

Built with Claude (Anthropic), AgentMail, Firebase, and deployed on Google Cloud Run.

---

## How it works

Documents enter Life Cabinet one of two ways:

```
Sender → AgentMail inbox → Webhook ─┐
                                     │
Web UI → POST /documents (upload) ──┼──→ Cloud Run
                                     │
                          ┌──────────┼──────────────────┐
                          │          │                   │
                    Download      Fetch thread      Fetch email
                 attachments       history            body
                          │
                    Convert to Claude-compatible format
                    (HEIC→JPEG, merge images+PDFs)
                          │
                    Claude claude-opus-4-8 — structured JSON response:
                    - subject, summary
                    - category (13-item taxonomy), document_type, tags
                    - document_date, expiry_date
                    - asset_name (reuses an existing asset when it matches)
                    - owner
                          │
                ┌─────────┴──────────┐
                │                    │
          Reply to sender      Save to database
          (email path only —   Firestore: metadata + classification
           HTML email +        GCS: merged PDF
           combined PDF)
```

Uploads can process multiple files as one merged document (e.g. several pages
of one letter) or as independent documents, each classified separately — see
`mode` on `POST /documents` below.

---

## Features

- **Reads non-English documents** — letters, invitations, invoices, official correspondence
- **Any attachment format** — JPEG, PNG, WebP, HEIC/HEIF (iPhone), AVIF, TIFF, BMP, PDF
- **Thread-aware** — includes prior emails in the chain as context
- **Auto-subject** — derives a descriptive subject from content, ignores vague originals like "test" or "hello"
- **AI classification** — every document is filed into one of 13 categories (Finance, Property, Vehicles, Insurance, …), given a document type, tags, and dates, and linked to a real-world asset
- **HTML reply** — formatted email with headings, bullet points, and blockquotes (email ingestion path only)
- **Combined PDF** — attachments merged into one PDF, named after the generated subject
- **Per-user storage** — documents and assets in Firestore, PDFs in Cloud Storage, keyed by sender email
- **Manual upload** — upload photos/PDFs directly from the web UI, processed as one merged document or as independent documents
- **Web UI** — Firebase-hosted SPA: a landing page, Home dashboard (needs attention / upcoming / recent), Cabinet (category + asset filters, matrix card grid, expandable detail), and a Workflow board (Inbox → Needs Action → Waiting → Completed) — secured with Google Sign-In

---

## Architecture

| Component | Technology |
|---|---|
| API / webhook server | FastAPI on Google Cloud Run |
| LLM | Claude claude-opus-4-8 (Anthropic) |
| Email | AgentMail |
| Image conversion | Pillow + pillow-heif |
| PDF merging | pypdf |
| Metadata store | Google Cloud Firestore |
| File store | Google Cloud Storage |
| Web UI | Firebase Hosting (vanilla JS + Firebase SDK) |
| Auth | Firebase Authentication (Google Sign-In); backend verifies ID tokens via `firebase-admin` |

---

## API endpoints

### `GET /health`
Health check.

```bash
curl https://myletterbox-757041740498.us-central1.run.app/health
# {"status": "ok"}
```

### `POST /summarize`
Directly summarise one or more uploaded German document images.

```bash
curl -X POST https://myletterbox-757041740498.us-central1.run.app/summarize \
  -F "files=@scan.jpg"
# {"summary": "..."}
```

Accepted file types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`, `image/heic`, `image/heif`, `image/avif`, `image/tiff`, `image/bmp`

### `POST /webhook`
AgentMail webhook receiver. Called automatically when the inbox receives an email — not intended for direct use.

**Request** (AgentMail `message.received` event):
```json
{
  "event_id": "...",
  "event_type": "message.received",
  "message": {
    "inbox_id": "you@agentmail.to",
    "message_id": "<...>",
    "thread_id": "...",
    "from": "Name <sender@example.com>",
    "subject": "hello",
    "body_url": "https://...",
    "attachments": [
      {
        "attachment_id": "...",
        "filename": "letter.jpg",
        "content_type": "image/jpeg"
      }
    ]
  },
  "thread": { "message_count": 1 }
}
```

**Response:**
```json
{
  "status": "ok",
  "subject": "East German Pedagogical Conference Invitation 1978",
  "summary": "..."
}
```

### `POST /documents`
Manual upload from the web UI. Requires a Firebase ID token (`Authorization: Bearer <token>`) — the backend derives the sender's storage path from the token's email claim, it is not passed in the request.

```bash
curl -X POST https://myletterbox-757041740498.us-central1.run.app/documents \
  -H "Authorization: Bearer $ID_TOKEN" \
  -F "files=@bill1.jpg" \
  -F "files=@bill2.jpg" \
  -F "title=" \
  -F "mode=separate"
```

- `files` — one or more images/PDFs (same accepted types as `/summarize`)
- `title` — optional, used as a hint for the generated subject
- `mode` — `merge` (default): all files become one document with one combined PDF. `separate`: each file is classified and saved as its own document (assets created by earlier files in the batch are available for later ones to reuse).

**Response:**
```json
{ "status": "ok", "documents": [{ "id": "...", "subject": "...", "summary": "..." }] }
```

### `PATCH /documents/{doc_id}`
Edit a document's metadata. Requires a Firebase ID token; only documents under the caller's own `users/{email}/documents` path can be modified. Body is any subset of the editable fields.

```bash
curl -X PATCH https://myletterbox-757041740498.us-central1.run.app/documents/abc123 \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workflow_status": "Completed", "tags": ["paid", "2026"]}'
```

Editable fields: `workflow_status`, `category`, `asset_name` (resolved to an asset, created if it doesn't exist yet), `tags`, `subject`, `summary`.

---

## Data storage

Every processed email is stored under the sender's email address.

### Firestore

```
users/
  {sender_email}/
    documents/
      {event_id}/
        subject         string   — generated subject line
        summary         string   — full English summary
        timestamp       datetime — upload/received time
        thread_id       string
        inbox_id        string
        pdf_gcs_uri     string   — gs://... path to merged PDF (null if no attachments)
        pdf_public_url  string   — https://storage.googleapis.com/... public download URL
        pdf_filename    string
        attachment_count number

        category         string  — one of 13 categories (Identity & Legal, Finance,
                                    Property, Vehicles, Insurance, Health, Family,
                                    Career & Business, Education, Travel,
                                    Purchases & Warranties, Reference, Archive)
        document_type    string  — free text, e.g. "Invoice", "Insurance Policy"
        workflow_status  string  — Inbox | Needs Action | Waiting | Completed
        tags             array<string>
        document_date    string  — ISO date on the document itself (nullable)
        expiry_date      string  — ISO date it expires/renews/is due (nullable)
        asset_id         string  — links to assets/{assetId} (nullable)
        asset_name       string  — denormalized for display (nullable)
        owner            string  — person the document concerns (nullable)
        source           string  — "email" | "upload"
        original_filename string

    assets/
      {assetId}/
        name       string   — e.g. "BMW iX3", "Frankfurt Apartment"
        category   string
        created_at datetime
```

Assets are created automatically (case-insensitive match-or-create) whenever a
document is classified with an `asset_name` that doesn't already exist for that
user, so repeated mentions of the same car or property converge on one asset
instead of creating duplicates.

### Cloud Storage

```
gs://myletterbox-757041740498/
  {sender_email}/
    {event_id}/
      {Subject_Line}.pdf    ← all attachments merged into one PDF
```

---

## Web UI

A static single-page app (`public/index.html`, vanilla JS, no build step) hosted
on Firebase. Signed out, it's a landing page; signed in, it's the cabinet.

**URL:** `https://project-f33cb18b-d366-43b3-9ee.web.app`

**Features:**
- Google Sign-In — only the sender's own documents are visible (enforced by Firestore security rules for reads; writes go through the backend, which verifies the same ID token)
- **Home** — Needs Attention (status = Needs Action, or expiring within 30 days), Upcoming (future expiry dates), Recent Documents
- **Cabinet** (default view after sign-in) — category filters rendered as folder tiles, a secondary asset-filter row once a category is picked, a workflow-status filter, and documents laid out as a responsive card grid (matrix); clicking a card opens it as a large centered modal with the full summary, PDF link, thread strip, and inline editors for workflow status / category / asset / tags. A table view is also available. The "+" button opens the upload modal (merge or process-separately mode)
- **Workflow** — documents grouped into Inbox / Needs Action / Waiting / Completed columns, with a status dropdown per row
- Search bar filters by subject or summary text, combinable with the category/asset/status filters
- Keyboard: `j`/`k` to move the cursor, `Enter` to open, `/` to search, `Esc` to close

**Firestore security rules** (`firestore.rules`) restrict each user to their own subtree, for both documents and assets:
```
match /users/{email}/documents/{docId} {
  allow read: if request.auth != null && request.auth.token.email == email;
}
match /users/{email}/assets/{assetId} {
  allow read: if request.auth != null && request.auth.token.email == email;
}
```
Only reads are allowed by these rules — all writes (including metadata edits from
the detail-pane editors) go through the backend's `PATCH /documents/{doc_id}`,
which verifies the caller's Firebase ID token itself.

**To redeploy the web UI** after making changes to `public/index.html` or `firestore.rules`:
```bash
firebase login   # once
firebase deploy --only hosting          # public/index.html
firebase deploy --only firestore:rules  # firestore.rules
```

---

## Local development

### Prerequisites
- Python 3.13+
- An [Anthropic API key](https://console.anthropic.com/settings/api-keys)
- An [AgentMail](https://agentmail.to) API key and inbox

### Setup

```bash
git clone https://github.com/vsrveera/myletterbox
cd myletterbox
pip install -r requirements.txt
```

Create a `.env` file:
```
ANTHROPIC_API_KEY=sk-ant-...
AGENTMAIL_API_KEY=am_...
GCS_BUCKET=myletterbox-757041740498   # optional, only needed for storage
```

Run the server:
```bash
uvicorn main:app --reload
```

Test with the sample image:
```bash
curl -X POST http://localhost:8000/summarize \
  -F "files=@sample_german_letter.jpg"
```

---

## Deployment (Google Cloud Run)

### First-time setup

```bash
# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com storage.googleapis.com

# Create Firestore database
gcloud firestore databases create --location=us-central1

# Create GCS bucket (must be globally unique)
gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=us-central1

# Grant Cloud Run service account access
SA="{PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/datastore.user"
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:$SA" --role="roles/storage.objectAdmin"
```

### Deploy

```bash
gcloud run deploy myletterbox \
  --source . \
  --region us-central1 \
  --set-env-vars "ANTHROPIC_API_KEY=sk-ant-...,AGENTMAIL_API_KEY=am_...,GCS_BUCKET=YOUR_BUCKET_NAME" \
  --allow-unauthenticated
```

### Register the AgentMail webhook

```bash
curl -X POST https://api.agentmail.to/v0/inboxes/{inbox_id}/webhooks \
  -H "Authorization: Bearer $AGENTMAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://YOUR_CLOUD_RUN_URL/webhook",
    "event_type": "message.received"
  }'
```

---

## Project structure

```
myletterbox/
├── main.py                         # FastAPI app — endpoints, webhook handler, auth, CORS
├── summarize_images.py             # Claude integration — classification and PDF merging
├── storage.py                      # Firestore + GCS persistence, asset get-or-create
├── Dockerfile
├── requirements.txt
├── firebase.json                   # Firebase Hosting + Firestore rules config
├── firestore.rules                 # Firestore security rules
├── .firebaserc                     # Firebase project binding
├── ProductRequirementsDocument.md  # Full product vision (Life Cabinet) — this repo implements Phase 1
├── public/
│   └── index.html                  # Web UI SPA (landing page, Home/Cabinet/Workflow, Google Sign-In)
└── sample_german_letter.jpg
```
