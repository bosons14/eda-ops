"""Search the OpenROAD / Yosys / OpenSTA documentation index built by eda-rag.

The index is a directory holding `chunks.jsonl` (one JSON object per passage: tool, source, path, url,
section, text), as written by eda-rag's `03_index.py` to `data/index/struct/`.

Keyword search (BM25) is pure Python and always available. When the index also has `faiss.index` and
`sentence-transformers` + `faiss` are importable, results are fused with dense retrieval (reciprocal
rank fusion) and re-scored by a cross-encoder. This module only retrieves: the calling model writes
the answer from the passages, so no LLM API key is needed.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

TOOLS = ("openroad", "yosys", "opensta")
MODES = ("auto", "bm25", "hybrid", "hybrid_rerank")
MAX_PASSAGE = 1800  # characters of each passage returned to the model
TOKEN = re.compile(r"-{0,2}[A-Za-z0-9_][A-Za-z0-9_.\-]*")

# Must match the models eda-rag used to build faiss.index (embed_model.txt in the index wins).
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
QUERY_PREFIX = os.environ.get("QUERY_PREFIX", "Represent this sentence for searching relevant passages: ")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-base")


def tokenize(text: str) -> list[str]:
    """Keep EDA identifiers whole (repair_design, -max_fanout, set_input_delay) and also emit their
    parts, so 'max fanout' still matches '-max_fanout'. Same tokenizer as eda-rag."""
    out: list[str] = []
    for t in TOKEN.findall(text.lower()):
        t = t.strip(".-") or t
        out.append(t)
        if "_" in t or "-" in t:
            out += [p for p in re.split(r"[_\-]+", t) if p]
    return out


def _default_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "eda-ops")
    return Path(base) / "docs-index"


def find_index_dir() -> Path | None:
    """EDAOPS_DOCS_INDEX may point at the index dir itself, at data/index, or at the eda-rag checkout."""
    roots = [Path(p).expanduser() for p in [os.environ.get("EDAOPS_DOCS_INDEX")] if p]
    roots.append(_default_dir())
    for root in roots:
        for d in (root, root / "struct", root / "data" / "index" / "struct"):
            if (d / "chunks.jsonl").is_file():
                return d.resolve()
    return None


class BM25:
    """Okapi BM25 over pre-tokenized documents, with an inverted index so a query only touches
    the documents that contain its terms."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / self.n) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                self.postings.setdefault(term, []).append((i, tf))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def scores(self, query: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in self.postings[term]:
                norm = tf + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                out[i] = out.get(i, 0.0) + idf * tf * (self.k1 + 1) / norm
        return out


def rrf(*ranked: list[int], k: int = 60) -> list[int]:
    """Reciprocal rank fusion: scale-free, so BM25 and cosine scores need no normalisation."""
    fused: dict[int, float] = {}
    for lst in ranked:
        for rank, i in enumerate(lst):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused, key=lambda i: -fused[i])


