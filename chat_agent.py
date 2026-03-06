"""
chat_agent.py  —  Docusign Conversational Agent
"""

import json
import pathlib
import anthropic
from knowledge_base import query, format_context, is_ready
from docusign_actions import TOOLS, execute_tool

CORRECTIONS_FILE = pathlib.Path("./corrections.json")

def _load_corrections():
    try:
        if CORRECTIONS_FILE.exists():
            return json.loads(CORRECTIONS_FILE.read_text())
    except Exception:
        pass
    return []

def save_correction(message_text, flagged_answer, feedback):
    corrections = _load_corrections()
    corrections.append({
        "question":      message_text,
        "wrong_answer":  flagged_answer,
        "user_feedback": feedback,
    })
    CORRECTIONS_FILE.write_text(json.dumps(corrections, indent=2))
    print(f"[Corrections] Saved. Total: {len(corrections)}")

def _corrections_prompt(corrections):
    if not corrections:
        return ""
    lines = ["\n\n## Known Corrections (user-reported — never repeat these)"]
    for i, c in enumerate(corrections[-20:], 1):
        lines.append(
            f"\n{i}. Question: \"{c['question']}\"\n"
            f"   Wrong answer: \"{c['wrong_answer'][:200]}\"\n"
            f"   Correction: \"{c['user_feedback']}\"\n"
            f"   → Do NOT repeat the wrong answer above."
        )
    return "\n".join(lines)

BASE_SYSTEM_PROMPT = """You are a helpful Docusign expert assistant built into the Docusign Agent app.
You have access to:
  1. A knowledge base scraped from support.docusign.com, developers.docusign.com,
     and docusign.com/products/electronic-signature/legality
  2. Tools to perform Docusign API actions on behalf of the user
  3. The ability to read and analyze PDF documents attached by the user

Guidelines:
- Answer questions conversationally and concisely
- When relevant documentation is provided, use it to give accurate answers
- Always cite source URLs inline when answering from documentation
- If a user wants to perform an action, use the available tools — actually DO it, don't just describe it
- For legality questions, always specify the region and recommend consulting a lawyer
- If the knowledge base doesn't have an answer and you're unsure, say so clearly
- Format responses with markdown for readability

PDF HANDLING — CRITICAL:
- When a PDF document is attached, you CAN and MUST read it directly. Never ask the user to copy/paste text.
- Immediately analyze the full document content and respond with a thorough summary covering:
  * Document type and purpose
  * Key parties involved
  * Important dates, amounts, or terms
  * Fields that need to be filled or signed
  * Any actions the user should take
- Never say you cannot read, access, or open the file. You have full access to the document content.

IMPORTANT — Source references:
At the end of every response, include a JSON block on its own line in this exact format:
SOURCES_JSON:{"sources":[{"title":"Page title","url":"https://..."}]}
Include up to 3 most relevant source URLs. Never omit this line.
"""

def _pick_collections(question):
    if not question:
        return ["support"]
    q = question.lower()
    is_legal  = any(w in q for w in ["legal","law","valid","country","region",
                                      "jurisdiction","enforceable","binding","comply"])
    is_api    = any(w in q for w in ["api","code","endpoint","sdk","integrate",
                                      "developer","webhook","rest","oauth","token",
                                      "curl","python","javascript","http"])
    is_action = any(w in q for w in ["send","void","resend","create","list",
                                      "envelope","template","sign","status"])
    sites = []
    if is_legal:  sites.append("legality")
    if is_api or is_action: sites.append("developers")
    if not sites or not (is_legal or is_api): sites.append("support")
    if "support" not in sites: sites.append("support")
    return sites

def _sse(obj):
    return "data: " + json.dumps(obj) + "\n\n"

