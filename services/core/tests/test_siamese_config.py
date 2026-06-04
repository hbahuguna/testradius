import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestSiameseConfigDefaults:
    """Test default configuration values."""

    def test_default_siamese_threshold(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.siamese_threshold == 0.75

    def test_default_mpnet_threshold(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.mpnet_threshold == 0.85

    def test_default_bm25_threshold(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.bm25_threshold == 0.60

    def test_default_model_path(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.model_path == "./method2test/"

    def test_default_embedding_dim(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.embedding_dim == 384

    def test_default_siamese_batch_size(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.siamese_batch_size == 16

    def test_default_mpnet_batch_size(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.mpnet_batch_size == 32

    def test_default_fallback_to_mpnet(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.fallback_to_mpnet is True

    def test_default_fallback_to_bm25(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.fallback_to_bm25 is True

    def test_default_fusion_mode(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.fusion_mode == "max"

    def test_default_model(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.default_model == "siamese"


class TestSiameseConfigFromEnv:
    """Test environment variable loading."""

    @patch.dict(os.environ, {
        "SIAMESE_MODEL_PATH": "/ custom/path",
        "SIAMESE_EMBEDDING_DIM": "256",
        "SIAMESE_THRESHOLD": "0.80",
        "MPNET_THRESHOLD": "0.90",
        "BM25_THRESHOLD": "0.70",
        "SIAMESE_BATCH_SIZE": "8",
        "MPNET_BATCH_SIZE": "16",
        "FALLBACK_TO_MPNET": "false",
        "FALLBACK_TO_BM25": "false",
        "DEFAULT_MAPPING_MODEL": "mpnet",
        "FUSION_MODE": "weighted",
    })
    def test_env_model_path(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.model_path == "/ custom/path"

    @patch.dict(os.environ, {
        "SIAMESE_EMBEDDING_DIM": "256",
    })
    def test_env_embedding_dim(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.embedding_dim == 256

    @patch.dict(os.environ, {
        "SIAMESE_THRESHOLD": "0.80",
    })
    def test_env_siamese_threshold(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.siamese_threshold == 0.80

    @patch.dict(os.environ, {
        "MPNET_THRESHOLD": "0.90",
    })
    def test_env_mpnet_threshold(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.mpnet_threshold == 0.90

    @patch.dict(os.environ, {
        "FALLBACK_TO_MPNET": "false",
    })
    def test_env_fallback_mpnet_disabled(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.fallback_to_mpnet is False

    @patch.dict(os.environ, {
        "FALLBACK_TO_BM25": "false",
    })
    def test_env_fallback_bm25_disabled(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.fallback_to_bm25 is False

    @patch.dict(os.environ, {
        "DEFAULT_MAPPING_MODEL": "mpnet",
    })
    def test_env_default_model(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.default_model == "mpnet"

    @patch.dict(os.environ, {
        "FUSION_MODE": "weighted",
    })
    def test_env_fusion_mode(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig.from_env()
        assert config.fusion_mode == "weighted"


class TestSiameseConfigGetters:
    """Test getter methods."""

    def test_get_threshold_siamese(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(siamese_threshold=0.72)
        assert config.get_threshold("siamese") == 0.72

    def test_get_threshold_mpnet(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(mpnet_threshold=0.88)
        assert config.get_threshold("mpnet") == 0.88

    def test_get_threshold_bm25(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(bm25_threshold=0.65)
        assert config.get_threshold("bm25") == 0.65

    def test_get_threshold_auto_uses_siamese(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(siamese_threshold=0.72)
        assert config.get_threshold("auto") == 0.72

    def test_get_threshold_unknown_defaults_to_siamese(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(siamese_threshold=0.72)
        assert config.get_threshold("unknown") == 0.72

    def test_get_batch_size_siamese(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(siamese_batch_size=8)
        assert config.get_batch_size("siamese") == 8

    def test_get_batch_size_mpnet(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(mpnet_batch_size=16)
        assert config.get_batch_size("mpnet") == 16

    def test_get_batch_size_bm25_defaults_32(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.get_batch_size("bm25") == 32


class TestSiameseConfigValidation:
    """Test configuration validation."""

    def test_invalid_siamese_threshold_too_high(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="SIAMESE_THRESHOLD"):
            SiameseConfig(siamese_threshold=1.5)

    def test_invalid_siamese_threshold_negative(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="SIAMESE_THRESHOLD"):
            SiameseConfig(siamese_threshold=-0.1)

    def test_invalid_mpnet_threshold_too_high(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="MPNET_THRESHOLD"):
            SiameseConfig(mpnet_threshold=1.5)

    def test_invalid_bm25_threshold_negative(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="BM25_THRESHOLD"):
            SiameseConfig(bm25_threshold=-0.1)

    def test_invalid_embedding_dim_zero(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="SIAMESE_EMBEDDING_DIM"):
            SiameseConfig(embedding_dim=0)

    def test_invalid_embedding_dim_negative(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="SIAMESE_EMBEDDING_DIM"):
            SiameseConfig(embedding_dim=-1)

    def test_invalid_siamese_batch_size_zero(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="SIAMESE_BATCH_SIZE"):
            SiameseConfig(siamese_batch_size=0)

    def test_invalid_mpnet_batch_size_negative(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="MPNET_BATCH_SIZE"):
            SiameseConfig(mpnet_batch_size=-1)

    def test_invalid_fusion_mode(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="FUSION_MODE"):
            SiameseConfig(fusion_mode="invalid")

    def test_invalid_fusion_mode_empty(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with pytest.raises(ValueError, match="FUSION_MODE"):
            SiameseConfig(fusion_mode="")


class TestSiameseConfigModelAvailability:
    """Test model availability checking."""

    def test_model_available_when_path_exists(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SiameseConfig(model_path=tmpdir)
            assert config.is_model_available("siamese") is False
            Path(tmpdir, "config.json").touch()
            assert config.is_model_available("siamese") is False
            Path(tmpdir, "model.safetensors").touch()
            assert config.is_model_available("siamese") is False
            Path(tmpdir, "tokenizer.json").touch()
            assert config.is_model_available("siamese") is True

    def test_mpnet_always_available(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.is_model_available("mpnet") is True

    def test_bm25_always_available(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.is_model_available("bm25") is True


class TestSiameseConfigFallback:
    """Test fallback enabled checks."""

    def test_fallback_mpnet_enabled_by_default(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.is_fallback_enabled("mpnet") is True

    def test_fallback_bm25_enabled_by_default(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.is_fallback_enabled("bm25") is True

    def test_fallback_disabled_when_flag_false(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig(fallback_to_mpnet=False)
        assert config.is_fallback_enabled("mpnet") is False

    def test_fallback_returns_false_for_unknown(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        assert config.is_fallback_enabled("unknown") is False


class TestSiameseConfigRepr:
    """Test string representation."""

    def test_repr_contains_key_values(self):
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        config = SiameseConfig()
        repr_str = repr(config)
        assert "SiameseConfig" in repr_str
        assert "model_path" in repr_str
        assert "siamese_threshold" in repr_str
        assert "mpnet_threshold" in repr_str