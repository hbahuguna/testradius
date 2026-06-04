import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add path for direct import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from testsquad_core.intelligence.embedder import Embedder


class TestEmbedder:
    """Test suite for Embedder class."""

    @pytest.fixture
    def embedder(self):
        return Embedder()

    # --- Test initialization ---

    def test_init_default(self, embedder):
        """Test default initialization."""
        assert embedder.model_name == "sentence-transformers/all-mpnet-base-v2"
        assert embedder.batch_size == 32
        assert embedder._model is None

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        e = Embedder(model_name="custom-model", batch_size=64)
        assert e.model_name == "custom-model"
        assert e.batch_size == 64

    def test_init_from_env_vars(self):
        """Test initialization from environment variables."""
        with patch.dict(os.environ, {"EMBEDDING_MODEL_NAME": "env-model", "EMBEDDING_BATCH_SIZE": "16"}):
            e = Embedder()
            assert e.model_name == "env-model"
            assert e.batch_size == 16

    # --- Test lazy loading ---

    def test_model_not_loaded_on_init(self, embedder):
        """Test model is not loaded on initialization."""
        assert embedder._model is None

    def test_load_model_lazy(self, embedder):
        """Test model lazy loading."""
        # Model should still be None after calling load_model without sentence-transformers
        embedder.load_model()
        assert embedder._model is None  # Falls back because module not available

    # --- Test batch encoding ---

    def test_embed_batch_empty(self, embedder):
        """Test empty batch returns empty list."""
        result = embedder.embed_batch([])
        assert result == []

    def test_embed_batch_single(self, embedder):
        """Test batch with single text."""
        result = embedder.embed_batch(["hello world"])
        assert len(result) == 1
        assert len(result[0]) == 768

    def test_embed_batch_multiple(self, embedder):
        """Test batch with multiple texts."""
        texts = ["hello", "world", "test"]
        result = embedder.embed_batch(texts)
        assert len(result) == 3
        assert all(len(v) == 768 for v in result)

    def test_embed_batch_large(self, embedder):
        """Test large batch doesn't crash."""
        texts = ["text " + str(i) for i in range(100)]
        result = embedder.embed_batch(texts)
        assert len(result) == 100

    # --- Test single encoding ---

    def test_embed_single_empty(self, embedder):
        """Test single embedding for empty string."""
        result = embedder.embed_single("")
        assert len(result) == 768

    def test_embed_single_text(self, embedder):
        """Test single embedding for text."""
        result = embedder.embed_single("hello world")
        assert len(result) == 768

    def test_embed_single_none(self, embedder):
        """Test single embedding for None-like input."""
        result = embedder.embed_single(None)
        assert len(result) == 768

    # --- Test similarity ---

    def test_similarity_empty(self, embedder):
        """Test similarity with empty inputs."""
        result = embedder.similarity([], [])
        assert result == []

    def test_similarity_identical(self, embedder):
        """Test similarity for identical vectors."""
        vec = [1.0] * 768
        result = embedder.similarity(vec, [vec])
        assert len(result) == 1
        assert result[0][0] == 0
        assert abs(result[0][1] - 1.0) < 0.001

    def test_similarity_orthogonal(self, embedder):
        """Test similarity for orthogonal vectors."""
        import numpy as np
        vec1 = [1.0] * 384 + [-1.0] * 384
        vec2 = [1.0] * 384 + [1.0] * 384
        result = embedder.similarity(vec1, [vec2])
        # Should be close to 0 for orthogonal
        assert abs(result[0][1]) < 0.1

    def test_similarity_top_k(self, embedder):
        """Test top-k filtering."""
        query = [1.0] * 768
        targets = [[1.0] * 768, [0.5] * 768, [0.0] * 768]
        result = embedder.similarity(query, targets, top_k=2)
        assert len(result) == 2

    def test_similarity_order(self, embedder):
        """Test results are sorted by similarity descending."""
        query = [1.0] * 768
        targets = [
            [0.1] * 768,
            [1.0] * 768,
            [0.5] * 768
        ]
        result = embedder.similarity(query, targets)
        scores = [r[1] for r in result]
        assert scores == sorted(scores, reverse=True)

    # --- Test edge cases ---

    def test_very_long_text(self, embedder):
        """Test handling of very long text."""
        long_text = "word " * 10000
        result = embedder.embed_single(long_text)
        assert len(result) == 768

    def test_unicode_text(self, embedder):
        """Test handling of unicode text."""
        result = embedder.embed_single("Hello 世界 🎉")
        assert len(result) == 768

    def test_special_characters(self, embedder):
        """Test handling of special characters."""
        result = embedder.embed_single("!@#$%^&*()_+-=[]{}|;':\",./<>?")
        assert len(result) == 768

    def test_get_embedding_dimension(self, embedder):
        """Test getting embedding dimension."""
        dim = embedder.get_embedding_dimension()
        assert dim == 768


class TestEmbedderBM25Fallback:
    """Test BM25 fallback functionality."""

    @pytest.fixture
    def embedder(self):
        return Embedder()

    def test_bm25_fallback_returns_vectors(self, embedder):
        """Test BM25 fallback returns vectors."""
        # When sentence-transformers unavailable, should return vectors
        result = embedder.embed_batch(["test", "text"])
        assert len(result) == 2
        assert all(len(v) == 768 for v in result)

    def test_bm25_fallback_zero_on_failure(self, embedder):
        """Test BM25 fallback with no tokens."""
        result = embedder.embed_batch([""])
        assert len(result) == 1
        assert len(result[0]) == 768


class TestEmbedderIntegration:
    """Integration-style tests for Embedder."""

    @pytest.fixture
    def embedder(self):
        return Embedder()

    def test_end_to_end_text_to_similarity(self, embedder):
        """Test full pipeline: text -> embedding -> similarity."""
        texts = [
            "The cat sat on the mat",
            "A dog ran in the park",
            "The cat chased the dog"
        ]
        
        embeddings = embedder.embed_batch(texts)
        assert len(embeddings) == 3
        
        # Similarity of text to itself should be high
        sim = embedder.similarity(embeddings[0], embeddings)
        assert sim[0][1] > 0.9  # Should be highest

    def test_semantic_similarity(self, embedder):
        """Test that similar sentences have higher similarity."""
        embeddings = embedder.embed_batch([
            "machine learning is great",
            "deep learning is awesome",
            "the weather is nice today"
        ])
        
        # ML sentences should be more similar to each other than to weather
        ml_sim = embedder.similarity(embeddings[0], [embeddings[1]])[0][1]
        weather_sim = embedder.similarity(embeddings[0], [embeddings[2]])[0][1]
        
        assert ml_sim > weather_sim