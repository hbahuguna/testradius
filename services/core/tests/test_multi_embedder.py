import pytest
import numpy as np
import tempfile
from pathlib import Path


class TestMultiModelEmbedderInstantiation:
    """Test MultiModelEmbedder instantiation and defaults."""

    def test_default_instantiation(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        assert embedder.embedding_dim == 768
        assert embedder._siamese_path == "./method2test/"
        assert embedder._siamese_batch_size == 16
        assert embedder._mpnet_batch_size == 32

    def test_custom_parameters(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder(
            siamese_path="/custom/path",
            target_dim=512,
            siamese_batch_size=8,
            mpnet_batch_size=16
        )
        assert embedder.embedding_dim == 512
        assert embedder._siamese_path == "/custom/path"
        assert embedder._siamese_batch_size == 8
        assert embedder._mpnet_batch_size == 16

    def test_properties_default_state(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        assert embedder.siamese_loaded is False
        assert embedder.mpnet_loaded is False


class TestMultiModelEmbedderDimensionNormalization:
    """Test dimension normalization."""

    def test_pad_384_to_768(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        input_emb = [[0.1] * 384]
        result = embedder.normalize_dimension(input_emb, 768)
        assert len(result[0]) == 768
        assert result[0][:384] == [0.1] * 384
        assert result[0][384:] == [0.0] * 384

    def test_truncate_1024_to_768(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        input_emb = [[0.1] * 1024]
        result = embedder.normalize_dimension(input_emb, 768)
        assert len(result[0]) == 768
        assert result[0] == [0.1] * 768

    def test_keep_768_as_is(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        input_emb = [[0.1] * 768]
        result = embedder.normalize_dimension(input_emb, 768)
        assert len(result[0]) == 768
        assert result[0] == [0.1] * 768

    def test_default_target_dim(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder(target_dim=512)
        input_emb = [[0.1] * 384]
        result = embedder.normalize_dimension(input_emb)
        assert len(result[0]) == 512

    def test_batch_normalization(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        input_emb = [[0.1] * 384, [0.2] * 384, [0.3] * 384]
        result = embedder.normalize_dimension(input_emb, 768)
        assert len(result) == 3
        assert all(len(r) == 768 for r in result)


class TestMultiModelEmbedderSimilarity:
    """Test cosine similarity computation."""

    def test_identical_vectors(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        query = [0.1] * 768
        targets = [[0.1] * 768]
        scores = embedder.compute_similarity(query, targets)
        assert len(scores) == 1
        assert abs(scores[0][1] - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        query = [1.0] + [0.0] * 767
        targets = [[0.0] * 768]
        targets[0][0] = 0.0
        targets[0][1] = 1.0
        scores = embedder.compute_similarity(query, targets)
        assert abs(scores[0][1]) < 0.001

    def test_top_k_filtering(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        query = [0.5] * 768
        targets = [
            [0.1] * 768,
            [0.9] * 768,
            [0.5] * 768,
            [0.0] * 768
        ]
        scores = embedder.compute_similarity(query, targets, top_k=2)
        assert len(scores) == 2
        assert scores[0][0] == 2  # Most similar

    def test_empty_query(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        scores = embedder.compute_similarity([], [[0.1] * 768])
        assert scores == []

    def test_empty_targets(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        scores = embedder.compute_similarity([0.1] * 768, [])
        assert scores == []

    def test_all_zeros(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        query = [0.0] * 768
        targets = [[0.0] * 768]
        scores = embedder.compute_similarity(query, targets)
        assert scores[0][1] == 0.0


class TestMultiModelEmbedderBatch:
    """Test batch embedding functionality."""

    def test_empty_input(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_batch([], model="siamese")
        assert result == []

    def test_empty_input_auto(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_batch([], model="auto")
        assert result == []

    def test_single_text(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        # Without actual model loaded, should return BM25 fallback (zeros)
        result = embedder.embed_batch(["test text"], model="siamese")
        assert len(result) == 1
        assert len(result[0]) == 768

    def test_batch_of_texts(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        texts = ["text 1", "text 2", "text 3"]
        result = embedder.embed_batch(texts, model="siamese")
        assert len(result) == 3
        for r in result:
            assert len(r) == 768


class TestMultiModelEmbedderModelSpecific:
    """Test model-specific embedding methods."""

    def test_embed_siamese_returns_768_normalized(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_siamese(["test"])
        # Should be normalized to target_dim (768)
        assert len(result[0]) == 768

    def test_embed_mpnet_returns_768(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_mpnet(["test"])
        assert len(result[0]) == 768

    def test_embed_bm25_returns_768(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_bm25(["test"])
        assert len(result[0]) == 768

    def test_invalid_model_raises(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        with pytest.raises(ValueError, match="Unknown model"):
            embedder.embed_batch(["test"], model="invalid")


class TestMultiModelEmbedderAutoMode:
    """Test auto model selection."""

    def test_auto_embeds_empty(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        result = embedder.embed_batch([], model="auto")
        assert result == []

    def test_auto_returns_768_normalized(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        # Auto mode should normalize to target_dim
        result = embedder.embed_batch(["test"], model="auto")
        assert len(result[0]) == 768


class TestMultiModelEmbedderRepr:
    """Test string representation."""

    def test_repr_contains_key_values(self):
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        embedder = MultiModelEmbedder()
        repr_str = repr(embedder)
        assert "MultiModelEmbedder" in repr_str
        assert "target_dim" in repr_str
        assert "siamese_loaded" in repr_str