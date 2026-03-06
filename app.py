import os
import sys
import json
import uuid
import base64
import threading
import urllib.parse
import requests as req
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

sys.path.insert(0, str(Path(__file__).parent))
from claude_detect_fields import convert_pdf_to_images, detect_fields_with_claude
from docusign_agent import build_docusign_tabs, create_template, send_envelope_from_template
from chat_agent import chat_stream, save_correction

app    = Flask(__name__)
UPLOAD = Path("uploads")
UPLOAD.mkdir(exist_ok=True)
JOBS_FILE = Path("jobs.json")

def load_jobs():
    try:
        return json.load(open(JOBS_FILE)) if JOBS_FILE.exists() else {}
    except:
        return {}

def save_job(job_id, data):
    jobs = load_jobs()
    jobs[job_id] = data
    with open(JOBS_FILE, 'w') as f:
        json.dump(jobs, f)

AUTH_SERVER  = "account-d.docusign.com"
REDIRECT_URI = os.environ.get("DOCUSIGN_REDIRECT_URI", "http://localhost:5000/api/auth-callback")

# ---- Auth ----
@app.route("/api/auth-url")
def auth_url():
    key = os.environ.get("DOCUSIGN_INTEGRATION_KEY")
    url = (f"https://{AUTH_SERVER}/oauth/auth?response_type=code&scope=signature"
           f"&client_id={key}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}")
    return jsonify({"url": url})

@app.route("/api/auth-callback")
def auth_callback():
    code   = request.args.get("code")
    key    = os.environ.get("DOCUSIGN_INTEGRATION_KEY")
    secret = os.environ.get("DOCUSIGN_SECRET_KEY")

    creds = base64.b64encode(f"{key}:{secret}".encode()).decode()
    r = req.post(f"https://{AUTH_SERVER}/oauth/token",
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})

    token    = r.json()["access_token"]
    r2       = req.get(f"https://{AUTH_SERVER}/oauth/userinfo",
                       headers={"Authorization": f"Bearer {token}"})
    accounts = r2.json().get("accounts", [])
    account  = next((a for a in accounts if a.get("is_default")), accounts[0])
    name     = r2.json().get("name", "Connected")

    return f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;text-align:center;padding:80px;background:#080909;color:#fff">
<h2 style="color:#4ade80">✓ Connected to DocuSign</h2>
<p style="color:#6b7280">You can close this tab.</p>
<script>
  const data = {{
    token:      "{token}",
    account_id: "{account["account_id"]}",
    base_uri:   "{account["base_uri"]}",
    name:       "{name}"
  }};
  if (window.opener) {{
    window.opener.postMessage({{type:"ds_auth", ...data}}, "*");
  }}
  setTimeout(() => window.close(), 800);
