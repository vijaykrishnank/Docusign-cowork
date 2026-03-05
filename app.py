import os
import sys
import json
import uuid
import base64
import threading
import urllib.parse
import requests as req
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory

sys.path.insert(0, str(Path(__file__).parent))
from claude_detect_fields import convert_pdf_to_images, detect_fields_with_claude
from docusign_agent import build_docusign_tabs, create_template, send_envelope_from_template

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

    # Return token to browser via postMessage so it stores in localStorage
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
    signer_name  = data.get("signer_name")
    signer_email = data.get("signer_email")
    pdf_b64      = data.get("pdf_base64")
    filename     = data.get("filename", "document.pdf")

    if not all([token, account_id, base_uri, signer_name, signer_email, pdf_b64]):
        return jsonify({"error": "Missing required fields"}), 400

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

            save_job(job_id, {"status": "running", "step": 5, "message": f"Sending envelope to {signer_email}..."})
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

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
