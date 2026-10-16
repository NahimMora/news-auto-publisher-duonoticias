"""Deduplicacion semantica con embeddings + FAISS."""
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from utils.http_client import HttpClient

DEDUP_INDEX_PATH = Path(os.getenv("DEDUP_INDEX_PATH", "./data/dedup_index.faiss"))
DEDUP_META_PATH = Path(os.getenv("DEDUP_META_PATH", "./data/dedup_meta.json"))
DEDUP_THRESHOLD = float(os.getenv("DEDUP_THRESHOLD", "0.88"))
DEDUP_SATURATION_THRESHOLD = float(os.getenv("DEDUP_SATURATION_THRESHOLD", "0.80"))
DEDUP_SATURATION_LIMIT = int(os.getenv("DEDUP_SATURATION_LIMIT", "3"))
DEDUP_WINDOW_HOURS = int(os.getenv("DEDUP_WINDOW_HOURS", "48"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_EMBEDDINGS_URL = os.getenv("OPENAI_EMBEDDINGS_URL", "https://api.openai.com/v1/embeddings")


@dataclass
class DedupResult:
    decision: str
    reason: str
    score: float
    match: Optional[Dict]


class EmbeddingClient:
    def __init__(self) -> None:
        self._provider = None
        self._model = None
        if OPENAI_API_KEY:
            self._provider = "openai"
            self._model = OPENAI_EMBEDDING_MODEL
        else:
            self._provider = "local"
            self._model = os.getenv("DEDUP_LOCAL_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, texts: List[str]) -> np.ndarray:
        if self._provider == "openai":
            return self._embed_openai(texts)
        return self._embed_local(texts)

    def _embed_openai(self, texts: List[str]) -> np.ndarray:
        client = HttpClient(headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, timeout=60, retries=3)
        try:
            resp = client.post(OPENAI_EMBEDDINGS_URL, json={"model": self._model, "input": texts})
            resp.raise_for_status()
            data = resp.json()
            vectors = [item["embedding"] for item in data.get("data", [])]
            return np.array(vectors, dtype="float32")
        finally:
            client.close()

    def _embed_local(self, texts: List[str]) -> np.ndarray:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError("sentence-transformers no disponible y falta OPENAI_API_KEY") from exc
        model = SentenceTransformer(self._model)
        vectors = model.encode(texts, normalize_embeddings=True)
        return np.array(vectors, dtype="float32")


class DedupStore:
    def __init__(self, dim: int) -> None:
        import faiss
        self._faiss = faiss
        self.index = faiss.IndexFlatIP(dim)
        self.items: List[Dict] = []

    @classmethod
    def load(cls, dim: int = 1536) -> "DedupStore":
        import faiss
        if DEDUP_META_PATH.exists() and DEDUP_INDEX_PATH.exists():
            items = json.loads(DEDUP_META_PATH.read_text(encoding="utf-8"))
            index = faiss.read_index(str(DEDUP_INDEX_PATH))
            store = cls(index.d)
            store.index = index
            store.items = items if isinstance(items, list) else []
            return store
        return cls(dim=dim)

    def save(self) -> None:
        DEDUP_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self.index, str(DEDUP_INDEX_PATH))
        DEDUP_META_PATH.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, vectors: np.ndarray, metas: List[Dict]) -> None:
        if vectors.size == 0:
            return
        vectors = self._normalize(vectors)
        self.index.add(vectors)
        self.items.extend(metas)

    def search(self, vector: np.ndarray, top_k: int = 5) -> List[Tuple[float, Dict]]:
        if self.index.ntotal == 0:
            return []
        vector = self._normalize(vector.reshape(1, -1))
        scores, indices = self.index.search(vector, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.items):
                continue
            results.append((float(score), self.items[idx]))
        return results

    def recent_titles(self, limit: int = 8) -> List[str]:
        return [item.get("titulo", "") for item in self.items[-limit:] if item.get("titulo")]

    def prune(self) -> None:
        if not self.items:
            return
        cutoff = time.time() - (DEDUP_WINDOW_HOURS * 3600)
        fresh = [item for item in self.items if item.get("ts", 0) >= cutoff]
        if len(fresh) == len(self.items):
            return
        self.items = fresh
        self.index = self._faiss.IndexFlatIP(self.index.d)
        if self.items:
            vectors = np.array([item.get("vec") for item in self.items], dtype="float32")
            vectors = self._normalize(vectors)
            self.index.add(vectors)

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


def build_text_for_embedding(item: Dict) -> str:
    parts = [item.get("titulo", ""), item.get("extracto", "")]
    for p in item.get("parrafos", [])[:3]:
        if isinstance(p, str):
            parts.append(p)
    text = "\n".join([p for p in parts if p]).strip()
    return text[:4000]


def check_duplicate(store: DedupStore, vector: np.ndarray) -> DedupResult:
    neighbors = store.search(vector, top_k=5)
    if not neighbors:
        return DedupResult("publicar", "Sin coincidencias", 0.0, None)
    best_score, best_meta = neighbors[0]
    if best_score >= DEDUP_THRESHOLD:
        return DedupResult("descartar", "Duplicado semantico", best_score, best_meta)

    saturation_count = 0
    cutoff = time.time() - (DEDUP_WINDOW_HOURS * 3600)
    for score, meta in neighbors:
        if score >= DEDUP_SATURATION_THRESHOLD and meta.get("ts", 0) >= cutoff:
            saturation_count += 1
    if saturation_count >= DEDUP_SATURATION_LIMIT:
        return DedupResult("descartar", "Saturacion tematica", best_score, best_meta)

    return DedupResult("publicar", "No duplicado", best_score, best_meta)


def ingest_items(store: DedupStore, items: List[Dict], vectors: np.ndarray) -> None:
    now = time.time()
    metas = []
    for item, vec in zip(items, vectors):
        metas.append({
            "titulo": item.get("titulo"),
            "url": item.get("url"),
            "ts": now,
            "vec": vec.tolist(),
        })
    store.add(vectors, metas)
    store.prune()
    store.save()