</script>
</body></html>"""

# ---- Send ----
@app.route("/api/send", methods=["POST"])
def send():
    data         = request.get_json(force=True, silent=True) or {}
    token        = data.get("token")
    account_id   = data.get("account_id")
    base_uri     = data.get("base_uri")
    recipients   = data.get("recipients", [])
    pdf_b64      = data.get("pdf_base64")
    filename     = data.get("filename", "document.pdf")

    if not all([token, account_id, base_uri, pdf_b64]) or not recipients:
        return jsonify({"error": "Missing required fields"}), 400

    # Back-compat: extract first recipient for legacy signer_name/signer_email
    signer_name  = recipients[0].get("name") if recipients else data.get("signer_name")
    signer_email = recipients[0].get("email") if recipients else data.get("signer_email")

    pdf_path = UPLOAD / f"{uuid.uuid4()}_{filename}"
    with open(str(pdf_path), "wb") as f:
        f.write(base64.b64decode(pdf_b64))

    job_id = str(uuid.uuid4())
    save_job(job_id, {"status": "running", "step": 1, "message": "Starting..."})

    def run():
        try:
            save_job(job_id, {"status": "running", "step": 1, "message": "Converting PDF to images..."})
            images_dir  = str(UPLOAD / "images")
            image_paths = convert_pdf_to_images(str(pdf_path), images_dir)

            save_job(job_id, {"status": "running", "step": 2, "message": "Detecting fields with Claude..."})
            fields_data = detect_fields_with_claude(image_paths)
            count       = len(fields_data["form_fields"])

            save_job(job_id, {"status": "running", "step": 3, "message": f"Detected {count} fields, building tabs..."})
            tabs = build_docusign_tabs(fields_data)

            save_job(job_id, {"status": "running", "step": 4, "message": "Creating DocuSign template..."})
            template_id = create_template(str(pdf_path), tabs, token, account_id, base_uri)

            names_str = ", ".join(r.get("email", "") for r in recipients)
            save_job(job_id, {"status": "running", "step": 5, "message": f"Sending envelope to {names_str}..."})
            envelope_id = send_envelope_from_template(template_id, signer_name, signer_email,
                                                      token, account_id, base_uri)
            save_job(job_id, {"status": "complete", "step": 5,
                            "message": "Envelope sent!",
                            "envelope_id": envelope_id,
                            "template_id": template_id})
        except Exception as e:
            save_job(job_id, {"status": "error", "step": -1, "message": str(e)})

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = load_jobs().get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

# ---- Chat ----
@app.route("/api/chat", methods=["POST"])
def chat_api():
    data = request.get_json(force=True, silent=True) or {}
    def generate():
        yield from chat_stream(
            message      = data.get("message", ""),
            history      = data.get("history", []),
            token        = data.get("token"),
            account_id   = data.get("account_id"),
            base_uri     = data.get("base_uri"),
            sender_email = data.get("sender_email"),
            pdf_base64   = data.get("pdf_base64"),
            pdf_filename = data.get("pdf_filename"),
        )
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/correction", methods=["POST"])
def correction():
    data = request.get_json(force=True, silent=True) or {}
    save_correction(
        message_text  = data.get("message", ""),
        flagged_answer= data.get("flagged_answer", ""),
        feedback      = data.get("feedback", ""),
    )
    return jsonify({"ok": True})

# ---- Health / Pages ----
@app.route("/api/sign-now", methods=["POST"])
def sign_now():
    data       = request.get_json(force=True, silent=True) or {}
    token      = data.get("token")
    account_id = data.get("account_id")
    base_uri   = data.get("base_uri")
    pdf_b64    = data.get("pdf_base64")
    filename   = data.get("filename", "document.pdf")
    name       = data.get("signer_name", "Signer")
    email      = data.get("signer_email", "signer@example.com")
    return_url = data.get("return_url", "https://docusign.com")

    if not all([token, account_id, base_uri, pdf_b64]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        # Clean base64
        clean_b64 = pdf_b64
        if "," in pdf_b64[:100]:
            clean_b64 = pdf_b64.split(",", 1)[1]
        clean_b64 = clean_b64.strip().replace("\n","").replace("\r","").replace(" ","")

        import requests as req_lib

        # Create envelope with embedded signing (clientUserId marks it as embedded)
        envelope_body = {
            "emailSubject": f"Please sign: {filename}",
            "documents": [{
                "documentBase64": clean_b64,
                "name": filename,
                "fileExtension": "pdf",
                "documentId": "1",
            }],
            "recipients": {
                "signers": [{
                    "name":         name,
                    "email":        email,
                    "recipientId":  "1",
                    "clientUserId": "1",   # required for embedded signing
                    "routingOrder": "1",
                }]
            },
            "status": "sent",
        }

        r = req_lib.post(
            f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=envelope_body,
            timeout=30
        )
        if r.status_code not in [200, 201]:
            return jsonify({"error": r.text}), 400

        envelope_id = r.json()["envelopeId"]

        # Get the embedded signing URL
        view_body = {
            "returnUrl":        return_url,
            "authenticationMethod": "none",
            "email":            email,
            "userName":         name,
            "clientUserId":     "1",
            "recipientId":      "1",
        }

        r2 = req_lib.post(
            f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes/{envelope_id}/views/recipient",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=view_body,
            timeout=30
        )
        if r2.status_code not in [200, 201]:
            return jsonify({"error": r2.text}), 400

        signing_url = r2.json()["url"]
        return jsonify({"signing_url": signing_url, "envelope_id": envelope_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/extract-pdf-fields", methods=["POST"])
def extract_pdf_fields():
    data     = request.get_json(force=True, silent=True) or {}
    pdf_b64  = data.get("pdf_base64")
    filename = data.get("filename", "document.pdf")

    if not pdf_b64:
        return jsonify({"error": "Missing pdf_base64"}), 400

    try:
        # Strip data URL prefix if present
        clean_b64 = pdf_b64
        if "," in pdf_b64[:100]:
            clean_b64 = pdf_b64.split(",", 1)[1]
        clean_b64 = clean_b64.strip().replace("\n", "").replace("\r", "").replace(" ", "")

        # Save PDF to disk temporarily
        pdf_path = UPLOAD / f"{uuid.uuid4()}_{filename}"
        with open(str(pdf_path), "wb") as f:
            f.write(base64.b64decode(clean_b64))

        # Convert to images and detect fields with Claude
        images_dir  = str(UPLOAD / "images")
        image_paths = convert_pdf_to_images(str(pdf_path), images_dir)
        fields_data = detect_fields_with_claude(image_paths)

        fields = fields_data.get("form_fields", [])
        return jsonify({"fields": fields, "filename": filename, "count": len(fields)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/chat")
def chat_page():
    return send_from_directory(".", "chat.html")

if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
