"""
docusign_agent.py

End-to-end agent that:
1. Downloads/loads a PDF from a URL or local path
2. Uses claude_detect_fields.py to convert PDF to images and detect all fields
3. Builds DocuSign tabs using pixel coordinates scaled to PDF points
   (scale_x = 612 / image_width, scale_y = 792 / image_height)
4. Authenticates via Authorization Code Grant (browser login)
5. Creates a DocuSign template from the PDF with tabs pre-placed
6. Sends the envelope from that template to the recipient

Usage:
    python3 docusign_agent.py <pdf_url_or_path> <signer_name> <signer_email>

Examples:
    python3 docusign_agent.py https://example.com/form.pdf "John Smith" "john@example.com"
    python3 docusign_agent.py /Users/you/Desktop/form.pdf "John Smith" "john@example.com"

Required environment variables:
    export DOCUSIGN_INTEGRATION_KEY="your-integration-key"
    export DOCUSIGN_SECRET_KEY="your-secret-key"
"""

import base64
import json
import os
import sys
import requests
import tempfile
import shutil
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Reuse functions from claude_detect_fields.py
sys.path.insert(0, str(Path(__file__).parent))
from claude_detect_fields import convert_pdf_to_images, detect_fields_with_claude
from document_summary import generate_summaries


# ---------------------------------------------------------------
# STEP 1: Load PDF from URL or local path
# ---------------------------------------------------------------
def load_pdf(pdf_source: str) -> str:
    if pdf_source.startswith("http://") or pdf_source.startswith("https://"):
        print(f"Downloading PDF from {pdf_source}...")
        response = requests.get(pdf_source, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download PDF: {response.status_code}")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(response.content)
        tmp.close()
        print(f"Downloaded to {tmp.name}")
        return tmp.name
    else:
        if not Path(pdf_source).exists():
            raise FileNotFoundError(f"PDF not found: {pdf_source}")
        print(f"Using local PDF: {pdf_source}")
        return pdf_source


# ---------------------------------------------------------------
# STEP 2 & 3: Reused from claude_detect_fields.py
# ---------------------------------------------------------------


# ---------------------------------------------------------------
# STEP 4a: Shift tab page numbers by offset (summary pages prepended)
# ---------------------------------------------------------------
def shift_tabs_by_offset(tabs: dict, offset: int) -> dict:
    """
    Shift every tab pageNumber by offset.
    External recipients get offset=1 (1 summary page prepended).
    Internal recipients get offset=2 (2 summary pages prepended).
    """
    shifted = {}
    for tab_type, tab_list in tabs.items():
        shifted[tab_type] = []
        for tab in tab_list:
            t = dict(tab)
            t["pageNumber"] = str(int(t["pageNumber"]) + offset)
            shifted[tab_type].append(t)
    return shifted


# ---------------------------------------------------------------
# STEP 4: Build DocuSign tabs using pixel → PDF point scaling
# PDF page = 612 x 792 pts
# Scale: x = 612 / image_width, y = 792 / image_height
# ---------------------------------------------------------------
def build_docusign_tabs(fields_data: dict) -> dict:
    print(f"\nBuilding DocuSign tabs from field coordinates...")

    fields     = fields_data["form_fields"]
    first_page = fields_data["pages"][0]
    scale_x    = 612.0 / first_page["image_width"]
    scale_y    = 792.0 / first_page["image_height"]
    print(f"   Scale: x={scale_x:.4f}, y={scale_y:.4f}")

    text_tabs        = []
    checkbox_tabs    = []
    date_tabs        = []
    email_tabs       = []
    number_tabs      = []
    sign_here_tabs   = []
    date_signed_tabs = []
    has_signature    = False

    for field in fields:
        page_num   = field["page_number"]
        box        = field["entry_bounding_box"]
        field_type = field.get("field_type", "text").lower()
        label      = field.get("field_label", "Field")

        x = int(box[0] * scale_x)
        y = int(box[1] * scale_y)
        w = int((box[2] - box[0]) * scale_x)
        h = int((box[3] - box[1]) * scale_y)

        # Ensure minimum dimensions
        w = max(w, 20)
        h = max(h, 12)

        base = {
            "tabLabel":   label,
            "documentId": "1",
            "pageNumber": str(page_num),
            "xPosition":  str(x),
            "yPosition":  str(y),
        }

        if field_type == "signature":
            sign_here_tabs.append({**base, "width": str(w), "height": str(h)})
            date_signed_tabs.append({
                **base,
                "tabLabel":  f"{label}_date",
                "xPosition": str(min(x + w + 10, 560)),  # cap at page width
                "width":     "80",
                "height":    str(h),
            })
            has_signature = True

        elif field_type == "checkbox":
            checkbox_tabs.append({**base, "width": str(max(w, 14)), "height": str(max(h, 14))})

        elif field_type == "date":
            date_tabs.append({**base, "width": str(w), "height": str(h),
                               "font": "helvetica", "fontSize": "size10",
                               "locked": "false", "required": "false"})

        elif field_type == "email":
            email_tabs.append({**base, "width": str(w), "height": str(h),
                                "font": "helvetica", "fontSize": "size10",
                                "locked": "false", "required": "false"})

        elif field_type == "number":
            number_tabs.append({**base, "width": str(w), "height": str(h),
                                 "font": "helvetica", "fontSize": "size10",
                                 "locked": "false", "required": "false"})

        else:
            text_tabs.append({**base, "width": str(w), "height": str(h),
                               "font": "helvetica", "fontSize": "size10",
                               "locked": "false", "required": "false"})

    # Add signature tab if none detected
    if not has_signature and fields:
        last     = fields[-1]
        last_box = last["entry_bounding_box"]
        sig_x    = int(last_box[0] * scale_x)
        sig_y    = int(last_box[3] * scale_y) + 20
        sign_here_tabs.append({
            "tabLabel":   "Signature",
            "documentId": "1",
            "pageNumber": str(last["page_number"]),
            "xPosition":  str(sig_x),
            "yPosition":  str(sig_y),
            "width":      "150",
            "height":     "40"
        })
        date_signed_tabs.append({
            "tabLabel":   "Date_Signed",
            "documentId": "1",
            "pageNumber": str(last["page_number"]),
            "xPosition":  str(min(sig_x + 160, 560)),
            "yPosition":  str(sig_y),
            "width":      "80",
            "height":     "40"
        })

    tabs = {}
    if text_tabs:        tabs["textTabs"]       = text_tabs
    if checkbox_tabs:    tabs["checkboxTabs"]   = checkbox_tabs
    if date_tabs:        tabs["dateTabs"]       = date_tabs
    if email_tabs:       tabs["emailTabs"]      = email_tabs
    if number_tabs:      tabs["numberTabs"]     = number_tabs
    if sign_here_tabs:   tabs["signHereTabs"]   = sign_here_tabs
    if date_signed_tabs: tabs["dateSignedTabs"] = date_signed_tabs

    total = sum(len(v) for v in tabs.values())
    print(f"Built {total} tab(s) across {len(set(f['page_number'] for f in fields))} page(s)")
    return tabs


# ---------------------------------------------------------------
# STEP 5: Authenticate via Authorization Code Grant
# ---------------------------------------------------------------
def get_docusign_token() -> tuple:
    integration_key = os.environ.get("DOCUSIGN_INTEGRATION_KEY")
    secret_key      = os.environ.get("DOCUSIGN_SECRET_KEY")
    auth_server     = "account-d.docusign.com"
    redirect_uri    = "http://localhost:8080/callback"

    auth_url = (
        f"https://{auth_server}/oauth/auth"
        f"?response_type=code"
        f"&scope=signature"
        f"&client_id={integration_key}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
    )
    print(f"\nOpening browser for DocuSign login...")
    webbrowser.open(auth_url)

    auth_code = None
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            params    = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            auth_code = params.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Login successful! You can close this tab and return to Terminal.")
        def log_message(self, *args): pass

    print("Waiting for browser login...")
    HTTPServer(("localhost", 8080), Handler).handle_request()

    credentials = base64.b64encode(f"{integration_key}:{secret_key}".encode()).decode()
    r = requests.post(
        f"https://{auth_server}/oauth/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded"
        },
        data={"grant_type": "authorization_code", "code": auth_code, "redirect_uri": redirect_uri}
    )
    if r.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {r.text}")

    token = r.json()["access_token"]
    print("Login successful!")

    r2       = requests.get(f"https://{auth_server}/oauth/userinfo",
                            headers={"Authorization": f"Bearer {token}"})
    accounts = r2.json().get("accounts", [])
    account  = next((a for a in accounts if a.get("is_default")), accounts[0])
    print(f"Account: {account['account_name']} ({account['account_id']})")
    return token, account["account_id"], account["base_uri"]