def chat_stream(message, history, token=None, account_id=None,
                base_uri=None, sender_email=None,
                pdf_base64=None, pdf_filename=None):
    client = anthropic.Anthropic()

    # Build user message content — must happen BEFORE it's used below
    user_content = message or ""
    if pdf_base64:
        # Strip data URL prefix if present (e.g. "data:application/pdf;base64,")
        clean_b64 = pdf_base64
        if "," in pdf_base64[:100]:
            clean_b64 = pdf_base64.split(",", 1)[1]
        # Remove any whitespace/newlines that could corrupt base64
        clean_b64 = clean_b64.strip().replace("\n", "").replace("\r", "").replace(" ", "")

        # Check size — Claude API limit is ~32MB for documents (~43MB base64)
        if len(clean_b64) > 40_000_000:
            yield _sse({"type": "error", "content": "PDF is too large (max ~30MB). Please use a smaller file."})
            return

        user_content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": clean_b64,
                },
            },
            {"type": "text", "text": message or "Please analyze this PDF and describe its contents, including any key sections, fields that need to be filled, parties involved, and what action is needed."}
        ]

    # RAG — use text message for knowledge base query
    query_text = message or (pdf_filename or "")
    kb_ready = is_ready("support")
    context  = ""
    sources  = []
    if kb_ready and query_text:
        chunks = query(query_text, sites=_pick_collections(query_text), n_results=5)
        if chunks:
            context = format_context(chunks)
            seen = set()
            for chunk in chunks:
                url   = chunk.get("metadata", {}).get("url", "")
                title = chunk.get("metadata", {}).get("title", url)
                if url and url not in seen:
                    sources.append({"title": title[:80], "url": url})
                    seen.add(url)

    corrections = _load_corrections()
    system = BASE_SYSTEM_PROMPT + _corrections_prompt(corrections)
    if pdf_base64:
        system += (
            "\n\n## PDF Document Attached\n"
            "The user has attached a PDF. It is embedded in their message as a document block — read it fully.\n"
            "NEVER ask the user to paste text or claim you cannot read the file.\n\n"
            "When the user wants to SEND this PDF as an envelope, use the `send_envelope_with_pdf` tool. "
            "Pass the pdf_base64 from the conversation context (it was already provided). "
            "Ask the user for recipient name/email and subject if not already given.\n\n"
            "When the user wants to CREATE A TEMPLATE from this PDF, use the `create_template_from_pdf` tool. "
            "Ask for a template name and signer role names if not provided.\n\n"
            "For anchor tabs: if the PDF contains text like /sig/, /date/, /initials/ use those as anchor_string values. "
            "Otherwise omit anchor_tabs and DocuSign will let the sender place fields manually."
        )
    if context:
        system += f"\n\n## Relevant Documentation\n\n{context}"
    else:
        system += "\n\n## Note\nKnowledge base not yet ready. Answer from training knowledge but flag uncertainty."

    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": user_content})

    tools = TOOLS if (token and account_id and base_uri) else []

    try:
        full_text = ""

        while True:
            response = client.messages.create(
                model      = "claude-sonnet-4-6",
                max_tokens = 2048,
                system     = system,
                messages   = messages,
                tools      = tools or [],
            )

            turn_text = ""
            for block in response.content:
                if block.type == "text" and block.text:
                    turn_text += block.text

            # Strip SOURCES_JSON line before streaming
            text_to_stream = turn_text
            parsed_sources = []
            if "SOURCES_JSON:" in turn_text:
                clean_lines = []
                for line in turn_text.split("\n"):
                    if line.strip().startswith("SOURCES_JSON:"):
                        try:
                            raw = line.strip()[len("SOURCES_JSON:"):]
                            parsed_sources = json.loads(raw).get("sources", [])
                        except Exception:
                            pass
                    else:
                        clean_lines.append(line)
                text_to_stream = "\n".join(clean_lines).strip()

            # Deduplicate sources
            all_sources = parsed_sources if parsed_sources else sources
            seen_urls = set()
            deduped = []
            for s in all_sources:
                if s.get("url") and s["url"] not in seen_urls:
                    deduped.append(s)
                    seen_urls.add(s["url"])
            all_sources = deduped[:4]

            # Stream text in word chunks
            if text_to_stream:
                full_text += text_to_stream
                words = text_to_stream.split(" ")
                buf = []
                for word in words:
                    buf.append(word)
                    if len(buf) >= 5:
                        yield _sse({"type": "text", "content": " ".join(buf) + " "})
                        buf = []
                if buf:
                    yield _sse({"type": "text", "content": " ".join(buf)})

            # Emit sources (only on final non-tool turn)
            if all_sources and response.stop_reason != "tool_use":
                yield _sse({"type": "sources", "sources": all_sources})

            # Handle tool use
            if response.stop_reason == "tool_use" and tools:
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        yield _sse({"type": "action_start", "name": block.name, "inputs": block.input})
                        inputs = dict(block.input)
                        # Inject pdf_base64 if the tool needs it but Claude couldn't pass it directly
                        # (Claude sees the PDF as a document block, not as extractable base64)
                        if block.name in ("send_envelope_with_pdf", "create_template_from_pdf"):
                            if pdf_base64 and not inputs.get("pdf_base64"):
                                clean_b64 = pdf_base64
                                if "," in pdf_base64[:100]:
                                    clean_b64 = pdf_base64.split(",", 1)[1]
                                clean_b64 = clean_b64.strip().replace("\n","").replace("\r","").replace(" ","")
                                inputs["pdf_base64"] = clean_b64
                            if pdf_filename and not inputs.get("filename"):
                                inputs["filename"] = pdf_filename
                        result = execute_tool(
                            name=block.name, inputs=inputs,
                            token=token, account_id=account_id, base_uri=base_uri)
                        yield _sse({"type": "action", "name": block.name, "result": result})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        yield _sse({"type": "done", "full_text": full_text[:500]})

    except Exception as e:
        import traceback
        print(f"[chat_stream error] {traceback.format_exc()}")
        yield _sse({"type": "error", "content": str(e)})
