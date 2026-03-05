"""
document_summary.py  —  Per-Recipient Document Summary Skill

Generates tailored summary PDFs for each recipient:
  - External signer -> 1-page summary (facts grounded in real tab/recipient data)
  - Internal signer -> 2-page summary (external page + internal context page)

Internal vs external: compare recipient email domain against the sender's DocuSign login email.

Summary generated AFTER template creation so recipient/tab data is fully resolved.

Context sources for internal page (with placeholders for Slack/Salesforce):
  - Custom notes typed by sender in UI
  - DocuSign envelope history for this recipient
  - Slack (set SLACK_BOT_TOKEN to enable)
  - Salesforce (set SALESFORCE_ACCESS_TOKEN to enable)
"""

import anthropic
import base64
import json
import os
import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

BLUE  = HexColor("#1A56DB")
DARK  = HexColor("#111827")
MUTED = HexColor("#9CA3AF")
GREEN = HexColor("#166534")
GBG   = HexColor("#ECFDF5")
GBDR  = HexColor("#A7F3D0")
PILL  = HexColor("#EEF2FF")
AMBER = HexColor("#B45309")
AMBG  = HexColor("#FFFBEB")
W, H  = letter
M     = 0.55 * inch
CW    = W - 2 * M


def _wrap(cv, text, font, size, max_w):
    words = str(text).split()
    lines, line = [], []
    for w in words:
        test = " ".join(line + [w])
        if cv.stringWidth(test, font, size) <= max_w:
            line.append(w)
        else:
            if line: lines.append(" ".join(line))
            line = [w]
    if line: lines.append(" ".join(line))
    return lines


def _draw_wrapped(cv, text, x, y, font, size, color, max_w, line_h=None):
    if line_h is None: line_h = size + 3
    lines = _wrap(cv, text, font, size, max_w)
    cv.setFont(font, size)
    cv.setFillColor(color)
    for l in lines:
        cv.drawString(x, y, l)
        y -= line_h
    return y


def _is_internal(recipient_email: str, sender_email: str) -> bool:
    """Compare recipient domain against sender's DocuSign login email domain."""
    if not sender_email or "@" not in sender_email:
        return False
    return (recipient_email.split("@")[-1].lower() ==
            sender_email.split("@")[-1].lower())


def _analyse_document(image_paths):
    print("  [Summary] Analysing document with Claude...")
    client  = anthropic.Anthropic()
    content = []
    for img_path in image_paths:
        with open(img_path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/png", "data": data}})
    content.append({"type": "text", "text": """Analyse this document.
Return ONLY JSON (no markdown):
{
  "doc_type": "Short type e.g. Offer Letter / NDA / Lease / SEC Filing",
  "purpose": "Max 2 sentences. What is this and what does signing accomplish?",
  "key_terms": [{"label": "Term", "value": "Max 6 words, complete phrase"}]
}
Extract 8-10 key terms most critical for a signer. Never truncate values.
Use 'Not specified' only if truly absent."""})
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        messages=[{"role": "user", "content": content}])
    raw = re.sub(r"```[a-z]*\n?", "", resp.content[0].text.strip()).replace("```", "").strip()
    try:
        r = json.loads(raw)
        print(f"  [Summary] {r.get('doc_type')}, {len(r.get('key_terms', []))} terms")
        return r
    except Exception:
        return {"doc_type": "Document", "purpose": "Review before signing.", "key_terms": []}


