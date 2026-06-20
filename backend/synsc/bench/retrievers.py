"""In-process retrievers for the benchmark — baselines and Delphi-style hybrid.

All retrievers operate on an in-memory :class:`Corpus` so the benchmark runs
without a database. They mirror the *shape* of the real retrieval strategies:

- ``NaiveGrepRetriever``  — what most agents do today: dump every file with a
  token match, unranked. High recall, terrible token economy.
- ``SmartGrepRetriever``  — identifier/definition-aware ripgrep-style ranking.
- ``BM25Retriever``       — classic lexical ranking.
- ``SymbolRetriever``     — exact symbol-name lookup via Delphi's parsers.
- ``HybridRetriever``     — normalized fusion of BM25 + symbol + substring,
  the strategy Delphi ships in ``hybrid_retrieval.py``.

Each ``retrieve`` returns ``(ranked_doc_ids, token_cost)`` where token_cost is
the number of tokens an agent would have to read to consume the answer (top-k
for ranked retrievers; all matched files for naive grep).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from synsc.bench.corpus import Corpus

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokenize(text: str) -> list[str]:
    """Tokenize, expanding identifiers into subwords.

    ``validate_token`` indexes as ``validate_token``, ``validate``, ``token`` so
    a subword query ("token validation") matches identifier-dense code — the
    same lexical trick the production hybrid retriever relies on.
    """
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        low = tok.lower()
        out.append(low)
        subs = _split_identifier(tok)
        if subs != [low]:
            out.extend(subs)
    return out


def _split_identifier(token: str) -> list[str]:
    """Split camelCase / snake_case into subwords for query expansion."""
    parts = re.split(r"[_\W]+", token)
    out: list[str] = []
    for part in parts:
        out.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", part) or [part])
    return [p.lower() for p in out if p]


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for tok in _TOKEN_RE.findall(query):
        terms.append(tok.lower())
        terms.extend(_split_identifier(tok))
    # Drop trivial stopwords that add noise to lexical matching.
    stop = {"the", "a", "an", "of", "to", "is", "in", "for", "where", "how", "what", "that", "this"}
    return [t for t in dict.fromkeys(terms) if t not in stop and len(t) > 1]


class Retriever:
    name = "base"

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        raise NotImplementedError

    @staticmethod
    def _token_cost(corpus: Corpus, doc_ids: list[str]) -> int:
        total = 0
        for doc_id in doc_ids:
            doc = corpus.get(doc_id)
            if doc:
                total += doc.token_count()
        return total


class NaiveGrepRetriever(Retriever):
    name = "naive_grep"

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        terms = set(_query_terms(query))
        matched: list[str] = []
        for doc in corpus:
            doc_tokens = set(_tokenize(doc.content))
            if terms & doc_tokens:
                matched.append(doc.doc_id)
        # Naive grep is unranked and dumps every matched file → full token cost.
        return matched, self._token_cost(corpus, matched)


class SmartGrepRetriever(Retriever):
    name = "smart_grep"

    _DEF_RE = re.compile(r"\b(?:def|class|func|function|fn|interface|struct|type|trait|impl)\b")

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        terms = _query_terms(query)
        scores: dict[str, float] = {}
        for doc in corpus:
            lines = doc.content.splitlines()
            score = 0.0
            for line in lines:
                low = line.lower()
                hits = sum(low.count(t) for t in terms)
                if hits and self._DEF_RE.search(line):
                    score += hits * 3.0  # definition lines weigh more
                else:
                    score += hits
            if score:
                scores[doc.doc_id] = score
        ranked = sorted(scores, key=lambda d: scores[d], reverse=True)
        return ranked, self._token_cost(corpus, ranked[:k])


class BM25Retriever(Retriever):
    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        docs = list(corpus)
        doc_tokens = {d.doc_id: _tokenize(d.content) for d in docs}
        lengths = {d: len(toks) for d, toks in doc_tokens.items()}
        avgdl = (sum(lengths.values()) / len(lengths)) if lengths else 0.0
        n_docs = len(docs)

        df: Counter = Counter()
        tf: dict[str, Counter] = {}
        for doc_id, toks in doc_tokens.items():
            counts = Counter(toks)
            tf[doc_id] = counts
            for term in counts:
                df[term] += 1

        terms = _query_terms(query)
        scores: dict[str, float] = defaultdict(float)
        for term in terms:
            if term not in df:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            for doc_id in doc_tokens:
                freq = tf[doc_id].get(term, 0)
                if not freq:
                    continue
                denom = freq + self.k1 * (
                    1 - self.b + self.b * (lengths[doc_id] / avgdl if avgdl else 0)
                )
                scores[doc_id] += idf * (freq * (self.k1 + 1)) / denom
        ranked = sorted(scores, key=lambda d: scores[d], reverse=True)
        return ranked, self._token_cost(corpus, ranked[:k])


class SymbolRetriever(Retriever):
    name = "symbol"

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        from synsc.parsing.registry import get_parser_registry

        registry = get_parser_registry()
        terms = set(_query_terms(query))
        scores: dict[str, float] = defaultdict(float)
        for doc in corpus:
            parser = registry.get_parser(doc.language) if doc.language else None
            if parser is None:
                continue
            try:
                symbols = parser.extract_symbols(doc.content)
            except Exception:
                continue
            for sym in symbols:
                name_terms = set(_split_identifier(sym.name)) | {sym.name.lower()}
                overlap = len(terms & name_terms)
                if overlap:
                    scores[doc.doc_id] += overlap
        ranked = sorted(scores, key=lambda d: scores[d], reverse=True)
        return ranked, self._token_cost(corpus, ranked[:k])


class HybridRetriever(Retriever):
    """Normalized fusion of BM25 + symbol + substring — Delphi's strategy."""

    name = "hybrid"

    def __init__(self) -> None:
        self.bm25 = BM25Retriever()
        self.symbol = SymbolRetriever()
        self.weights = {"bm25": 1.0, "symbol": 1.2, "substr": 0.5}

    @staticmethod
    def _normalized_scores(ranked: list[str]) -> dict[str, float]:
        n = len(ranked)
        if n == 0:
            return {}
        return {doc_id: 1.0 - (i / n) for i, doc_id in enumerate(ranked)}

    def _substring_scores(self, corpus: Corpus, query: str) -> list[str]:
        terms = _query_terms(query)
        scores: dict[str, float] = defaultdict(float)
        for doc in corpus:
            low = doc.content.lower()
            for term in terms:
                c = low.count(term)
                if c:
                    scores[doc.doc_id] += c
        return sorted(scores, key=lambda d: scores[d], reverse=True)

    def retrieve(self, corpus: Corpus, query: str, k: int) -> tuple[list[str], int]:
        bm25_ranked, _ = self.bm25.retrieve(corpus, query, k)
        symbol_ranked, _ = self.symbol.retrieve(corpus, query, k)
        substr_ranked = self._substring_scores(corpus, query)

        contributions = {
            "bm25": self._normalized_scores(bm25_ranked),
            "symbol": self._normalized_scores(symbol_ranked),
            "substr": self._normalized_scores(substr_ranked),
        }
        fused: dict[str, float] = defaultdict(float)
        for source, scores in contributions.items():
            w = self.weights[source]
            for doc_id, score in scores.items():
                fused[doc_id] += w * score
        ranked = sorted(fused, key=lambda d: fused[d], reverse=True)
        return ranked, self._token_cost(corpus, ranked[:k])


def default_retrievers() -> list[Retriever]:
    return [
        NaiveGrepRetriever(),
        SmartGrepRetriever(),
        BM25Retriever(),
        SymbolRetriever(),
        HybridRetriever(),
    ]
