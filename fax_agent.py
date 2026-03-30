"""
fax_agent.py — Healthcare Fax Automation Agent

Pipeline:
1. Classify document using medical-document-classifier skill
2. Determine follow-up actions using medical-followup-actions skill
3. If signature required: detect fields, build DocuSign tabs, send envelope
"""

import anthropic
import base64
import json
import os
import uuid
from pathlib import Path

from claude_detect_fields import convert_pdf_to_images, detect_fields_with_claude
from docusign_agent import build_docusign_tabs, create_template, send_envelope_from_template

ACCEPTED_TYPES = {
    "Durable Medical Equipment",
    "Home Health",
    "Prescription",
    "Prior Authorization",
    "Medical Record Request",
    "Legal Acknowledgement Document",
}

CLASSIFIER_PROMPT = """You are a medical document classifier.

Classify this healthcare document into one of these types:
- Durable Medical Equipment
- Home Health
- Prescription
- Prior Authorization
- Medical Record Request
- Legal Acknowledgement Document
- Unclassified

Return ONLY a JSON object, no markdown, no explanation:
{
  "type": "<document type or 'Unclassified'>",
  "confidence": "<High | Medium | Low>",
  "reasoning": "<1-3 sentences explaining key signals>"
}"""

FOLLOWUP_PROMPT = """You are a medical document follow-up action analyzer.

The document has been classified as: {doc_type}

Based on the document content, determine the required follow-up actions.

Return ONLY a JSON object, no markdown, no explanation:
{{
  "document_type": "{doc_type}",
  "follow_up_required": true,
  "actions": {{
    "status": {{ <type-specific extracted status fields> }},
    "signatures": {{
      "required": true | false,
      "type": "<description of what signature is needed, or null>",
      "routing_department": "<department name, or null>",
      "recipient_name": "<name extracted from document if present, or null>",
      "recipient_email": "<email extracted from document if present, or null>"
    }},
    "routing": {{
      "department": "<primary department>",
      "reason": "<one sentence why>"
    }}
  }}
}}

For signatures: look carefully for any physician name, provider name, email addresses, or contact info
in the document that would indicate WHO needs to sign. Extract recipient_name and recipient_email
if they appear anywhere in the document."""


def classify_document(pdf_b64: str, filename: str) -> dict:
    """Run medical-document-classifier skill on the PDF."""
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": CLASSIFIER_PROMPT}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def get_followup_actions(pdf_b64: str, doc_type: str) -> dict:
    """Run medical-followup-actions skill on the classified document."""
    client = anthropic.Anthropic()

    prompt = FOLLOWUP_PROMPT.format(doc_type=doc_type)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def send_fax_envelope(pdf_b64: str, filename: str,
                      signer_name: str, signer_email: str,
                      token: str, account_id: str, base_uri: str,
                      upload_dir: Path) -> dict:
    """
    Full pipeline: save PDF → detect fields → build tabs → create template → send envelope.
    Reuses existing docusign_agent functions.
    """
    # 1. Save PDF to disk
    pdf_path = upload_dir / f"{uuid.uuid4()}_{filename}"
    with open(str(pdf_path), "wb") as f:
        f.write(base64.b64decode(pdf_b64))

    # 2. Convert to images & detect fields
    images_dir = str(upload_dir / "fax_images")
    image_paths = convert_pdf_to_images(str(pdf_path), images_dir)
    fields_data = detect_fields_with_claude(image_paths)

    # 3. Build DocuSign tabs
    tabs = build_docusign_tabs(fields_data)

    # 4. Create template
    template_id = create_template(str(pdf_path), tabs, token, account_id, base_uri)

    # 5. Send envelope
    envelope_id = send_envelope_from_template(
        template_id, signer_name, signer_email, token, account_id, base_uri
    )

    return {
        "envelope_id": envelope_id,
        "template_id": template_id,
        "fields_detected": len(fields_data.get("form_fields", [])),
    }