# ---------------------------------------------------------------
# STEP 6: Create DocuSign template from PDF + tabs
# ---------------------------------------------------------------
def create_template(summary_result: dict, tabs_per_recipient: dict,
                    token: str, account_id: str, base_uri: str) -> str:
    """
    Create a DocuSign template with up to 3 documents:
      Doc 1 = External summary (visible to all)
      Doc 2 = Internal context page (visible to internal recipients only)
      Doc 3 = Original document (visible to all)

    Uses DocuSign Document Visibility so each recipient only sees their pages.
    """
    print(f"\nCreating DocuSign template with document visibility...")

    recipients = summary_result["recipients"]
    ext_path   = summary_result["external_pdf"]
    int_path   = summary_result["internal_pdf"]
    orig_path  = summary_result["original_pdf"]
    offsets    = summary_result["page_offsets"]

    def enc(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    documents = [
        {"documentBase64": enc(ext_path),  "name": "Summary",
         "fileExtension": "pdf", "documentId": "1"},
        {"documentBase64": enc(int_path),  "name": "Internal Context",
         "fileExtension": "pdf", "documentId": "2"},
        {"documentBase64": enc(orig_path), "name": Path(orig_path).name,
         "fileExtension": "pdf", "documentId": "3"},
    ]

    signers = []
    for r in recipients:
        rid    = str(r["recipient_id"])
        offset = offsets.get(r["recipient_id"], 1)
        tabs   = shift_tabs_by_offset(
            tabs_per_recipient.get(r["recipient_id"], {}), offset)
        # Re-assign all tabs to documentId 3 (the original doc)
        for tab_list in tabs.values():
            for tab in tab_list:
                tab["documentId"] = "3"

        signer = {
            "roleName":     r.get("role", f"Signer {rid}"),
            "recipientId":  rid,
            "routingOrder": str(r.get("routing_order", rid)),
            "tabs":         tabs,
        }
        # Document visibility: internal sees docs 1+2+3, external sees 1+3
        if r.get("is_internal"):
            signer["excludedDocuments"] = []
        else:
            signer["excludedDocuments"] = [{"documentId": "2"}]

        signers.append(signer)

    template_def = {
        "name":        f"{Path(orig_path).stem} - Auto Template",
        "description": "Auto-generated by DocuSign Agent",
        "shared":      "false",
        "enforceSignerVisibility": "true",
        "documents":   documents,
        "recipients":  {"signers": signers},
    }

    r = requests.post(
        f"{base_uri}/restapi/v2.1/accounts/{account_id}/templates",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=template_def
    )
    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Template creation failed ({r.status_code}):\n{r.text}")

    template_id = r.json()["templateId"]
    print(f"Template created: {template_id}")
    return template_id


# ---------------------------------------------------------------
# STEP 7: Send envelope from template
# ---------------------------------------------------------------
def send_envelope_from_template(template_id: str, recipients: list,
                                  token: str, account_id: str, base_uri: str) -> str:
    """
    Send envelope from template to multiple recipients with routing order.
    recipients: list of {recipient_id, name, email, role, routing_order}
    """
    names = ", ".join(r["name"] for r in recipients)
    print(f"\nSending envelope to: {names}...")

    template_roles = []
    for r in recipients:
        template_roles.append({
            "name":         r["name"],
            "email":        r["email"],
            "roleName":     r.get("role", f"Signer {r['recipient_id']}"),
            "recipientId":  str(r["recipient_id"]),
            "routingOrder": str(r.get("routing_order", r["recipient_id"])),
        })

    envelope = {
        "templateId":    template_id,
        "emailSubject":  "Please review and sign the document",
        "emailBlurb":    "Please review, complete all fields, and sign the document.",
        "templateRoles": template_roles,
        "status":        "sent"
    }

    r = requests.post(
        f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=envelope
    )
    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Envelope send failed ({r.status_code}):\n{r.text}")

    envelope_id = r.json()["envelopeId"]
    print(f"Envelope sent! ID: {envelope_id}")
    print(f"  Track at: https://apps-d.docusign.com/send/manage")
    return envelope_id


# ---------------------------------------------------------------
# app.py-compatible wrappers
# (app.py passes a plain pdf_path string and flat signer args)
# ---------------------------------------------------------------
def _clamp_tabs_to_page_count(tabs: dict, pdf_path: str) -> dict:
    """Remove any tabs whose pageNumber exceeds the actual PDF page count."""
    try:
        from pypdf import PdfReader
        page_count = len(PdfReader(pdf_path).pages)
    except Exception:
        return tabs  # can't check — pass through unchanged
    print(f"   PDF has {page_count} page(s) — clamping tabs...")
    clamped = {}
    for tab_type, tab_list in tabs.items():
        valid = [t for t in tab_list if int(t.get("pageNumber", 1)) <= page_count]
        removed = len(tab_list) - len(valid)
        if removed:
            print(f"   Removed {removed} {tab_type} tab(s) with out-of-range page numbers")
        if valid:
            clamped[tab_type] = valid
    return clamped


def create_template(pdf_path: str, tabs: dict,
                    token: str, account_id: str, base_uri: str) -> str:
    """
    Simplified create_template for use by app.py.
    Creates a single-document template from a PDF file path + pre-built tabs.
    """
    print(f"\nCreating DocuSign template from {pdf_path}...")

    with open(pdf_path, "rb") as f:
        doc_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Clamp tabs to actual PDF page count before sending
    safe_tabs = _clamp_tabs_to_page_count(
        {k: v for k, v in (tabs or {}).items() if isinstance(v, list) and len(v) > 0},
        pdf_path
    )

    template_def = {
        "name":        f"{Path(pdf_path).stem} - Auto Template",
        "description": "Auto-generated by DocuSign Agent",
        "shared":      "false",
        "documents": [{
            "documentBase64": doc_b64,
            "name":           Path(pdf_path).name,
            "fileExtension":  "pdf",
            "documentId":     "1",
        }],
        "recipients": {
            "signers": [{
                "roleName":     "Signer",
                "recipientId":  "1",
                "routingOrder": "1",
                "tabs":         safe_tabs,
            }]
        },
        "emailSubject": "Please review and sign the document",
        "status":       "created",
    }

    r = requests.post(
        f"{base_uri}/restapi/v2.1/accounts/{account_id}/templates",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=template_def
    )
    if r.status_code not in [200, 201]:
        # Retry without tabs as last resort
        print(f"Template creation failed with tabs ({r.status_code}), retrying without tabs...")
        template_def["recipients"]["signers"][0].pop("tabs", None)
        r = requests.post(
            f"{base_uri}/restapi/v2.1/accounts/{account_id}/templates",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=template_def
        )
    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Template creation failed ({r.status_code}):\n{r.text}")

    template_id = r.json()["templateId"]
    print(f"Template created: {template_id}")
    return template_id


def send_envelope_from_template(template_id: str, signer_name: str, signer_email: str,
                                  token: str, account_id: str, base_uri: str) -> str:
    """
    Simplified send_envelope_from_template for use by app.py.
    Sends to a single signer by name and email.
    """
    print(f"\nSending envelope to {signer_name} <{signer_email}>...")

    envelope = {
        "templateId":   template_id,
        "emailSubject": "Please review and sign the document",
        "emailBlurb":   "Please review, complete all fields, and sign the document.",
        "templateRoles": [{
            "name":         signer_name,
            "email":        signer_email,
            "roleName":     "Signer",
            "recipientId":  "1",
            "routingOrder": "1",
        }],
        "status": "sent",
    }

    r = requests.post(
        f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=envelope
    )
    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Envelope send failed ({r.status_code}):\n{r.text}")

    envelope_id = r.json()["envelopeId"]
    print(f"Envelope sent! ID: {envelope_id}")
    return envelope_id


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
def main():
    if len(sys.argv) != 4:
        print("Usage: python3 docusign_agent.py <pdf_url_or_path> <signer_name> <signer_email>")
        print("\nExamples:")
        print('  python3 docusign_agent.py https://example.com/form.pdf "John Smith" "john@example.com"')
        print('  python3 docusign_agent.py /Users/you/Desktop/form.pdf "John Smith" "john@example.com"')
        sys.exit(1)

    pdf_source   = sys.argv[1]
    signer_name  = sys.argv[2]
    signer_email = sys.argv[3]

    for var in ["DOCUSIGN_INTEGRATION_KEY", "DOCUSIGN_SECRET_KEY"]:
        if not os.environ.get(var):
            print(f"Missing environment variable: {var}")
            print(f"  Run: export {var}='your-value'")
            sys.exit(1)

    images_dir = "docusign_form_images"

    try:
        # Detect fields
        pdf_path    = load_pdf(pdf_source)
        image_paths = convert_pdf_to_images(pdf_path, images_dir)
        fields_data = detect_fields_with_claude(image_paths)

        with open("fields.json", "w") as f:
            json.dump(fields_data, f, indent=2)
        print(f"Field data saved to fields.json")

        # Build tabs using original pixel coordinate approach
        tabs = build_docusign_tabs(fields_data)

        # Generate 1-page summary and prepend it to the PDF
        # (happens after field detection so we reuse the already-converted images)
        pdf_path = generate_and_prepend_summary(pdf_path, image_paths)

        # Shift all tab page numbers by 1 to account for the new summary page
        tabs = shift_tabs_for_summary_page(tabs)

        # Authenticate once, reuse token for both template + envelope
        token, account_id, base_uri = get_docusign_token()

        # Create template then send envelope from it
        template_id = create_template(pdf_path, tabs, token, account_id, base_uri)
        send_envelope_from_template(template_id, signer_name, signer_email,
                                    token, account_id, base_uri)

        print(f"\nDone! {signer_name} will receive an email to fill and sign.")

    finally:
        if Path(images_dir).exists():
            shutil.rmtree(images_dir)


if __name__ == "__main__":
    main()
