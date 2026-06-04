import os
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"
DEFAULT_BATCH_SIZE = 32


class Embedder:
    """Generate vector embeddings for text using sentence-transformers.
    
    Supports:
    - Lazy-loading model on first call
    - Batch encoding
    - Cosine similarity computation
    - BM25 fallback
    """
    
    def __init__(
        self,
        model_name: str = None,
        batch_size: int = None
    ):
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL_NAME", DEFAULT_MODEL)
        self.batch_size = batch_size or int(os.getenv("EMBEDDING_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
        self._model = None
        self._bm25 = None
    
    def load_model(self):
        """Lazy-load the sentence-transformers model on first call."""
        if self._model is not None:
            return
        
        logger.info(f"Loading embedding model: {self.model_name}")
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            logger.info(f"Model loaded: {self.model_name}")
        except Exception as e:
            logger.warning(f"Failed to load sentence-transformers model: {e}")
            logger.info("BM25 will be used as fallback")
            self._model = None
    
    def _load_bm25(self):
        """Lazy-load BM25 as fallback."""
        if self._bm25 is not None:
            return
        
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi
        except ImportError:
            logger.warning("rank-bm25 not available, BM25 fallback disabled")
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode a batch of texts to embeddings."""
        if not texts:
            return []
        
        if self._model is None:
            self.load_model()
        
        if self._model is not None:
            try:
                embeddings = self._model.encode(
                    texts,
                    batch_size=self.batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True
                )
                return embeddings.tolist()
            except Exception as e:
                logger.warning(f"Embedding failed: {e}, falling back to BM25")
        
        return self._bm25_fallback(texts)
    
    def embed_single(self, text: str) -> List[float]:
        """Encode a single text to embedding."""
        if not text:
            return [0.0] * 768
        
        embeddings = self.embed_batch([text])
        return embeddings[0] if embeddings else [0.0] * 768
    
    def similarity(
        self,
        query: List[float],
        targets: List[List[float]],
        top_k: int = 50
    ) -> List[Tuple[int, float]]:
        """Compute cosine similarity between query and targets."""
        if not targets or not query:
            return []
        
        import numpy as np
        
        query_vec = np.array(query)
        target_matrix = np.array(targets)
        
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        target_norm = target_matrix / (np.linalg.norm(target_matrix, axis=1, keepdims=True) + 1e-8)
        
        similarities = np.dot(target_norm, query_norm)
        
        if top_k >= len(similarities):
            top_indices = np.argsort(similarities)[::-1]
        else:
            top_indices = np.argpartition(similarities, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
        
        return [(int(idx), float(similarities[idx])) for idx in top_indices]
    
    def _bm25_fallback(self, texts: List[str]) -> List[List[float]]:
        """BM25-based pseudo-embeddings as fallback."""
        self._load_bm25()
        
        if self._bm25 is None:
            return [[0.0] * 768 for _ in texts]
        
        tokenized = [text.lower().split() for text in texts]
        
        try:
            bm25 = self._bm25(tokenized)
        except Exception:
            return [[0.0] * 768 for _ in texts]
        
        all_tokens = [token for text in tokenized for token in text]
        if all_tokens:
            avg_doc = list(set(all_tokens))[:100]
            scores = bm25.get_scores(avg_doc)
            
            max_score = max(abs(s) for s in scores) if scores else 1
            if max_score == 0:
                max_score = 1
            
            vectors = []
            for score in scores:
                normalized = score / max_score
                vector = [normalized * (hash(str(i)) % 1000 / 1000) for i in range(768)]
                vectors.append(vector)
            return vectors
        
        return [[0.0] * 768 for _ in texts]
    
    def get_embedding_dimension(self) -> int:
        """Get the embedding dimension for the current model."""
        if self._model is None:
            self.load_model()
        
        if self._model is not None:
            return self._model.get_sentence_embedding_dimension()
        
        return 768