def _get_ds_history(email, token, account_id, base_uri):
    if not token: return []
    try:
        import requests
        r = requests.get(
            f"{base_uri}/restapi/v2.1/accounts/{account_id}/envelopes"
            f"?count=5&from_date=2020-01-01&status=completed",
            headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200: return []
        out = []
        for env in r.json().get("envelopes", []):
            r2 = requests.get(
                f"{base_uri}/restapi/v2.1/accounts/{account_id}"
                f"/envelopes/{env['envelopeId']}/recipients",
                headers={"Authorization": f"Bearer {token}"})
            if r2.status_code == 200:
                for s in r2.json().get("signers", []):
                    if s.get("email", "").lower() == email.lower():
                        out.append({"envelope_id": env["envelopeId"],
                                    "subject": env.get("emailSubject", "")[:60],
                                    "status": env.get("status", ""),
                                    "sent": (env.get("sentDateTime") or "")[:10]})
                        break
        return out[:3]
    except Exception as e:
        print(f"  [Summary] DS history error: {e}"); return []


def _get_slack_context(email, doc_type):
    if not os.environ.get("SLACK_BOT_TOKEN"): return []
    return []  # TODO: implement Slack search


def _get_sf_context(email):
    if not os.environ.get("SALESFORCE_ACCESS_TOKEN"): return {}
    return {}  # TODO: implement Salesforce lookup


def _render_external_page(out_path, doc_info, recipient, tabs):
    cv = canvas.Canvas(out_path, pagesize=letter)
    y  = H - M

    tab_counts = {}
    total_tabs = 0
    for tab_type, tab_list in tabs.items():
        if tab_list:
            label = (tab_type.replace("Tabs", "").replace("signHere", "Signature")
                     .replace("text", "Text").replace("dateSigned", "Date Signed")
                     .replace("date", "Date").replace("checkbox", "Checkbox")
                     .replace("initial", "Initial").replace("email", "Email")
                     .replace("number", "Number"))
            tab_counts[label] = len(tab_list)
            total_tabs += len(tab_list)

    # Pill badge
    pill_text = doc_info.get("doc_type", "Document").upper()
    pill_w    = cv.stringWidth(pill_text, "Helvetica-Bold", 7) + 16
    cv.setFillColor(PILL); cv.roundRect(M, y - 2, pill_w, 16, 8, fill=1, stroke=0)
    cv.setFont("Helvetica-Bold", 7); cv.setFillColor(BLUE)
    cv.drawString(M + 8, y + 4, pill_text)
    y -= 24

    # Title
    cv.setFont("Helvetica-Bold", 26); cv.setFillColor(DARK)
    cv.drawString(M, y, "Document Summary"); y -= 32

    # Purpose
    y = _draw_wrapped(cv, doc_info.get("purpose", ""), M, y,
                      "Helvetica-Oblique", 9, MUTED, CW, 14); y -= 10

    # Divider
    cv.setStrokeColor(BLUE); cv.setLineWidth(1.5); cv.line(M, y, W - M, y); y -= 16

    # Recipient info
    cv.setFont("Helvetica-Bold", 7); cv.setFillColor(BLUE)
    cv.drawString(M, y, "SENT TO"); y -= 13
    cv.setFont("Helvetica-Bold", 11); cv.setFillColor(DARK)
    cv.drawString(M, y, recipient.get("name", "")); y -= 13
    cv.setFont("Helvetica", 9); cv.setFillColor(MUTED)
    parts = [recipient.get("email", "")]
    if recipient.get("role"): parts.append(f"Role: {recipient['role']}")
    parts.append(f"Signing order: {recipient.get('routing_order', 1)}")
    cv.drawString(M, y, "  ·  ".join(parts)); y -= 18

    # Your role box
    cv.setFont("Helvetica-Bold", 7); cv.setFillColor(BLUE)
    cv.drawString(M, y, "YOUR ROLE AS SIGNER"); y -= 11

    role_rows = []
    if total_tabs:
        fields_str = ", ".join(f"{v} {k}" for k, v in tab_counts.items())
        role_rows.append(("Fields to complete:", f"{total_tabs} total — {fields_str}"))
    if recipient.get("role"):
        role_rows.append(("Signing as:", recipient["role"]))
    role_rows.append(("Your action:", "Review all fields, complete them, then sign"))

    box_h = len(role_rows) * 20 + 16
    cv.setFillColor(GBG); cv.setStrokeColor(GBDR); cv.setLineWidth(0.5)
    cv.roundRect(M, y - box_h + 6, CW, box_h, 6, fill=1, stroke=1)
    ry = y - 8
    for lbl, val in role_rows:
        cv.setFont("Helvetica-Bold", 8.5); cv.setFillColor(GREEN)
        cv.drawString(M + 10, ry, lbl)
        lw = cv.stringWidth(lbl, "Helvetica-Bold", 8.5)
        cv.setFont("Helvetica", 8.5); cv.setFillColor(DARK)
        cv.drawString(M + 10 + lw + 5, ry, val)
        ry -= 20
    y -= box_h + 10

    # Divider
    cv.setStrokeColor(HexColor("#E5E7EB")); cv.setLineWidth(0.5)
    cv.line(M, y, W - M, y); y -= 14

    # Key terms
    key_terms = doc_info.get("key_terms", [])
    if key_terms:
        cv.setFont("Helvetica-Bold", 7); cv.setFillColor(BLUE)
        cv.drawString(M, y, "KEY TERMS"); y -= 12
        col_w = CW / 2 - 8; cell_h = 26
        for i in range(0, len(key_terms), 2):
            left  = key_terms[i]
            right = key_terms[i + 1] if i + 1 < len(key_terms) else None
            if (i // 2) % 2 == 0:
                cv.setFillColor(HexColor("#FAFAFA"))
                cv.rect(M, y - cell_h + 6, CW, cell_h, fill=1, stroke=0)
            cv.setFont("Helvetica-Bold", 7); cv.setFillColor(MUTED)
            cv.drawString(M + 4, y, str(left.get("label", "")).upper())
            cv.setFont("Helvetica", 9); cv.setFillColor(DARK)
            cv.drawString(M + 4, y - 13, str(left.get("value", "")))
            if right:
                rx = M + col_w + 16
                cv.setFont("Helvetica-Bold", 7); cv.setFillColor(MUTED)
                cv.drawString(rx, y, str(right.get("label", "")).upper())
                cv.setFont("Helvetica", 9); cv.setFillColor(DARK)
                cv.drawString(rx, y - 13, str(right.get("value", "")))
            cv.setStrokeColor(HexColor("#F3F4F6")); cv.setLineWidth(0.4)
            cv.line(M, y - cell_h + 6, W - M, y - cell_h + 6)
            y -= cell_h

    footer = "Auto-generated by Claude AI. Review the full document before signing."
    cv.setFont("Helvetica-Oblique", 7); cv.setFillColor(MUTED)
    fw = cv.stringWidth(footer, "Helvetica-Oblique", 7)
    cv.drawString((W - fw) / 2, M + 4, footer)
    cv.save()
    print(f"  [Summary] External page rendered")


def _render_internal_page(out_path, recipient, doc_info, notes,
                           ds_history, slack_msgs, sf_context):
    cv = canvas.Canvas(out_path, pagesize=letter)
    y  = H - M

    # Amber header bar
    cv.setFillColor(AMBG); cv.rect(0, H - 52, W, 52, fill=1, stroke=0)
    cv.setFont("Helvetica-Bold", 7); cv.setFillColor(AMBER)
    cv.drawString(M, H - 16, "INTERNAL USE ONLY — NOT FOR EXTERNAL DISTRIBUTION")
    cv.setFont("Helvetica-Bold", 18); cv.setFillColor(DARK)
    cv.drawString(M, H - 38, "Internal Context Summary")
    y = H - 66

    cv.setFont("Helvetica", 9); cv.setFillColor(MUTED)
    cv.drawString(M, y, f"Prepared for: {recipient.get('name','')}  ·  {recipient.get('email','')}"); y -= 18
    cv.setStrokeColor(AMBER); cv.setLineWidth(1.5); cv.line(M, y, W - M, y); y -= 16

    def section(title):
        nonlocal y
        cv.setFont("Helvetica-Bold", 7); cv.setFillColor(AMBER)
        cv.drawString(M, y, title); y -= 13

    # Notes
    section("SENDER NOTES")
    if notes and notes.strip():
        note_lines = _wrap(cv, notes.strip(), "Helvetica", 9.5, CW - 20)
        note_h = len(note_lines) * 14 + 14
        cv.setFillColor(AMBG); cv.roundRect(M, y - note_h + 6, CW, note_h, 4, fill=1, stroke=0)
        ny = y - 8
        cv.setFont("Helvetica", 9.5); cv.setFillColor(DARK)
        for l in note_lines:
            cv.drawString(M + 10, ny, l); ny -= 14
        y -= note_h + 8
    else:
        cv.setFont("Helvetica-Oblique", 9); cv.setFillColor(MUTED)
        cv.drawString(M, y, "No notes provided by sender."); y -= 14
    y -= 6

    # DS History
    section("DOCUSIGN ENVELOPE HISTORY WITH THIS RECIPIENT")
    if ds_history:
        for env in ds_history:
            cv.setFont("Helvetica-Bold", 9); cv.setFillColor(DARK)
            cv.drawString(M + 4, y, f"• {env.get('subject', 'Untitled')}")
            cv.setFont("Helvetica", 8); cv.setFillColor(MUTED)
            cv.drawString(M + 14, y - 11,
                f"Status: {env.get('status')}  ·  Sent: {env.get('sent')}  ·  "
                f"ID: {env.get('envelope_id','')[:16]}...")
            y -= 26
    else:
        cv.setFont("Helvetica-Oblique", 9); cv.setFillColor(MUTED)
        cv.drawString(M, y, "No prior envelopes found for this recipient."); y -= 14
    y -= 6

    # Slack — only render if SLACK_BOT_TOKEN is set and returned data
    if slack_msgs:
        section("SLACK CONTEXT")
        for msg in slack_msgs[:3]:
            cv.setFont("Helvetica-Bold", 8); cv.setFillColor(DARK)
            cv.drawString(M + 4, y, f"#{msg.get('channel')}  ·  {msg.get('user')}  ·  {msg.get('date')}")
            y -= 12
            for l in _wrap(cv, msg.get("text", ""), "Helvetica", 8.5, CW - 20)[:2]:
                cv.setFont("Helvetica", 8.5); cv.setFillColor(DARK)
                cv.drawString(M + 14, y, l); y -= 12
            y -= 4
        y -= 6

    # Salesforce — only render if SALESFORCE_ACCESS_TOKEN is set and returned data
    if sf_context:
        section("SALESFORCE CONTEXT")
        for lbl, val in [("Contact", sf_context.get("contact_name")),
                         ("Account", sf_context.get("account")),
                         ("Opportunity", sf_context.get("opportunity")),
                         ("Stage", sf_context.get("stage")),
                         ("Amount", sf_context.get("amount"))]:
            if val:
                cv.setFont("Helvetica-Bold", 8); cv.setFillColor(MUTED)
                cv.drawString(M + 4, y, lbl.upper())
                lw = cv.stringWidth(lbl.upper(), "Helvetica-Bold", 8)
                cv.setFont("Helvetica", 9); cv.setFillColor(DARK)
                cv.drawString(M + 4 + lw + 8, y, str(val)); y -= 14

    footer = "INTERNAL DOCUMENT — Auto-generated by Claude AI for internal use only."
    cv.setFont("Helvetica-Oblique", 7); cv.setFillColor(MUTED)
    fw = cv.stringWidth(footer, "Helvetica-Oblique", 7)
    cv.drawString((W - fw) / 2, M + 4, footer)
    cv.save()
    print(f"  [Summary] Internal page rendered")


def generate_summaries(original_pdf, image_paths, recipients,
                       tabs_per_recipient, sender_email="",
                       token=None, account_id=None, base_uri=None):
    """
    Generate per-recipient summary PDFs.

    recipients: list of dicts with keys:
      recipient_id, name, email, role, routing_order, notes

    tabs_per_recipient: {recipient_id: tabs_dict}

    Returns:
      external_pdf, internal_pdf, original_pdf,
      recipients (with is_internal added),
      page_offsets {recipient_id: int},
      doc_info
    """
    print("\n[Summary Skill] Generating summaries...")
    base    = Path(original_pdf)
    tmp_dir = base.parent

    doc_info = _analyse_document(image_paths)

    # External page — use first recipient's real tabs
    first_r    = recipients[0] if recipients else {}
    first_tabs = tabs_per_recipient.get(first_r.get("recipient_id", "1"), {})
    ext_path   = str(tmp_dir / (base.stem + "_ext_summary.pdf"))
    _render_external_page(ext_path, doc_info, first_r, first_tabs)

    # Internal context page — use first internal recipient
    int_path  = str(tmp_dir / (base.stem + "_int_context.pdf"))
    int_recip = next((r for r in recipients if _is_internal(r.get("email", ""), sender_email)), {})
    ds_hist   = _get_ds_history(int_recip.get("email", ""), token, account_id, base_uri) if int_recip and token else []
    slack     = _get_slack_context(int_recip.get("email", ""), doc_info.get("doc_type", ""))
    sf        = _get_sf_context(int_recip.get("email", ""))
    _render_internal_page(int_path, int_recip, doc_info,
                          int_recip.get("notes", "") if int_recip else "",
                          ds_hist, slack, sf)

    # Tag each recipient + compute page offsets
    page_offsets = {}
    for r in recipients:
        r["is_internal"]             = _is_internal(r.get("email", ""), sender_email)
        page_offsets[r["recipient_id"]] = 2 if r["is_internal"] else 1

    print("[Summary Skill] Done")
    return {
        "external_pdf":         ext_path,
        "internal_pdf":         int_path,
        "original_pdf":         original_pdf,
        "recipients":           recipients,
        "page_offsets":         page_offsets,
        "doc_info":             doc_info,
    }
