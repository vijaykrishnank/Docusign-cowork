"""
scraper.py  —  DocuSign Knowledge Base Scraper

Auto-runs on startup if ChromaDB is empty.
Re-checks every 24 hours — only re-scrapes a site if its seed page
content has changed since the last crawl (hash-based change detection).

Collections:
  docusign_support    — support.docusign.com
  docusign_developers — developers.docusign.com
  docusign_legality   — docusign.com/products/electronic-signature/legality
"""

import hashlib
import json
import os
import re
import sys
import time
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH   = Path("./chroma_db")
STATE_FILE    = CHROMA_PATH / "scrape_state.json"   # tracks last_scraped + seed_hash per site
CHUNK_SIZE    = 400
CHUNK_OVERLAP = 50
DELAY         = 1.0   # seconds between requests
CHECK_INTERVAL = 60 * 60 * 24  # 24 hours in seconds

MAX_PAGES = {
    "support":    500,
    "developers": 500,
    "legality":   50,
}

SEEDS = {
    "support":    "https://support.docusign.com",
    "developers": "https://developers.docusign.com",
    "legality":   "https://www.docusign.com/products/electronic-signature/legality",
}

ALLOWED_DOMAINS = {
    "support":    "support.docusign.com",
    "developers": "developers.docusign.com",
    "legality":   "www.docusign.com",
}

COLLECTION_NAMES = {
    "support":    "docusign_support",
    "developers": "docusign_developers",
    "legality":   "docusign_legality",
}


# ── State persistence ─────────────────────────────────────────
def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_state(state: dict):
    CHROMA_PATH.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Voyage embeddings via Anthropic ──────────────────────────
def _get_embedding_function():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    class VoyageEmbeddingFunction(embedding_functions.EmbeddingFunction):
        def __call__(self, input):
            import anthropic
            client  = anthropic.Anthropic(api_key=api_key)
            results = []
            for i in range(0, len(input), 64):
                batch    = input[i:i + 64]
                response = client.beta.embeddings.create(
                    model="voyage-3", input=batch, input_type="document")
                results.extend([e.embedding for e in response.embeddings])
            return results

    return VoyageEmbeddingFunction()


# ── Change detection ──────────────────────────────────────────
def _seed_hash(site_key: str) -> str:
    """Fetch the seed page and return an MD5 of its main text content."""
    try:
        session = requests.Session()
        session.headers["User-Agent"] = "DocuSignAgentBot/1.0"
        resp = session.get(SEEDS[site_key], timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text()).strip()
        return hashlib.md5(text[:5000].encode()).hexdigest()
    except Exception:
        return ""


def _site_needs_update(site_key: str, state: dict) -> bool:
    """Return True if this site has never been scraped or its seed page changed."""
    site_state = state.get(site_key, {})

    # Never scraped
    if not site_state.get("last_scraped"):
        print(f"[Scraper] {site_key}: never scraped — will build")
        return True

    # Check 24h window
    age = time.time() - site_state.get("last_scraped", 0)
    if age < CHECK_INTERVAL:
        hours_left = int((CHECK_INTERVAL - age) / 3600)
        print(f"[Scraper] {site_key}: checked {int(age/3600)}h ago, next check in {hours_left}h")
        return False

    # 24h passed — check if seed page actually changed
    current_hash = _seed_hash(site_key)
    stored_hash  = site_state.get("seed_hash", "")
    if current_hash and current_hash == stored_hash:
        print(f"[Scraper] {site_key}: no changes detected, skipping re-scrape")
        # Update timestamp so we don't re-check for another 24h
        state[site_key]["last_scraped"] = time.time()
        _save_state(state)
        return False

    print(f"[Scraper] {site_key}: changes detected — re-scraping")
    return True


# ── Text chunking ─────────────────────────────────────────────
def _chunk_text(text: str, url: str, title: str) -> list:
    words  = text.split()
    chunks = []
    i, idx = 0, 0
    while i < len(words):
        chunk_words = words[i:i + CHUNK_SIZE]
        chunk_str   = " ".join(chunk_words)
        chunk_id    = hashlib.md5(f"{url}_{idx}".encode()).hexdigest()
        chunks.append({
            "id":       chunk_id,
            "text":     chunk_str,
            "metadata": {"url": url, "title": title, "chunk_index": idx,
                         "scraped_at": int(time.time())}
        })
        i   += CHUNK_SIZE - CHUNK_OVERLAP
        idx += 1
    return chunks


# ── Page scraper ──────────────────────────────────────────────
def _scrape_page(url: str, session: requests.Session):
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return "", ""
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return "", ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title else url
        main  = (soup.find("main") or soup.find("article") or
                 soup.find(id="content") or soup.find(class_="content") or
                 soup.body)
        if not main:
            return title, ""
        text = re.sub(r"\s+", " ", main.get_text(separator=" ", strip=True))
        return title, text
    except Exception as e:
        print(f"  [Scraper] Error scraping {url}: {e}")
        return "", ""


