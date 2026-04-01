"""BM25-based retrieval for paper reading sessions. Zero external dependencies."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class Chunk:
    """A chunk of paper text with its section header."""

    index: int
    text: str
    header: str = ""  # nearest preceding markdown header


# ---------------------------------------------------------------------------
# Markdown-aware chunking
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


def chunk_markdown(
    text: str,
    max_chars: int = 800,
    overlap: int = 100,
) -> list[Chunk]:
    """Split markdown text into chunks preserving section structure.

    1. Split on ``## `` / ``### `` boundaries (keeps section context).
    2. Within sections, split on double-newline (paragraph boundaries).
    3. Greedily merge consecutive paragraphs up to *max_chars*.
    4. Overlap the last *overlap* chars from the previous chunk.
    """
    if not text or not text.strip():
        return []

    # Split into (header, body) sections
    sections: list[tuple[str, str]] = []
    parts = _HEADER_RE.split(text)

    # re.split with 2 capture groups produces:
    #   [preamble, level, title, body, level, title, body, ...]
    # If text starts with a header, preamble is "".
    i = 0
    preamble = parts[0].strip() if parts else ""
    if preamble:
        sections.append(("", preamble))
    i = 1  # skip preamble (even if empty)

    while i + 2 < len(parts):
        _level = parts[i]      # e.g. "##"
        title = parts[i + 1]   # e.g. "Methods"
        body = parts[i + 2]
        sections.append((title.strip(), body))
        i += 3

    # If no headers found at all, treat entire text as one section
    if not sections:
        sections = [("", text)]

    chunks: list[Chunk] = []
    chunk_idx = 0
    prev_tail = ""

    for header, body in sections:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        if not paragraphs:
            continue

        current = prev_tail
        for para in paragraphs:
            candidate = f"{current}\n\n{para}".strip() if current else para
            if len(candidate) <= max_chars:
                current = candidate
            else:
                # Flush current chunk
                if current:
                    chunks.append(Chunk(index=chunk_idx, text=current, header=header))
                    chunk_idx += 1
                    # Keep tail for overlap
                    prev_tail = current[-overlap:] if overlap and len(current) > overlap else ""
                    current = f"{prev_tail}\n\n{para}".strip() if prev_tail else para
                else:
                    # Single paragraph exceeds max_chars — take it as-is
                    chunks.append(Chunk(index=chunk_idx, text=para, header=header))
                    chunk_idx += 1
                    prev_tail = para[-overlap:] if overlap and len(para) > overlap else ""
                    current = ""

        # Flush remaining
        if current:
            chunks.append(Chunk(index=chunk_idx, text=current, header=header))
            chunk_idx += 1
            prev_tail = current[-overlap:] if overlap and len(current) > overlap else ""

    return chunks


# ---------------------------------------------------------------------------
# BM25-Okapi index
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """In-memory BM25-Okapi index over a list of chunks."""

    def __init__(self, chunks: list[Chunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b

        self._doc_tokens: list[list[str]] = [_tokenize(c.text) for c in chunks]
        self._doc_lens = [len(t) for t in self._doc_tokens]
        self._avgdl = sum(self._doc_lens) / max(len(self._doc_lens), 1)
        self._n = len(chunks)

        # Document frequency: how many docs contain each term
        self._df: Counter[str] = Counter()
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] += 1

    def query(self, q: str, top_k: int = 4) -> list[Chunk]:
        """Return the top-k chunks most relevant to query *q*."""
        if not self.chunks:
            return []

        q_tokens = _tokenize(q)
        if not q_tokens:
            return self.chunks[:top_k]

        scores: list[tuple[float, int]] = []
        for idx, doc_tokens in enumerate(self._doc_tokens):
            score = self._score_doc(q_tokens, doc_tokens, self._doc_lens[idx])
            scores.append((score, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [self.chunks[idx] for _, idx in scores[:top_k]]

    def _score_doc(self, q_tokens: list[str], doc_tokens: list[str], doc_len: int) -> float:
        tf_map: Counter[str] = Counter(doc_tokens)
        score = 0.0
        for term in q_tokens:
            if term not in tf_map:
                continue
            tf = tf_map[term]
            df = self._df.get(term, 0)
            # IDF with smoothing
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
            # BM25 TF normalization
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl))
            score += idf * tf_norm
        return score


# ---------------------------------------------------------------------------
# Paper index facade
# ---------------------------------------------------------------------------


class PaperIndex:
    """Lazy, in-memory BM25 index for one paper's fulltext."""

    def __init__(self, fulltext: str, abstract: str | None = None) -> None:
        self.chunks = chunk_markdown(fulltext)
        # Always include abstract as chunk 0 (high-level orientation)
        if abstract and abstract.strip():
            self.chunks.insert(0, Chunk(index=0, text=abstract.strip(), header="Abstract"))
            # Re-index
            for i, c in enumerate(self.chunks):
                c.index = i
        self._bm25 = BM25Index(self.chunks)

    def retrieve(self, query: str, top_k: int = 4) -> list[Chunk]:
        """Return the top-k chunks most relevant to *query*."""
        return self._bm25.query(query, top_k=top_k)
