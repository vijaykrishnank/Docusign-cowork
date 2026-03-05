"""
knowledge_base.py  —  Query the DocuSign ChromaDB knowledge base

Wraps ChromaDB queries with Voyage embeddings so the chat agent
can retrieve the most relevant chunks for any question.
"""

import os
import anthropic
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = Path("./chroma_db")

COLLECTION_NAMES = {
    "support":    "docusign_support",
    "developers": "docusign_developers",
    "legality":   "docusign_legality",
}

_client     = None
_emb_fn     = None
_collections = {}


def _get_client():
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def _get_embedding_function():
    global _emb_fn
    if _emb_fn is not None:
        return _emb_fn

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    class VoyageEmbeddingFunction(embedding_functions.EmbeddingFunction):
        def __call__(self, input):
            client = anthropic.Anthropic(api_key=api_key)
            results = []
            batch_size = 64
            for i in range(0, len(input), batch_size):
                batch = input[i:i + batch_size]
                response = client.beta.embeddings.create(
                    model="voyage-3",
                    input=batch,
                    input_type="query",
                )
                results.extend([e.embedding for e in response.embeddings])
            return results

    _emb_fn = VoyageEmbeddingFunction()
    return _emb_fn


def _get_collection(name: str):
    if name not in _collections:
        client = _get_client()
        emb_fn = _get_embedding_function()
        try:
            _collections[name] = client.get_collection(
                name=name,
                embedding_function=emb_fn
            )
        except Exception:
            return None
    return _collections[name]


def is_ready(site: str = "support") -> bool:
    """Check if the knowledge base has been built for a given site."""
    col = _get_collection(COLLECTION_NAMES[site])
    if col is None:
        return False
    try:
        return col.count() > 0
    except Exception:
        return False


def query(question: str, sites: list[str] = None, n_results: int = 5) -> list[dict]:
    """
    Query the knowledge base and return top matching chunks.

    Args:
        question:  The user's question
        sites:     Which collections to search. Defaults to all three.
        n_results: Number of results per collection

    Returns:
        List of dicts with keys: text, url, title, site, score
    """
    if sites is None:
        sites = ["support", "developers", "legality"]

    all_results = []

    for site in sites:
        col = _get_collection(COLLECTION_NAMES[site])
        if col is None or col.count() == 0:
            continue

        try:
            results = col.query(
                query_texts=[question],
                n_results=min(n_results, col.count()),
                include=["documents", "metadatas", "distances"]
            )

            docs      = results["documents"][0]
            metas     = results["metadatas"][0]
            distances = results["distances"][0]

            for doc, meta, dist in zip(docs, metas, distances):
                all_results.append({
                    "text":  doc,
                    "url":   meta.get("url", ""),
                    "title": meta.get("title", ""),
                    "site":  site,
                    "score": 1 - dist,  # cosine similarity
                })
        except Exception as e:
            print(f"  [KB] Query error on {site}: {e}")

    # Sort by relevance score descending
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:n_results * len(sites)]


def format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string for Claude."""
    if not chunks:
        return "No relevant documentation found."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"[Source {i}: {chunk['title']} ({chunk['url']})]  "
            f"Relevance: {chunk['score']:.2f}\n"
            f"{chunk['text']}"
        )
    return "\n\n---\n\n".join(parts)
