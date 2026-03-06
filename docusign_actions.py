"""
docusign_actions.py — Full Docusign eSign REST API v2.1 tool surface

All resource categories from:
  https://developers.docusign.com/docs/esign-rest-api/reference/

Categories:
  Envelopes              — list, get, create, void, resend, correct, audit, form data
  EnvelopeDocuments      — list, get info
  EnvelopeRecipients     — list, add, delete
  EnvelopeRecipientTabs  — list, update
  EnvelopeCustomFields   — list, create
  EnvelopeLocks          — get, create, delete
  Templates              — list, get, create, delete, send
  TemplateDocuments      — list, get info
  TemplateRecipients     — list, add, delete
  TemplateRecipientTabs  — list, create, update, delete
  TemplateCustomFields   — list
  TemplateLocks          — get
  Folders                — list, list items, move envelope
  SigningGroups          — list, get, list users
  Accounts               — get info, get settings
  Users                  — list, get, get profile
  BulkEnvelopes          — list batches, get batch
  CustomTabs             — list
"""

import requests


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _url(base_uri, account_id, path):
    return f"{base_uri}/restapi/v2.1/accounts/{account_id}{path}"

def _get(token, base_uri, account_id, path, params=None):
    r = requests.get(_url(base_uri, account_id, path), headers=_h(token), params=params, timeout=20)
    return r.json() if r.ok else {"error": r.text, "status_code": r.status_code}

def _post(token, base_uri, account_id, path, body):
    r = requests.post(_url(base_uri, account_id, path), headers=_h(token), json=body, timeout=20)
    return r.json() if r.ok else {"error": r.text, "status_code": r.status_code}

def _put(token, base_uri, account_id, path, body):
    r = requests.put(_url(base_uri, account_id, path), headers=_h(token), json=body, timeout=20)
    return r.json() if r.ok else {"error": r.text, "status_code": r.status_code}

def _delete(token, base_uri, account_id, path, body=None):
    r = requests.delete(_url(base_uri, account_id, path), headers=_h(token), json=body, timeout=20)
    if r.status_code == 204:
        return {"success": True}
    return r.json() if r.ok else {"error": r.text, "status_code": r.status_code}


# ══════════════════════════════════════════════════════════════
# ENVELOPES
# ══════════════════════════════════════════════════════════════

def list_envelopes(token, account_id, base_uri,
                   count=10, status="sent", from_date="2020-01-01", search_text=None):
    """List recent envelopes. status: sent|delivered|completed|declined|voided|any"""
    params = {"count": count, "from_date": from_date, "status": status}
    if search_text:
        params["search_text"] = search_text
    data = _get(token, base_uri, account_id, "/envelopes", params)
    if "error" in data:
        return data
    envs = data.get("envelopes", [])
    return {
        "total": data.get("totalSetSize", len(envs)),
        "envelopes": [{
            "envelope_id":   e.get("envelopeId"),
            "subject":       e.get("emailSubject"),
            "status":        e.get("status"),
            "sent_date":     e.get("sentDateTime"),
            "last_modified": e.get("lastModifiedDateTime"),
            "completed":     e.get("completedDateTime"),
        } for e in envs]
    }

def get_envelope(token, account_id, base_uri, envelope_id):
    """Get full details and recipients of an envelope."""
    env = _get(token, base_uri, account_id, f"/envelopes/{envelope_id}")
    if "error" in env:
        return env
    recip = _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/recipients")
    return {**env, "recipients_detail": recip}

def void_envelope(token, account_id, base_uri, envelope_id, reason="Voided by sender"):
    """Void a sent envelope."""
    r = _put(token, base_uri, account_id, f"/envelopes/{envelope_id}",
             {"status": "voided", "voidedReason": reason})
    return {"success": True, "envelope_id": envelope_id, "status": "voided"} if "error" not in r else r

def resend_envelope(token, account_id, base_uri, envelope_id):
    """Resend reminder to all pending recipients."""
    r = _put(token, base_uri, account_id, f"/envelopes/{envelope_id}", {"resendEnvelope": True})
    return {"success": True, "message": "Reminder sent"} if "error" not in r else r

def correct_envelope(token, account_id, base_uri, envelope_id,
                     recipient_id, new_email=None, new_name=None):
    """Correct a recipient's email or name on a sent envelope."""
    signer = {"recipientId": recipient_id}
    if new_email: signer["email"] = new_email
    if new_name:  signer["name"] = new_name
    return _put(token, base_uri, account_id, f"/envelopes/{envelope_id}/recipients",
                {"signers": [signer]})

def get_envelope_audit_events(token, account_id, base_uri, envelope_id):
    """Get the full audit trail for an envelope."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/audit_events")

def get_envelope_form_data(token, account_id, base_uri, envelope_id):
    """Get all tab/field values filled by recipients in a completed envelope."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/form_data")

def create_and_send_envelope(token, account_id, base_uri,
                              signer_name, signer_email, subject, message=""):
    """Create a simple plain-text envelope and send it immediately."""
    body = {
        "emailSubject": subject,
        "emailBlurb": message,
        "recipients": {"signers": [{
            "name": signer_name, "email": signer_email,
            "recipientId": "1", "routingOrder": "1",
        }]},
        "status": "sent",
    }
    r = _post(token, base_uri, account_id, "/envelopes", body)
    if "error" in r:
        return r
    return {"success": True, "envelope_id": r.get("envelopeId"), "status": "sent"}


# ══════════════════════════════════════════════════════════════
# ENVELOPE DOCUMENTS
# ══════════════════════════════════════════════════════════════