class DocIndex:
    def __init__(self, directory: Path):
        self.dir = directory
        with open(directory / "chunks.jsonl", encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f if line.strip()]
        self.bm25 = BM25([tokenize(c["text"]) for c in self.chunks])
        model_file = directory / "embed_model.txt"
        self.embed_model = model_file.read_text().strip() if model_file.is_file() else EMBED_MODEL
        self._faiss = None
        self._dense_error: str | None = None

    # -- availability ---------------------------------------------------------------------------
    def dense_available(self) -> bool:
        if self._faiss is not None:
            return True
        if self._dense_error is not None:
            return False
        if not (self.dir / "faiss.index").is_file():
            self._dense_error = "no faiss.index in the index (built with --no-dense)"
            return False
        try:
            import faiss
            import sentence_transformers  # noqa: F401
        except ImportError as exc:
            self._dense_error = f"{exc.name} not installed in the MCP server's Python (see EDAOPS_DOCS_DENSE)"
            return False
        self._faiss = faiss.read_index(str(self.dir / "faiss.index"))
        return True

    # -- retrieval primitives: each returns chunk indices, best first -------------------------
    def _ok(self, i: int, tools: set[str] | None) -> bool:
        return tools is None or self.chunks[i].get("tool") in tools

    def keyword(self, q: str, k: int, tools: set[str] | None) -> list[int]:
        s = self.bm25.scores(tokenize(q))
        return [i for i in sorted(s, key=lambda i: -s[i]) if self._ok(i, tools)][:k]

    def dense(self, q: str, k: int, tools: set[str] | None) -> list[int]:
        qv = _embedder(self.embed_model).encode([QUERY_PREFIX + q], normalize_embeddings=True)
        pool = k if tools is None else min(len(self.chunks), k * 20)
        _, idx = self._faiss.search(qv.astype("float32"), pool)
        return [int(i) for i in idx[0] if i >= 0 and self._ok(int(i), tools)][:k]

    def rerank(self, q: str, cands: list[int], k: int) -> list[int]:
        scores = _reranker().predict([(q, self.chunks[i]["text"]) for i in cands], batch_size=32)
        return [i for _, i in sorted(zip(scores, cands), key=lambda p: -float(p[0]))][:k]

    def search(self, q: str, k: int = 5, tools: set[str] | None = None, mode: str = "auto",
               pool: int = 50) -> tuple[str, list[int], str | None]:
        note = None
        if mode == "auto":
            mode = "hybrid_rerank" if self.dense_available() else "bm25"
        elif mode != "bm25" and not self.dense_available():
            note = f"'{mode}' unavailable ({self._dense_error}); used bm25"
            mode = "bm25"
        if mode == "bm25":
            return mode, self.keyword(q, k, tools), note
        fused = rrf(self.dense(q, pool, tools), self.keyword(q, pool, tools))
        hits = self.rerank(q, fused[:pool], k) if mode == "hybrid_rerank" else fused[:k]
        return mode, hits, note


@lru_cache(maxsize=1)
def _embedder(model: str):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model)


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANK_MODEL, max_length=512)


@lru_cache(maxsize=2)
def _load(directory: str, mtime: float) -> DocIndex:  # mtime in the key: rebuilt index is reloaded
    return DocIndex(Path(directory))


def get_index() -> DocIndex | None:
    d = find_index_dir()
    return _load(str(d), (d / "chunks.jsonl").stat().st_mtime) if d else None


NO_INDEX = ("No documentation index found. Build one with eda-rag (https://github.com/bosons14/eda-rag): "
            "python 01_ingest.py && python 02_chunk.py && python 03_index.py --chunks struct [--no-dense], "
            "then set EDAOPS_DOCS_INDEX to the eda-rag folder (or copy data/index/struct to "
            f"{_default_dir()}).")


def status() -> dict:
    idx = get_index()
    if idx is None:
        return {"available": False, "hint": NO_INDEX}
    dense = idx.dense_available()
    return {"available": True, "index": str(idx.dir), "passages": len(idx.chunks),
            "by_tool": dict(Counter(c.get("tool", "?") for c in idx.chunks)),
            "modes": ["bm25", "hybrid", "hybrid_rerank"] if dense else ["bm25"],
            **({} if dense else {"dense_unavailable": idx._dense_error})}


def search(query: str, k: int = 5, tools: list[str] | None = None, mode: str = "auto") -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Empty query."}
    if mode not in MODES:
        return {"ok": False, "error": f"mode must be one of {list(MODES)}"}
    want = {t.lower() for t in tools} if tools else None
    if want and not want <= set(TOOLS):
        return {"ok": False, "error": f"tools must be among {list(TOOLS)}"}
    idx = get_index()
    if idx is None:
        return {"ok": False, "error": NO_INDEX}
    used, hits, note = idx.search(query, k=max(1, min(int(k), 20)), tools=want, mode=mode)
    results = []
    for n, i in enumerate(hits, 1):
        c = idx.chunks[i]
        text = c["text"]
        results.append({"n": n, "tool": c.get("tool"), "source": c.get("source", "docs"),
                        "path": c.get("path"), "section": c.get("section", ""), "url": c.get("url"),
                        "text": text if len(text) <= MAX_PASSAGE else text[:MAX_PASSAGE] + " ..."})
    out = {"ok": True, "query": query, "mode": used, "results": results}
    if note:
        out["note"] = note
    if not results:
        out["hint"] = "No passage matched. Retry with the exact command or option name, or fewer words."
    return out
