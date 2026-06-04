import logging
import os
from typing import List, Tuple, Optional
import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    from transformers import AutoTokenizer, AutoModel
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available, Siamese embeddings disabled")


class MultiModelEmbedder:
    """Unified embedder supporting multiple models.
    
    Supports:
    - Siamese: Fine-tuned model from local path (384-dim)
    - MPNet: all-mpnet-base-v2 (768-dim)
    - BM25: Pseudo-embeddings fallback
    
    Design:
    - Lazy-load models on first call
    - Cache model instances
    - Dimension normalization (pad/truncate to 768)
    - Batch processing with configurable sizes
    """
    
    DEFAULT_TARGET_DIM = 768
    SIAMESE_DIM = 384
    MPNET_DIM = 768
    
    def __init__(
        self,
        siamese_path: str = "./method2test/",
        target_dim: int = DEFAULT_TARGET_DIM,
        siamese_batch_size: int = 16,
        mpnet_batch_size: int = 32,
        use_fp16: bool = False,
    ):
        self._siamese_path = siamese_path
        self._target_dim = target_dim
        self._siamese_batch_size = siamese_batch_size
        self._mpnet_batch_size = mpnet_batch_size
        self._use_fp16 = use_fp16
        
        self._siamese_model = None
        self._siamese_tokenizer = None
        self._mpnet_model = None
        self._mpnet_tokenizer = None
        self._bm25 = None
    
    def _load_siamese(self) -> bool:
        """Lazy-load Siamese model from local path."""
        if self._siamese_model is not None:
            return True
            
        if not TORCH_AVAILABLE:
            logger.warning("PyTorch not available, cannot load Siamese model")
            return False
            
        try:
            logger.info(f"Loading Siamese model from {self._siamese_path}")
            self._siamese_tokenizer = AutoTokenizer.from_pretrained(self._siamese_path)
            self._siamese_model = AutoModel.from_pretrained(self._siamese_path)
            self._siamese_model.eval()
            logger.info(f"Siamese model loaded: {self.SIAMESE_DIM}-dim")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to load Siamese model: {e}")
            self._siamese_model = None
            self._siamese_tokenizer = None
            return False
    
    def _load_mpnet(self) -> bool:
        """Lazy-load MPNet model."""
        if self._mpnet_model is not None:
            return True
            
        try:
            logger.info("Loading MPNet model (all-mpnet-base-v2)")
            from sentence_transformers import SentenceTransformer
            self._mpnet_model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
            logger.info("MPNet model loaded: 768-dim")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to load MPNet model: {e}")
            self._mpnet_model = None
            return False
    
    def _load_bm25(self) -> bool:
        """Lazy-load BM25."""
        if self._bm25 is not None:
            return True
            
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi
            logger.info("BM25 loaded")
            return True
            
        except ImportError:
            logger.warning("rank-bm25 not available")
            self._bm25 = None
            return False
    
    def embed_siamese(self, texts: List[str]) -> List[List[float]]:
        """Embed using Siamese model (384-dim)."""
        if not texts:
            return []
        
        if self._siamese_model is None:
            if not self._load_siamese():
                return self._bm25_fallback(texts)
        
        if self._siamese_model is None:
            return self._bm25_fallback(texts)
        
        embeddings = []
        batch_size = self._siamese_batch_size
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            try:
                encoded = self._siamese_tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=128,
                    return_tensors="pt"
                )
                
                with torch.no_grad():
                    outputs = self._siamese_model(**encoded)
                
                last_hidden = outputs.last_hidden_state
                attention_mask = encoded["attention_mask"]
                input_mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
                sum_embeddings = torch.sum(last_hidden * input_mask_expanded, 1)
                sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                embeddings_batch = (sum_embeddings / sum_mask).numpy()
                
                embeddings.extend(embeddings_batch.tolist())
                
            except Exception as e:
                logger.warning(f"Siamese embedding failed: {e}")
                for _ in range(len(batch)):
                    embeddings.append([0.0] * self.SIAMESE_DIM)
        
        return embeddings
    
    def embed_mpnet(self, texts: List[str]) -> List[List[float]]:
        """Embed using MPNet model (768-dim)."""
        if not texts:
            return []
        
        if self._mpnet_model is None:
            if not self._load_mpnet():
                return self._bm25_fallback(texts)
        
        if self._mpnet_model is None:
            return self._bm25_fallback(texts)
        
        try:
            embeddings = self._mpnet_model.encode(
                texts,
                batch_size=self._mpnet_batch_size,
                show_progress_bar=False,
                convert_to_numpy=True
            )
            return embeddings.tolist()
            
        except Exception as e:
            logger.warning(f"MPNet embedding failed: {e}")
            return self._bm25_fallback(texts)
    
    def embed_bm25(self, texts: List[str]) -> List[List[float]]:
        """BM25 pseudo-embeddings (768-dim)."""
        return self._bm25_fallback(texts)
    
    def _bm25_fallback(self, texts: List[str]) -> List[List[float]]:
        """Generate BM25 pseudo-embeddings."""
        self._load_bm25()
        
        if self._bm25 is None:
            return [[0.0] * self._target_dim for _ in texts]
        
        tokenized = [text.lower().split() for text in texts]
        
        try:
            bm25 = self._bm25(tokenized)
        except Exception:
            return [[0.0] * self._target_dim for _ in texts]
        
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
                vector = [
                    normalized * (hash(str(i)) % 1000 / 1000)
                    for i in range(self._target_dim)
                ]
                vectors.append(vector)
            return vectors
        
        return [[0.0] * self._target_dim for _ in texts]
    
    def embed_batch(
        self,
        texts: List[str],
        model: str = "siamese",
        normalize: bool = True
    ) -> List[List[float]]:
        """Unified embedding interface.

        Args:
            texts: List of text strings to embed
            model: Model to use (siamese, mpnet, bm25, auto)
            normalize: If True, normalize to target_dim (768). If False,
                       return native dimension. Set False for Siamese-only paths.
        """
        if not texts:
            return []
        
        if model == "auto":
            if self._siamese_model is not None or self._load_siamese():
                embeddings = self.embed_siamese(texts)
                if embeddings and any(any(e) for e in embeddings):
                    if normalize:
                        return self.normalize_dimension(embeddings, self._target_dim)
                    return embeddings
            
            if self._mpnet_model is not None or self._load_mpnet():
                embeddings = self.embed_mpnet(texts)
                if embeddings and any(any(e) for e in embeddings):
                    return embeddings
            
            return self.embed_bm25(texts)
        
        if model == "siamese":
            embeddings = self.embed_siamese(texts)
        elif model == "mpnet":
            embeddings = self.embed_mpnet(texts)
        elif model == "bm25":
            embeddings = self.embed_bm25(texts)
        else:
            raise ValueError(f"Unknown model: {model}")
        
        if normalize:
            return self.normalize_dimension(embeddings, self._target_dim)
        return embeddings
    
    def normalize_dimension(
        self,
        embeddings: List[List[float]],
        target_dim: int = None
    ) -> List[List[float]]:
        """Normalize embeddings to target dimension."""
        if target_dim is None:
            target_dim = self._target_dim
        
        normalized = []
        
        for emb in embeddings:
            current_dim = len(emb)
            
            if current_dim == target_dim:
                normalized.append(emb)
            elif current_dim < target_dim:
                padded = list(emb) + [0.0] * (target_dim - current_dim)
                normalized.append(padded)
            else:
                truncated = emb[:target_dim]
                normalized.append(truncated)
        
        return normalized
    
    def compute_similarity(
        self,
        query: List[float],
        targets: List[List[float]],
        top_k: int = 50
    ) -> List[Tuple[int, float]]:
        """Compute cosine similarity between query and targets."""
        if not query or not targets:
            return []
        
        query_vec = np.array(query)
        target_matrix = np.array(targets)
        
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        target_norm = target_matrix / (
            np.linalg.norm(target_matrix, axis=1, keepdims=True) + 1e-8
        )
        
        similarities = np.dot(target_norm, query_norm)
        
        if top_k >= len(similarities):
            indices = np.argsort(similarities)[::-1]
        else:
            indices = np.argpartition(similarities, -top_k)[-top_k:]
            indices = indices[np.argsort(similarities[indices])[::-1]]
        
        return [(int(idx), float(similarities[idx])) for idx in indices]
    
    @property
    def embedding_dim(self) -> int:
        return self._target_dim
    
    @property
    def siamese_loaded(self) -> bool:
        return self._siamese_model is not None
    
    @property
    def mpnet_loaded(self) -> bool:
        return self._mpnet_model is not None
    
    def __repr__(self) -> str:
        return (
            f"MultiModelEmbedder("
            f"siamese_path={self._siamese_path}, "
            f"target_dim={self._target_dim}, "
            f"siamese_loaded={self.siamese_loaded}, "
            f"mpnet_loaded={self.mpnet_loaded})"
        )