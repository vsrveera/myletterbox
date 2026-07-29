# myletterbox

An AI-powered email processing service that reads German letters and documents sent as email attachments, summarises them in English, and replies to the sender automatically.

Built with Claude (Anthropic), AgentMail, and deployed on Google Cloud Run.

---

## How it works

```
Sender → AgentMail inbox → Webhook → Cloud Run
                                         │
                          ┌──────────────┼──────────────────┐
                          │              │                   │
                    Download          Fetch thread      Fetch email
                 attachments           history            body
                          │
                    Convert to Claude-compatible format
                    (HEIC→JPEG, merge images+PDFs)
                          │
                    Claude claude-opus-4-8
                    - Generates subject from content
                    - Summarises in English
                          │
                ┌─────────┴──────────┐
                │                    │
          Reply to sender      Save to database
          (HTML email +        Firestore: metadata + summary
           combined PDF)       GCS: merged PDF
```

---

## Features

- **Reads German documents** — letters, invitations, invoices, official correspondence
- **Any attachment format** — JPEG, PNG, WebP, HEIC/HEIF (iPhone), AVIF, TIFF, BMP, PDF
- **Thread-aware** — includes prior emails in the chain as context
- **Auto-subject** — derives a descriptive subject from content, ignores vague originals like "test" or "hello"
- **HTML reply** — formatted email with headings, bullet points, and blockquotes
- **Combined PDF** — all attachments merged into one PDF, named after the generated subject, and attached to the reply
- **Per-user storage** — summaries in Firestore, PDFs in Cloud Storage, keyed by sender email

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
    "from": "sender@example.com",
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
        timestamp       datetime
        thread_id       string
        inbox_id        string
        pdf_gcs_uri     string   — gs://... path to merged PDF (null if no attachments)
        pdf_filename    string
        attachment_count number
```

### Cloud Storage

```
gs://myletterbox-757041740498/
  {sender_email}/
    {event_id}/
      {Subject_Line}.pdf    ← all attachments merged into one PDF
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
├── main.py              # FastAPI app — endpoints and webhook handler
├── summarize_images.py  # Claude integration — analysis and PDF merging
├── storage.py           # Firestore + GCS persistence
├── Dockerfile
├── requirements.txt
└── sample_german_letter.jpg
```