# ── Crawler ───────────────────────────────────────────────────
def _crawl(site_key: str, collection) -> int:
    seed      = SEEDS[site_key]
    domain    = ALLOWED_DOMAINS[site_key]
    max_pages = MAX_PAGES[site_key]
    visited   = set()
    queue     = [seed]
    total     = 0
    session   = requests.Session()
    session.headers["User-Agent"] = "DocuSignAgentBot/1.0 (educational scraper)"

    print(f"[Scraper] Crawling {site_key} (max {max_pages} pages)...")

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        print(f"  [{len(visited)}/{max_pages}] {url[:80]}")

        title, text = _scrape_page(url, session)
        if text and len(text) > 100:
            chunks = _chunk_text(text, url, title)
            if chunks:
                try:
                    collection.upsert(
                        ids       = [c["id"] for c in chunks],
                        documents = [c["text"] for c in chunks],
                        metadatas = [c["metadata"] for c in chunks],
                    )
                    total += len(chunks)
                except Exception as e:
                    print(f"  [Scraper] ChromaDB upsert error: {e}")

            # Discover links
            try:
                for a in BeautifulSoup(session.get(url, timeout=15).text,
                                       "html.parser").find_all("a", href=True):
                    href   = urljoin(url, a["href"])
                    parsed = urlparse(href)
                    if (parsed.netloc == domain and
                            parsed.scheme in ("http", "https") and
                            not any(href.endswith(x) for x in
                                    [".pdf", ".zip", ".png", ".jpg", ".gif"]) and
                            href not in visited and href not in queue):
                        queue.append(href)
            except Exception:
                pass

        time.sleep(DELAY)

    print(f"[Scraper] {site_key}: {len(visited)} pages, {total} chunks stored")
    return total


# ── Core: check and update one site ──────────────────────────
def _update_site(site_key: str, client, emb_fn, state: dict):
    col = client.get_or_create_collection(
        name               = COLLECTION_NAMES[site_key],
        embedding_function = emb_fn,
        metadata           = {"hnsw:space": "cosine"}
    )
    seed_hash = _seed_hash(site_key)
    _crawl(site_key, col)
    state[site_key] = {
        "last_scraped": time.time(),
        "seed_hash":    seed_hash,
        "chunks":       col.count(),
    }
    _save_state(state)
    print(f"[Scraper] {site_key} complete — {col.count()} chunks total")


# ── Public: build or refresh knowledge base ───────────────────
def build_knowledge_base(sites=None):
    """Scrape all sites unconditionally (used for forced refresh)."""
    if sites is None:
        sites = ["support", "developers", "legality"]
    CHROMA_PATH.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    emb_fn = _get_embedding_function()
    state  = _load_state()
    for site in sites:
        _update_site(site, client, emb_fn, state)
    print("[Scraper] Knowledge base build complete.")


# ── Auto-start + 24h scheduler ───────────────────────────────
def start_background_scheduler():
    """
    Called once at app startup.
    - Immediately checks each site: scrapes if empty or changed.
    - Then loops every 24h checking for updates.
    Runs entirely in a daemon thread — never blocks the web server.
    """
    def run():
        CHROMA_PATH.mkdir(exist_ok=True)
        try:
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            emb_fn = _get_embedding_function()
        except Exception as e:
            print(f"[Scraper] Could not initialise ChromaDB: {e}")
            return

        while True:
            state = _load_state()
            for site in ["support", "developers", "legality"]:
                try:
                    # Also force update if collection exists but is empty
                    col = client.get_or_create_collection(
                        name               = COLLECTION_NAMES[site],
                        embedding_function = emb_fn,
                        metadata           = {"hnsw:space": "cosine"}
                    )
                    is_empty = col.count() == 0
                    if is_empty or _site_needs_update(site, state):
                        _update_site(site, client, emb_fn, state)
                except Exception as e:
                    print(f"[Scraper] Error updating {site}: {e}")

            # Sleep 1 hour between checks (change detection handles skipping)
            print(f"[Scraper] All sites checked. Next check in 1 hour.")
            time.sleep(3600)

    t = threading.Thread(target=run, daemon=True, name="kb-scheduler")
    t.start()
    print("[Scraper] Background knowledge base scheduler started.")


if __name__ == "__main__":
    sites = sys.argv[1:] if len(sys.argv) > 1 else None
    valid = {"support", "developers", "legality"}
    if sites:
        invalid = set(sites) - valid
        if invalid:
            print(f"Unknown sites: {invalid}. Valid: {valid}")
            sys.exit(1)
    build_knowledge_base(sites)