def list_envelope_documents(token, account_id, base_uri, envelope_id):
    """List all documents in an envelope with metadata (name, pages, size)."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/documents")

def get_envelope_document_info(token, account_id, base_uri, envelope_id, document_id):
    """Get metadata for a specific document in an envelope. Use 'combined' for merged PDF."""
    return _get(token, base_uri, account_id,
                f"/envelopes/{envelope_id}/documents/{document_id}")

def delete_envelope_documents(token, account_id, base_uri, envelope_id, document_ids):
    """Delete one or more documents from a draft envelope.
    document_ids: list of document ID strings e.g. ['1','2']"""
    body = {"documents": [{"documentId": did} for did in document_ids]}
    return _delete(token, base_uri, account_id,
                   f"/envelopes/{envelope_id}/documents", body)

def get_envelope_document_fields(token, account_id, base_uri, envelope_id, document_id):
    """Get custom document fields (metadata) for a document in an envelope."""
    return _get(token, base_uri, account_id,
                f"/envelopes/{envelope_id}/documents/{document_id}/fields")

def create_envelope_document_fields(token, account_id, base_uri, envelope_id,
                                     document_id, document_fields):
    """Create custom document fields on an envelope document.
    document_fields: list of {name, value} objects."""
    return _post(token, base_uri, account_id,
                 f"/envelopes/{envelope_id}/documents/{document_id}/fields",
                 {"documentFields": document_fields})

def update_envelope_document_fields(token, account_id, base_uri, envelope_id,
                                     document_id, document_fields):
    """Update custom document fields on an envelope document."""
    return _put(token, base_uri, account_id,
                f"/envelopes/{envelope_id}/documents/{document_id}/fields",
                {"documentFields": document_fields})

def delete_envelope_document_fields(token, account_id, base_uri, envelope_id,
                                     document_id, document_fields):
    """Delete specific custom document fields from an envelope document."""
    return _delete(token, base_uri, account_id,
                   f"/envelopes/{envelope_id}/documents/{document_id}/fields",
                   {"documentFields": document_fields})


# ══════════════════════════════════════════════════════════════
# ENVELOPE RECIPIENTS
# ══════════════════════════════════════════════════════════════

def list_envelope_recipients(token, account_id, base_uri, envelope_id):
    """List all recipients of an envelope with status."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/recipients")

def add_envelope_recipient(token, account_id, base_uri, envelope_id,
                           name, email, routing_order=1, recipient_type="signers"):
    """Add a recipient to an existing envelope. recipient_type: signers|carbonCopies|certifiedDeliveries"""
    body = {recipient_type: [{
        "name": name, "email": email,
        "recipientId": "99", "routingOrder": str(routing_order),
    }]}
    return _post(token, base_uri, account_id, f"/envelopes/{envelope_id}/recipients", body)

def delete_envelope_recipient(token, account_id, base_uri, envelope_id, recipient_id):
    """Remove a recipient from an envelope."""
    return _delete(token, base_uri, account_id, f"/envelopes/{envelope_id}/recipients",
                   {"signers": [{"recipientId": recipient_id}]})


# ══════════════════════════════════════════════════════════════
# ENVELOPE RECIPIENT TABS
# ══════════════════════════════════════════════════════════════

def list_envelope_recipient_tabs(token, account_id, base_uri, envelope_id, recipient_id):
    """List all tabs (fields) assigned to a recipient in an envelope."""
    return _get(token, base_uri, account_id,
                f"/envelopes/{envelope_id}/recipients/{recipient_id}/tabs")

def update_envelope_recipient_tabs(token, account_id, base_uri,
                                    envelope_id, recipient_id, tabs):
    """Update tab values for a recipient. tabs: e.g. {'textTabs':[{'tabId':'x','value':'y'}]}"""
    return _put(token, base_uri, account_id,
                f"/envelopes/{envelope_id}/recipients/{recipient_id}/tabs", tabs)


# ══════════════════════════════════════════════════════════════
# ENVELOPE CUSTOM FIELDS
# ══════════════════════════════════════════════════════════════

def list_envelope_custom_fields(token, account_id, base_uri, envelope_id):
    """List custom metadata fields on an envelope."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/custom_fields")

def create_envelope_custom_fields(token, account_id, base_uri, envelope_id, text_custom_fields):
    """Add custom fields to an envelope. text_custom_fields: [{name, value, required, show}]"""
    return _post(token, base_uri, account_id, f"/envelopes/{envelope_id}/custom_fields",
                 {"textCustomFields": text_custom_fields})


# ══════════════════════════════════════════════════════════════
# ENVELOPE LOCKS
# ══════════════════════════════════════════════════════════════

def get_envelope_lock(token, account_id, base_uri, envelope_id):
    """Get lock information for an envelope being edited."""
    return _get(token, base_uri, account_id, f"/envelopes/{envelope_id}/lock")

def create_envelope_lock(token, account_id, base_uri, envelope_id,
                          lock_duration_in_seconds=300):
    """Lock an envelope for editing."""
    return _post(token, base_uri, account_id, f"/envelopes/{envelope_id}/lock",
                 {"lockType": "edit", "lockDurationInSeconds": str(lock_duration_in_seconds)})

def delete_envelope_lock(token, account_id, base_uri, envelope_id):
    """Release the lock on an envelope."""
    return _delete(token, base_uri, account_id, f"/envelopes/{envelope_id}/lock")


# ══════════════════════════════════════════════════════════════
# TEMPLATES
# ══════════════════════════════════════════════════════════════

def list_templates(token, account_id, base_uri,
                   count=20, search_text=None, folder_id=None):
    """List templates in the account."""
    params = {"count": count}
    if search_text: params["search_text"] = search_text
    if folder_id:   params["folder_id"] = folder_id
    data = _get(token, base_uri, account_id, "/templates", params)
    if "error" in data:
        return data
    templates = data.get("envelopeTemplates", [])
    return {
        "total": data.get("totalSetSize", len(templates)),
        "templates": [{
            "template_id": t.get("templateId"),
            "name":        t.get("name"),
            "description": t.get("description"),
            "created":     t.get("created"),
            "last_used":   t.get("lastUsed"),
            "shared":      t.get("shared"),
            "owner_email": t.get("owner", {}).get("email"),
        } for t in templates]
    }

def get_template(token, account_id, base_uri, template_id):
    """Get full details of a template including documents, recipients, and tabs."""
    return _get(token, base_uri, account_id, f"/templates/{template_id}")

def delete_template(token, account_id, base_uri, template_id):
    """Delete a template."""
    return _delete(token, base_uri, account_id, f"/templates/{template_id}")

def send_from_template(token, account_id, base_uri,
                       template_id, signer_name, signer_email,
                       subject=None, role_name="Signer"):
    """Send an envelope from a template."""
    r = _post(token, base_uri, account_id, "/envelopes", {
        "templateId": template_id,
        "emailSubject": subject or "Please review and sign this document",
        "templateRoles": [{
            "name": signer_name, "email": signer_email,
            "roleName": role_name, "recipientId": "1",
        }],
        "status": "sent",
    })
    if "error" in r:
        return r
    return {"success": True, "envelope_id": r.get("envelopeId"), "status": "sent",
            "recipient": f"{signer_name} <{signer_email}>"}


# ══════════════════════════════════════════════════════════════
# TEMPLATE DOCUMENTS
# ══════════════════════════════════════════════════════════════

def list_template_documents(token, account_id, base_uri, template_id):
    """List all documents attached to a template with metadata (name, pages, size)."""
    return _get(token, base_uri, account_id, f"/templates/{template_id}/documents")

def get_template_document_info(token, account_id, base_uri, template_id, document_id):
    """Get PDF or metadata for a document in a template. Use 'combined' for all pages merged."""
    return _get(token, base_uri, account_id,
                f"/templates/{template_id}/documents/{document_id}")

def delete_template_documents(token, account_id, base_uri, template_id, document_ids):
    """Delete one or more documents from a template.
    document_ids: list of document ID strings e.g. ['1','2']"""
    body = {"documents": [{"documentId": did} for did in document_ids]}
    return _delete(token, base_uri, account_id,
                   f"/templates/{template_id}/documents", body)

def get_template_document_fields(token, account_id, base_uri, template_id, document_id):
    """Get custom document fields (metadata) for a document in a template."""
    return _get(token, base_uri, account_id,
                f"/templates/{template_id}/documents/{document_id}/fields")

def create_template_document_fields(token, account_id, base_uri, template_id,
                                     document_id, document_fields):
    """Create custom document fields on a template document.
    document_fields: list of {name, value} objects."""
    return _post(token, base_uri, account_id,
                 f"/templates/{template_id}/documents/{document_id}/fields",
                 {"documentFields": document_fields})

def update_template_document_fields(token, account_id, base_uri, template_id,
                                     document_id, document_fields):
    """Update custom document fields on a template document."""
    return _put(token, base_uri, account_id,
                f"/templates/{template_id}/documents/{document_id}/fields",
                {"documentFields": document_fields})

def delete_template_document_fields(token, account_id, base_uri, template_id,
                                     document_id, document_fields):
    """Delete specific custom document fields from a template document."""
    return _delete(token, base_uri, account_id,
                   f"/templates/{template_id}/documents/{document_id}/fields",
                   {"documentFields": document_fields})


# ══════════════════════════════════════════════════════════════
# TEMPLATE RECIPIENTS
# ══════════════════════════════════════════════════════════════

def list_template_recipients(token, account_id, base_uri, template_id):
    """List all recipient roles in a template."""
    return _get(token, base_uri, account_id, f"/templates/{template_id}/recipients")

def add_template_recipient(token, account_id, base_uri, template_id,
                           role_name, routing_order=1, default_name=None, default_email=None):
    """Add a recipient role to a template."""
    signer = {"roleName": role_name, "recipientId": "99", "routingOrder": str(routing_order)}
    if default_name:  signer["name"] = default_name
    if default_email: signer["email"] = default_email
    return _post(token, base_uri, account_id, f"/templates/{template_id}/recipients",
                 {"signers": [signer]})

def delete_template_recipient(token, account_id, base_uri, template_id, recipient_id):
    """Remove a recipient role from a template."""
    return _delete(token, base_uri, account_id, f"/templates/{template_id}/recipients",
                   {"signers": [{"recipientId": recipient_id}]})


# ══════════════════════════════════════════════════════════════
# TEMPLATE RECIPIENT TABS
# ══════════════════════════════════════════════════════════════

def list_template_recipient_tabs(token, account_id, base_uri, template_id, recipient_id):
    """List all tabs assigned to a recipient role in a template."""
    return _get(token, base_uri, account_id,
                f"/templates/{template_id}/recipients/{recipient_id}/tabs")

def create_template_recipient_tabs(token, account_id, base_uri,
                                    template_id, recipient_id, tabs):
    """Add tabs to a recipient role in a template.
    tabs example: {'signHereTabs':[{'documentId':'1','pageNumber':'1','xPosition':'200','yPosition':'400'}]}"""
    return _post(token, base_uri, account_id,
                 f"/templates/{template_id}/recipients/{recipient_id}/tabs", tabs)

def update_template_recipient_tabs(token, account_id, base_uri,
                                    template_id, recipient_id, tabs):
    """Update existing tabs on a recipient role in a template."""
    return _put(token, base_uri, account_id,
                f"/templates/{template_id}/recipients/{recipient_id}/tabs", tabs)

def delete_template_recipient_tabs(token, account_id, base_uri,
                                    template_id, recipient_id, tabs):
    """Delete specific tabs from a recipient role in a template. tabs: dict with tabIds."""
    return _delete(token, base_uri, account_id,
                   f"/templates/{template_id}/recipients/{recipient_id}/tabs", tabs)


# ══════════════════════════════════════════════════════════════
# TEMPLATE CUSTOM FIELDS
# ══════════════════════════════════════════════════════════════

def list_template_custom_fields(token, account_id, base_uri, template_id):
    """List custom metadata fields on a template."""
    return _get(token, base_uri, account_id, f"/templates/{template_id}/custom_fields")


# ══════════════════════════════════════════════════════════════
# TEMPLATE LOCKS
# ══════════════════════════════════════════════════════════════

def get_template_lock(token, account_id, base_uri, template_id):
    """Get lock information for a template being edited."""
    return _get(token, base_uri, account_id, f"/templates/{template_id}/lock")


# ══════════════════════════════════════════════════════════════
# FOLDERS
# ══════════════════════════════════════════════════════════════

def list_folders(token, account_id, base_uri):
    """List all folders (inbox, sent, drafts, custom) in the account."""
    return _get(token, base_uri, account_id, "/folders")

def list_folder_items(token, account_id, base_uri, folder_id, count=20, status=None):
    """List envelopes inside a folder."""
    params = {"count": count}
    if status: params["status"] = status
    return _get(token, base_uri, account_id, f"/folders/{folder_id}", params)

def move_envelope_to_folder(token, account_id, base_uri, folder_id, envelope_id):
    """Move an envelope into a folder."""
    return _put(token, base_uri, account_id, f"/folders/{folder_id}",
                {"envelopeIds": [envelope_id]})


# ══════════════════════════════════════════════════════════════
# SIGNING GROUPS
# ══════════════════════════════════════════════════════════════

def list_signing_groups(token, account_id, base_uri):
    """List all signing groups in the account."""
    return _get(token, base_uri, account_id, "/signing_groups")

def get_signing_group(token, account_id, base_uri, signing_group_id):
    """Get details and members of a signing group."""
    return _get(token, base_uri, account_id, f"/signing_groups/{signing_group_id}")

def list_signing_group_users(token, account_id, base_uri, signing_group_id):
    """List users in a specific signing group."""
    return _get(token, base_uri, account_id,
                f"/signing_groups/{signing_group_id}/users")


# ══════════════════════════════════════════════════════════════
# ACCOUNTS
# ══════════════════════════════════════════════════════════════

def get_account_info(token, account_id, base_uri):
    """Get details about the current Docusign account (name, plan, settings)."""
    return _get(token, base_uri, account_id, "")

def get_account_settings(token, account_id, base_uri):
    """Get all account-level settings."""
    return _get(token, base_uri, account_id, "/settings")


# ══════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════

def list_users(token, account_id, base_uri, count=20, email=None, status=None):
    """List users in the account."""
    params = {"count": count}
    if email:  params["email"] = email
    if status: params["status"] = status
    return _get(token, base_uri, account_id, "/users", params)

def get_user(token, account_id, base_uri, user_id):
    """Get details for a specific user."""
    return _get(token, base_uri, account_id, f"/users/{user_id}")

def get_user_profile(token, account_id, base_uri, user_id):
    """Get the profile of a specific user."""
    return _get(token, base_uri, account_id, f"/users/{user_id}/profile")


# ══════════════════════════════════════════════════════════════
# BULK ENVELOPES
# ══════════════════════════════════════════════════════════════

def list_bulk_send_batches(token, account_id, base_uri, count=10, status=None):
    """List bulk send batches."""
    params = {"count": count}
    if status: params["status"] = status
    return _get(token, base_uri, account_id, "/bulk_send_batch", params)

def get_bulk_send_batch(token, account_id, base_uri, batch_id):
    """Get status and details of a specific bulk send batch."""
    return _get(token, base_uri, account_id, f"/bulk_send_batch/{batch_id}")


# ══════════════════════════════════════════════════════════════
# CUSTOM TABS
# ══════════════════════════════════════════════════════════════

def list_custom_tabs(token, account_id, base_uri):
    """List all custom tabs defined in the account."""
    return _get(token, base_uri, account_id, "/tab_definitions")


# ══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS FOR CLAUDE
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# SEND ENVELOPE WITH PDF
# ══════════════════════════════════════════════════════════════

def send_envelope_with_pdf(token, account_id, base_uri,
                            pdf_base64, filename,
                            recipients, subject,
                            message="", anchor_tabs=None):
    """Send a PDF as an envelope with recipients and optional anchor-based signature tabs.
    
    recipients: list of {name, email, recipient_id, routing_order}
    anchor_tabs: optional list of {recipient_id, anchor_string, tab_type}
                 e.g. [{"recipient_id":"1","anchor_string":"/sig1/","tab_type":"signHere"}]
    If anchor_tabs is not provided, DocuSign will use any /sig/ anchors found in the PDF.
    """
    # Validate required inputs
    if not recipients or not isinstance(recipients, list) or len(recipients) == 0:
        return {"error": "recipients must be a non-empty list of {name, email} objects"}
    if not subject:
        return {"error": "subject is required"}
    if not pdf_base64:
        return {"error": "pdf_base64 is required"}

    # Strip data URL prefix if present
    clean_b64 = pdf_base64
    if "," in pdf_base64[:100]:
        clean_b64 = pdf_base64.split(",", 1)[1]
    clean_b64 = clean_b64.strip().replace("\n", "").replace("\r", "").replace(" ", "")

    # Build signers list
    signers = []
    for r in recipients:
        signer = {
            "name":         r["name"],
            "email":        r["email"],
            "recipientId":  str(r.get("recipient_id", "1")),
            "routingOrder": str(r.get("routing_order", "1")),
        }
        # Add tabs for this recipient
        if anchor_tabs:
            tabs = {"signHereTabs": [], "dateSignedTabs": [], "fullNameTabs": [], "initialHereTabs": []}
            for tab in anchor_tabs:
                if str(tab.get("recipient_id")) != str(r.get("recipient_id", "1")):
                    continue
                tab_type = tab.get("tab_type", "signHere")
                tab_entry = {
                    "anchorString":  tab["anchor_string"],
                    "anchorUnits":   "pixels",
                    "anchorXOffset": str(tab.get("x_offset", 0)),
                    "anchorYOffset": str(tab.get("y_offset", 0)),
                }
                if tab_type == "signHere":
                    tabs["signHereTabs"].append(tab_entry)
                elif tab_type == "dateSigned":
                    tabs["dateSignedTabs"].append(tab_entry)
                elif tab_type == "fullName":
                    tabs["fullNameTabs"].append(tab_entry)
                elif tab_type == "initialHere":
                    tabs["initialHereTabs"].append(tab_entry)
            # Clean empty tab lists
            signer["tabs"] = {k: v for k, v in tabs.items() if v}
        signers.append(signer)

    body = {
        "emailSubject": subject,
        "emailBlurb":   message,
        "documents": [{
            "documentBase64": clean_b64,
            "name":           filename or "document.pdf",
            "fileExtension":  "pdf",
            "documentId":     "1",
        }],
        "recipients": {"signers": signers},
        "status": "sent",
    }

    r = _post(token, base_uri, account_id, "/envelopes", body)
    if "error" in r:
        return r
    return {
        "success":     True,
        "envelope_id": r.get("envelopeId"),
        "status":      "sent",
        "recipients":  [{"name": s["name"], "email": s["email"]} for s in signers],
    }


# ══════════════════════════════════════════════════════════════
# CREATE TEMPLATE FROM PDF
# ══════════════════════════════════════════════════════════════

def create_template_from_pdf(token, account_id, base_uri,
                              pdf_base64, filename, template_name,
                              description="", role_names=None, anchor_tabs=None):
    """Create a reusable Docusign template from a PDF.
    
    role_names: list of signer role names e.g. ["Signer", "Counter-signer"]
                Defaults to ["Signer"] if not provided.
    anchor_tabs: optional list of {role_name, anchor_string, tab_type}
    """
    # Strip data URL prefix if present
    clean_b64 = pdf_base64
    if "," in pdf_base64[:100]:
        clean_b64 = pdf_base64.split(",", 1)[1]
    clean_b64 = clean_b64.strip().replace("\n", "").replace("\r", "").replace(" ", "")

    roles = role_names or ["Signer"]

    # Build placeholder recipients (roles)
    signers = []
    for i, role in enumerate(roles):
        signer = {
            "roleName":     role,
            "recipientId":  str(i + 1),
            "routingOrder": str(i + 1),
            "name":         "",
            "email":        "",
        }
        # Add tabs for this role
        if anchor_tabs:
            tabs = {"signHereTabs": [], "dateSignedTabs": [], "fullNameTabs": [], "initialHereTabs": []}
            for tab in anchor_tabs:
                if tab.get("role_name") != role:
                    continue
                tab_type = tab.get("tab_type", "signHere")
                tab_entry = {
                    "anchorString":  tab["anchor_string"],
                    "anchorUnits":   "pixels",
                    "anchorXOffset": str(tab.get("x_offset", 0)),
                    "anchorYOffset": str(tab.get("y_offset", 0)),
                }
                if tab_type == "signHere":
                    tabs["signHereTabs"].append(tab_entry)
                elif tab_type == "dateSigned":
                    tabs["dateSignedTabs"].append(tab_entry)
                elif tab_type == "fullName":
                    tabs["fullNameTabs"].append(tab_entry)
                elif tab_type == "initialHere":
                    tabs["initialHereTabs"].append(tab_entry)
            signer["tabs"] = {k: v for k, v in tabs.items() if v}
        signers.append(signer)

    body = {
        "name":        template_name,
        "description": description,
        "shared":      "false",
        "documents": [{
            "documentBase64": clean_b64,
            "name":           filename or "document.pdf",
            "fileExtension":  "pdf",
            "documentId":     "1",
        }],
        "recipients": {"signers": signers},
        "status":     "created",
        "emailSubject": template_name,
    }

    r = _post(token, base_uri, account_id, "/templates", body)
    if "error" in r:
        return r
    return {
        "success":     True,
        "template_id": r.get("templateId"),
        "name":        template_name,
        "roles":       roles,
    }


TOOLS = [

    # ── Envelopes ──────────────────────────────────────────────
    {
        "name": "list_envelopes",
        "description": "List recent Docusign envelopes, filterable by status (sent/delivered/completed/declined/voided/any) and searchable by text.",
        "input_schema": {"type": "object", "properties": {
            "count":       {"type": "integer", "description": "Number to return (default 10)"},
            "status":      {"type": "string",  "description": "sent|delivered|completed|declined|voided|any"},
            "from_date":   {"type": "string",  "description": "Start date YYYY-MM-DD"},
            "search_text": {"type": "string",  "description": "Search term"},
        }}
    },
    {
        "name": "get_envelope",
        "description": "Get full details of an envelope including all recipients and their current signing status.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "void_envelope",
        "description": "Void (cancel) a sent envelope that hasn't been completed.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
            "reason":      {"type": "string", "description": "Reason for voiding"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "resend_envelope",
        "description": "Resend reminder emails to all pending recipients of an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "correct_envelope",
        "description": "Correct a recipient's email address or name on a sent envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":  {"type": "string", "description": "Envelope ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID to correct"},
            "new_email":    {"type": "string", "description": "New email address"},
            "new_name":     {"type": "string", "description": "New name"},
        }, "required": ["envelope_id", "recipient_id"]}
    },
    {
        "name": "get_envelope_audit_events",
        "description": "Get the complete audit trail for an envelope — all events, timestamps, IP addresses.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "get_envelope_form_data",
        "description": "Get all field values (tab data) filled in by recipients in a completed envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "create_and_send_envelope",
        "description": "Create a simple envelope and send it to a signer immediately (no PDF required).",
        "input_schema": {"type": "object", "properties": {
            "signer_name":  {"type": "string", "description": "Recipient full name"},
            "signer_email": {"type": "string", "description": "Recipient email"},
            "subject":      {"type": "string", "description": "Email subject"},
            "message":      {"type": "string", "description": "Email message body (optional)"},
        }, "required": ["signer_name", "signer_email", "subject"]}
    },
    {
        "name": "send_envelope_with_pdf",
        "description": "Send a PDF document as a Docusign envelope to one or more recipients for signing. Use this when the user wants to send a specific PDF file. The pdf_base64 must be provided (from an attached document). Optionally include anchor_tabs to place signature fields at specific text locations in the PDF.",
        "input_schema": {"type": "object", "properties": {
            "pdf_base64": {"type": "string", "description": "Base64-encoded PDF content"},
            "filename":   {"type": "string", "description": "PDF filename e.g. contract.pdf"},
            "recipients": {
                "type": "array",
                "description": "List of recipients",
                "items": {"type": "object", "properties": {
                    "name":         {"type": "string"},
                    "email":        {"type": "string"},
                    "recipient_id": {"type": "string"},
                    "routing_order":{"type": "integer"},
                }, "required": ["name", "email"]}
            },
            "subject":     {"type": "string", "description": "Email subject line"},
            "message":     {"type": "string", "description": "Optional email message body"},
            "anchor_tabs": {
                "type": "array",
                "description": "Optional signature/date field anchors. Each item: {recipient_id, anchor_string, tab_type: signHere|dateSigned|fullName|initialHere}",
                "items": {"type": "object"}
            },
        }, "required": ["pdf_base64", "filename", "recipients", "subject"]}
    },
    {
        "name": "create_template_from_pdf",
        "description": "Create a reusable Docusign template from a PDF document. Use this when the user wants to save a document as a template they can send repeatedly. Optionally specify signer role names and anchor tabs for signature placement.",
        "input_schema": {"type": "object", "properties": {
            "pdf_base64":     {"type": "string", "description": "Base64-encoded PDF content"},
            "filename":       {"type": "string", "description": "PDF filename"},
            "template_name":  {"type": "string", "description": "Name for the new template"},
            "description":    {"type": "string", "description": "Optional template description"},
            "role_names":     {
                "type": "array",
                "description": "Signer role names e.g. ['Signer', 'Counter-signer']. Defaults to ['Signer'].",
                "items": {"type": "string"}
            },
            "anchor_tabs": {
                "type": "array",
                "description": "Optional tab anchors: [{role_name, anchor_string, tab_type: signHere|dateSigned|fullName|initialHere}]",
                "items": {"type": "object"}
            },
        }, "required": ["pdf_base64", "filename", "template_name"]}
    },

    # ── Envelope Documents ─────────────────────────────────────
    {
        "name": "list_envelope_documents",
        "description": "List all documents attached to an envelope with name, pages, and size.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "get_envelope_document_info",
        "description": "Get metadata for a specific document in an envelope. Use document_id='combined' for all pages merged into one PDF.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
            "document_id": {"type": "string", "description": "Document ID or 'combined'"},
        }, "required": ["envelope_id", "document_id"]}
    },
    {
        "name": "delete_envelope_documents",
        "description": "Delete one or more documents from a draft envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":  {"type": "string", "description": "Envelope ID"},
            "document_ids": {"type": "array",  "description": "List of document ID strings to delete", "items": {"type": "string"}},
        }, "required": ["envelope_id", "document_ids"]}
    },
    {
        "name": "get_envelope_document_fields",
        "description": "Get custom metadata fields for a specific document in an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
            "document_id": {"type": "string", "description": "Document ID"},
        }, "required": ["envelope_id", "document_id"]}
    },
    {
        "name": "create_envelope_document_fields",
        "description": "Add custom metadata fields to a document in an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":      {"type": "string", "description": "Envelope ID"},
            "document_id":      {"type": "string", "description": "Document ID"},
            "document_fields":  {"type": "array",  "description": "List of {name, value} objects", "items": {"type": "object"}},
        }, "required": ["envelope_id", "document_id", "document_fields"]}
    },
    {
        "name": "update_envelope_document_fields",
        "description": "Update custom metadata fields on a document in an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":     {"type": "string", "description": "Envelope ID"},
            "document_id":     {"type": "string", "description": "Document ID"},
            "document_fields": {"type": "array",  "description": "Updated {name, value} objects", "items": {"type": "object"}},
        }, "required": ["envelope_id", "document_id", "document_fields"]}
    },
    {
        "name": "delete_envelope_document_fields",
        "description": "Delete specific custom metadata fields from a document in an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":     {"type": "string", "description": "Envelope ID"},
            "document_id":     {"type": "string", "description": "Document ID"},
            "document_fields": {"type": "array",  "description": "Fields to delete (with name)", "items": {"type": "object"}},
        }, "required": ["envelope_id", "document_id", "document_fields"]}
    },

    # ── Envelope Recipients ────────────────────────────────────
    {
        "name": "list_envelope_recipients",
        "description": "List all recipients of an envelope with type, routing order, and signing status.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "add_envelope_recipient",
        "description": "Add a new recipient to an existing envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":    {"type": "string",  "description": "Envelope ID"},
            "name":           {"type": "string",  "description": "Recipient name"},
            "email":          {"type": "string",  "description": "Recipient email"},
            "routing_order":  {"type": "integer", "description": "Signing order"},
            "recipient_type": {"type": "string",  "description": "signers|carbonCopies|certifiedDeliveries"},
        }, "required": ["envelope_id", "name", "email"]}
    },
    {
        "name": "delete_envelope_recipient",
        "description": "Remove a recipient from an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":  {"type": "string", "description": "Envelope ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
        }, "required": ["envelope_id", "recipient_id"]}
    },

    # ── Envelope Recipient Tabs ────────────────────────────────
    {
        "name": "list_envelope_recipient_tabs",
        "description": "List all tabs (signature, text, date, checkbox fields) assigned to a recipient in an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":  {"type": "string", "description": "Envelope ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
        }, "required": ["envelope_id", "recipient_id"]}
    },
    {
        "name": "update_envelope_recipient_tabs",
        "description": "Update tab values for a recipient in an envelope. tabs: e.g. {\"textTabs\":[{\"tabId\":\"x\",\"value\":\"new\"}]}",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":  {"type": "string", "description": "Envelope ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
            "tabs":         {"type": "object", "description": "Tabs to update"},
        }, "required": ["envelope_id", "recipient_id", "tabs"]}
    },

    # ── Envelope Custom Fields ─────────────────────────────────
    {
        "name": "list_envelope_custom_fields",
        "description": "List custom metadata fields on an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "create_envelope_custom_fields",
        "description": "Add custom metadata fields to an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":        {"type": "string", "description": "Envelope ID"},
            "text_custom_fields": {"type": "array",  "description": "List of {name, value, required, show}"},
        }, "required": ["envelope_id", "text_custom_fields"]}
    },

    # ── Envelope Locks ─────────────────────────────────────────
    {
        "name": "get_envelope_lock",
        "description": "Get lock information for an envelope currently being edited.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "create_envelope_lock",
        "description": "Lock an envelope to prevent concurrent edits.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id":               {"type": "string",  "description": "Envelope ID"},
            "lock_duration_in_seconds":  {"type": "integer", "description": "Lock duration (default 300)"},
        }, "required": ["envelope_id"]}
    },
    {
        "name": "delete_envelope_lock",
        "description": "Release the edit lock on an envelope.",
        "input_schema": {"type": "object", "properties": {
            "envelope_id": {"type": "string", "description": "Envelope ID"},
        }, "required": ["envelope_id"]}
    },

    # ── Templates ──────────────────────────────────────────────
    {
        "name": "list_templates",
        "description": "List templates in the account, optionally filtered by search text or folder.",
        "input_schema": {"type": "object", "properties": {
            "count":       {"type": "integer", "description": "Number to return (default 20)"},
            "search_text": {"type": "string",  "description": "Search term"},
            "folder_id":   {"type": "string",  "description": "Filter by folder ID"},
        }}
    },
    {
        "name": "get_template",
        "description": "Get full details of a template including all documents, recipients, tabs, and settings.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },
    {
        "name": "delete_template",
        "description": "Permanently delete a template from the account.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },
    {
        "name": "send_from_template",
        "description": "Send an envelope from a template to a recipient.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "signer_name":  {"type": "string", "description": "Recipient full name"},
            "signer_email": {"type": "string", "description": "Recipient email"},
            "subject":      {"type": "string", "description": "Email subject (optional)"},
            "role_name":    {"type": "string", "description": "Role name in template (default: Signer)"},
        }, "required": ["template_id", "signer_name", "signer_email"]}
    },

    # ── Template Documents ─────────────────────────────────────
    {
        "name": "list_template_documents",
        "description": "List all documents attached to a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },
    {
        "name": "get_template_document_info",
        "description": "Get PDF or metadata for a document in a template. Use document_id='combined' for all pages merged, or 'archive' for a ZIP of all documents.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
            "document_id": {"type": "string", "description": "Document ID, 'combined', or 'archive'"},
        }, "required": ["template_id", "document_id"]}
    },
    {
        "name": "delete_template_documents",
        "description": "Delete one or more documents from a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "document_ids": {"type": "array",  "description": "List of document ID strings to delete", "items": {"type": "string"}},
        }, "required": ["template_id", "document_ids"]}
    },
    {
        "name": "get_template_document_fields",
        "description": "Get custom metadata fields for a specific document in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
            "document_id": {"type": "string", "description": "Document ID"},
        }, "required": ["template_id", "document_id"]}
    },
    {
        "name": "create_template_document_fields",
        "description": "Add custom metadata fields to a document in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":     {"type": "string", "description": "Template ID"},
            "document_id":     {"type": "string", "description": "Document ID"},
            "document_fields": {"type": "array",  "description": "List of {name, value} objects", "items": {"type": "object"}},
        }, "required": ["template_id", "document_id", "document_fields"]}
    },
    {
        "name": "update_template_document_fields",
        "description": "Update custom metadata fields on a document in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":     {"type": "string", "description": "Template ID"},
            "document_id":     {"type": "string", "description": "Document ID"},
            "document_fields": {"type": "array",  "description": "Updated {name, value} objects", "items": {"type": "object"}},
        }, "required": ["template_id", "document_id", "document_fields"]}
    },
    {
        "name": "delete_template_document_fields",
        "description": "Delete specific custom metadata fields from a document in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":     {"type": "string", "description": "Template ID"},
            "document_id":     {"type": "string", "description": "Document ID"},
            "document_fields": {"type": "array",  "description": "Fields to delete (with name)", "items": {"type": "object"}},
        }, "required": ["template_id", "document_id", "document_fields"]}
    },

    # ── Template Recipients ────────────────────────────────────
    {
        "name": "list_template_recipients",
        "description": "List all recipient roles defined in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },
    {
        "name": "add_template_recipient",
        "description": "Add a new recipient role to a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":   {"type": "string",  "description": "Template ID"},
            "role_name":     {"type": "string",  "description": "Role name"},
            "routing_order": {"type": "integer", "description": "Signing order"},
            "default_name":  {"type": "string",  "description": "Default signer name (optional)"},
            "default_email": {"type": "string",  "description": "Default signer email (optional)"},
        }, "required": ["template_id", "role_name"]}
    },
    {
        "name": "delete_template_recipient",
        "description": "Remove a recipient role from a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
        }, "required": ["template_id", "recipient_id"]}
    },

    # ── Template Recipient Tabs ────────────────────────────────
    {
        "name": "list_template_recipient_tabs",
        "description": "List all tabs (fields) assigned to a recipient role in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
        }, "required": ["template_id", "recipient_id"]}
    },
    {
        "name": "create_template_recipient_tabs",
        "description": "Add tabs (fields) to a recipient role in a template. tabs example: {\"signHereTabs\":[{\"documentId\":\"1\",\"pageNumber\":\"1\",\"xPosition\":\"200\",\"yPosition\":\"400\"}]}",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
            "tabs":         {"type": "object", "description": "Tabs object to add"},
        }, "required": ["template_id", "recipient_id", "tabs"]}
    },
    {
        "name": "update_template_recipient_tabs",
        "description": "Update existing tabs on a recipient role in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
            "tabs":         {"type": "object", "description": "Updated tabs"},
        }, "required": ["template_id", "recipient_id", "tabs"]}
    },
    {
        "name": "delete_template_recipient_tabs",
        "description": "Delete specific tabs from a recipient role in a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id":  {"type": "string", "description": "Template ID"},
            "recipient_id": {"type": "string", "description": "Recipient ID"},
            "tabs":         {"type": "object", "description": "Tabs to delete (with tabIds)"},
        }, "required": ["template_id", "recipient_id", "tabs"]}
    },

    # ── Template Custom Fields ─────────────────────────────────
    {
        "name": "list_template_custom_fields",
        "description": "List custom metadata fields defined on a template.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },

    # ── Template Locks ─────────────────────────────────────────
    {
        "name": "get_template_lock",
        "description": "Get lock information for a template currently being edited.",
        "input_schema": {"type": "object", "properties": {
            "template_id": {"type": "string", "description": "Template ID"},
        }, "required": ["template_id"]}
    },

    # ── Folders ────────────────────────────────────────────────
    {
        "name": "list_folders",
        "description": "List all folders in the account (inbox, sent, drafts, custom folders).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "list_folder_items",
        "description": "List envelopes inside a specific folder.",
        "input_schema": {"type": "object", "properties": {
            "folder_id": {"type": "string",  "description": "Folder ID"},
            "count":     {"type": "integer", "description": "Number to return (default 20)"},
            "status":    {"type": "string",  "description": "Filter by envelope status"},
        }, "required": ["folder_id"]}
    },
    {
        "name": "move_envelope_to_folder",
        "description": "Move an envelope into a specific folder.",
        "input_schema": {"type": "object", "properties": {
            "folder_id":   {"type": "string", "description": "Destination folder ID"},
            "envelope_id": {"type": "string", "description": "Envelope ID to move"},
        }, "required": ["folder_id", "envelope_id"]}
    },

    # ── Signing Groups ─────────────────────────────────────────
    {
        "name": "list_signing_groups",
        "description": "List all signing groups in the account.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_signing_group",
        "description": "Get details and members of a specific signing group.",
        "input_schema": {"type": "object", "properties": {
            "signing_group_id": {"type": "string", "description": "Signing group ID"},
        }, "required": ["signing_group_id"]}
    },
    {
        "name": "list_signing_group_users",
        "description": "List all users in a signing group.",
        "input_schema": {"type": "object", "properties": {
            "signing_group_id": {"type": "string", "description": "Signing group ID"},
        }, "required": ["signing_group_id"]}
    },

    # ── Accounts ───────────────────────────────────────────────
    {
        "name": "get_account_info",
        "description": "Get information about the current Docusign account (name, plan, limits).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_account_settings",
        "description": "Get all account-level feature and configuration settings.",
        "input_schema": {"type": "object", "properties": {}}
    },

    # ── Users ──────────────────────────────────────────────────
    {
        "name": "list_users",
        "description": "List users in the Docusign account, filterable by email or status.",
        "input_schema": {"type": "object", "properties": {
            "count":  {"type": "integer", "description": "Number to return (default 20)"},
            "email":  {"type": "string",  "description": "Filter by email address"},
            "status": {"type": "string",  "description": "Active|Closed"},
        }}
    },
    {
        "name": "get_user",
        "description": "Get details for a specific user in the account.",
        "input_schema": {"type": "object", "properties": {
            "user_id": {"type": "string", "description": "User ID"},
        }, "required": ["user_id"]}
    },
    {
        "name": "get_user_profile",
        "description": "Get the profile information of a specific user.",
        "input_schema": {"type": "object", "properties": {
            "user_id": {"type": "string", "description": "User ID"},
        }, "required": ["user_id"]}
    },

    # ── Bulk Envelopes ─────────────────────────────────────────
    {
        "name": "list_bulk_send_batches",
        "description": "List bulk send batches in the account.",
        "input_schema": {"type": "object", "properties": {
            "count":  {"type": "integer", "description": "Number to return (default 10)"},
            "status": {"type": "string",  "description": "Filter by status"},
        }}
    },
    {
        "name": "get_bulk_send_batch",
        "description": "Get status and details of a specific bulk send batch.",
        "input_schema": {"type": "object", "properties": {
            "batch_id": {"type": "string", "description": "Bulk send batch ID"},
        }, "required": ["batch_id"]}
    },

    # ── Custom Tabs ────────────────────────────────────────────
    {
        "name": "list_custom_tabs",
        "description": "List all custom tab definitions in the account.",
        "input_schema": {"type": "object", "properties": {}}
    },
]


# ══════════════════════════════════════════════════════════════
# DISPATCH
# ══════════════════════════════════════════════════════════════

ACTION_MAP = {
    "list_envelopes":                  list_envelopes,
    "get_envelope":                    get_envelope,
    "void_envelope":                   void_envelope,
    "resend_envelope":                 resend_envelope,
    "correct_envelope":                correct_envelope,
    "get_envelope_audit_events":       get_envelope_audit_events,
    "get_envelope_form_data":          get_envelope_form_data,
    "create_and_send_envelope":        create_and_send_envelope,
    "send_envelope_with_pdf":          send_envelope_with_pdf,
    "create_template_from_pdf":        create_template_from_pdf,
    "list_envelope_documents":          list_envelope_documents,
    "get_envelope_document_info":       get_envelope_document_info,
    "delete_envelope_documents":        delete_envelope_documents,
    "get_envelope_document_fields":     get_envelope_document_fields,
    "create_envelope_document_fields":  create_envelope_document_fields,
    "update_envelope_document_fields":  update_envelope_document_fields,
    "delete_envelope_document_fields":  delete_envelope_document_fields,
    "list_envelope_recipients":        list_envelope_recipients,
    "add_envelope_recipient":          add_envelope_recipient,
    "delete_envelope_recipient":       delete_envelope_recipient,
    "list_envelope_recipient_tabs":    list_envelope_recipient_tabs,
    "update_envelope_recipient_tabs":  update_envelope_recipient_tabs,
    "list_envelope_custom_fields":     list_envelope_custom_fields,
    "create_envelope_custom_fields":   create_envelope_custom_fields,
    "get_envelope_lock":               get_envelope_lock,
    "create_envelope_lock":            create_envelope_lock,
    "delete_envelope_lock":            delete_envelope_lock,
    "list_templates":                  list_templates,
    "get_template":                    get_template,
    "delete_template":                 delete_template,
    "send_from_template":              send_from_template,
    "list_template_documents":              list_template_documents,
    "get_template_document_info":           get_template_document_info,
    "delete_template_documents":            delete_template_documents,
    "get_template_document_fields":         get_template_document_fields,
    "create_template_document_fields":      create_template_document_fields,
    "update_template_document_fields":      update_template_document_fields,
    "delete_template_document_fields":      delete_template_document_fields,
    "list_template_recipients":        list_template_recipients,
    "add_template_recipient":          add_template_recipient,
    "delete_template_recipient":       delete_template_recipient,
    "list_template_recipient_tabs":    list_template_recipient_tabs,
    "create_template_recipient_tabs":  create_template_recipient_tabs,
    "update_template_recipient_tabs":  update_template_recipient_tabs,
    "delete_template_recipient_tabs":  delete_template_recipient_tabs,
    "list_template_custom_fields":     list_template_custom_fields,
    "get_template_lock":               get_template_lock,
    "list_folders":                    list_folders,
    "list_folder_items":               list_folder_items,
    "move_envelope_to_folder":         move_envelope_to_folder,
    "list_signing_groups":             list_signing_groups,
    "get_signing_group":               get_signing_group,
    "list_signing_group_users":        list_signing_group_users,
    "get_account_info":                get_account_info,
    "get_account_settings":            get_account_settings,
    "list_users":                      list_users,
    "get_user":                        get_user,
    "get_user_profile":                get_user_profile,
    "list_bulk_send_batches":          list_bulk_send_batches,
    "get_bulk_send_batch":             get_bulk_send_batch,
    "list_custom_tabs":                list_custom_tabs,
}


def execute_tool(name: str, inputs: dict,
                 token: str, account_id: str, base_uri: str) -> dict:
    fn = ACTION_MAP.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(token=token, account_id=account_id, base_uri=base_uri, **inputs)
    except Exception as e:
        return {"error": str(e)}
