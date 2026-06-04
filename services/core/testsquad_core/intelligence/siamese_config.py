import os
import logging
from pathlib import Path
from typing import Optional, Literal

logger = logging.getLogger(__name__)

ModelType = Literal["siamese", "mpnet", "bm25", "auto"]
DefaultModel = "siamese"


class SiameseConfig:
    """Configuration for SiameseMapper service.
    
    Manages settings for:
    - Model paths and types
    - Thresholds per model
    - Fallback behavior
    - Batch processing
    """
    
    # Environment variable defaults
    DEFAULT_MODEL_PATH = "/app/method2test/"
    DEFAULT_EMBEDDING_DIM = 384
    DEFAULT_SIAMESE_THRESHOLD = 0.5
    DEFAULT_MPNET_THRESHOLD = 0.5
    DEFAULT_BM25_THRESHOLD = 0.60
    DEFAULT_HEURISTIC_THRESHOLD = 0.5
    DEFAULT_SIAMESE_BATCH_SIZE = 16
    DEFAULT_MPNET_BATCH_SIZE = 32
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        siamese_threshold: Optional[float] = None,
        mpnet_threshold: Optional[float] = None,
        bm25_threshold: Optional[float] = None,
        siamese_batch_size: Optional[int] = None,
        mpnet_batch_size: Optional[int] = None,
        fallback_to_mpnet: Optional[bool] = None,
        fallback_to_bm25: Optional[bool] = None,
        default_model: Optional[ModelType] = None,
        fusion_mode: Optional[Literal["max", "weighted", "rrf"]] = None,
        heuristic_threshold: Optional[float] = None,
    ):
        self._model_path = model_path or os.getenv("SIAMESE_MODEL_PATH", self.DEFAULT_MODEL_PATH)
        self._embedding_dim = embedding_dim or int(os.getenv("SIAMESE_EMBEDDING_DIM", str(self.DEFAULT_EMBEDDING_DIM)))
        self._siamese_threshold = siamese_threshold or float(os.getenv("SIAMESE_THRESHOLD", str(self.DEFAULT_SIAMESE_THRESHOLD)))
        self._mpnet_threshold = mpnet_threshold or float(os.getenv("MPNET_THRESHOLD", str(self.DEFAULT_MPNET_THRESHOLD)))
        self._bm25_threshold = bm25_threshold or float(os.getenv("BM25_THRESHOLD", str(self.DEFAULT_BM25_THRESHOLD)))
        self._heuristic_threshold = heuristic_threshold or float(os.getenv("HEURISTIC_THRESHOLD", str(self.DEFAULT_HEURISTIC_THRESHOLD)))
        self._siamese_batch_size = siamese_batch_size or int(os.getenv("SIAMESE_BATCH_SIZE", str(self.DEFAULT_SIAMESE_BATCH_SIZE)))
        self._mpnet_batch_size = mpnet_batch_size or int(os.getenv("MPNET_BATCH_SIZE", str(self.DEFAULT_MPNET_BATCH_SIZE)))
        self._fallback_to_mpnet = fallback_to_mpnet if fallback_to_mpnet is not None else os.getenv("FALLBACK_TO_MPNET", "true").lower() == "true"
        self._fallback_to_bm25 = fallback_to_bm25 if fallback_to_bm25 is not None else os.getenv("FALLBACK_TO_BM25", "true").lower() == "true"
        self._default_model = default_model or os.getenv("DEFAULT_MAPPING_MODEL", DefaultModel)
        self._fusion_mode = fusion_mode or os.getenv("FUSION_MODE", "max")
        
        self._validate()
    
    @classmethod
    def from_env(cls) -> "SiameseConfig":
        """Create config from environment variables."""
        return cls()
    
    def _validate(self) -> None:
        """Validate configuration values."""
        errors = []
        
        # Validate threshold values
        if not 0.0 <= self._siamese_threshold <= 1.0:
            errors.append(f"SIAMESE_THRESHOLD must be between 0.0 and 1.0, got {self._siamese_threshold}")
        
        if not 0.0 <= self._mpnet_threshold <= 1.0:
            errors.append(f"MPNET_THRESHOLD must be between 0.0 and 1.0, got {self._mpnet_threshold}")
        
        if not 0.0 <= self._bm25_threshold <= 1.0:
            errors.append(f"BM25_THRESHOLD must be between 0.0 and 1.0, got {self._bm25_threshold}")
        
        # Validate embedding dimension
        if self._embedding_dim <= 0:
            errors.append(f"SIAMESE_EMBEDDING_DIM must be positive, got {self._embedding_dim}")
        
        # Validate batch sizes
        if self._siamese_batch_size <= 0:
            errors.append(f"SIAMESE_BATCH_SIZE must be positive, got {self._siamese_batch_size}")
        
        if self._mpnet_batch_size <= 0:
            errors.append(f"MPNET_BATCH_SIZE must be positive, got {self._mpnet_batch_size}")
        
        # Validate model path exists
        if self._model_path and not Path(self._model_path).exists():
            logger.warning(f"Model path does not exist: {self._model_path}")
        
        # Validate fusion mode
        if self._fusion_mode not in ["max", "weighted", "rrf"]:
            errors.append(f"FUSION_MODE must be one of: max, weighted, rrf, got {self._fusion_mode}")
        
        if errors:
            raise ValueError("SiameseConfig validation failed:\n" + "\n".join(errors))
    
    @property
    def model_path(self) -> str:
        return self._model_path
    
    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim
    
    @property
    def siamese_threshold(self) -> float:
        return self._siamese_threshold
    
    @property
    def mpnet_threshold(self) -> float:
        return self._mpnet_threshold
    
    @property
    def bm25_threshold(self) -> float:
        return self._bm25_threshold
    
    @property
    def heuristic_threshold(self) -> float:
        return self._heuristic_threshold
    
    @property
    def siamese_batch_size(self) -> int:
        return self._siamese_batch_size
    
    @property
    def mpnet_batch_size(self) -> int:
        return self._mpnet_batch_size
    
    @property
    def fallback_to_mpnet(self) -> bool:
        return self._fallback_to_mpnet
    
    @property
    def fallback_to_bm25(self) -> bool:
        return self._fallback_to_bm25
    
    @property
    def default_model(self) -> ModelType:
        return self._default_model
    
    @property
    def fusion_mode(self) -> str:
        return self._fusion_mode
    
    def get_threshold(self, model: ModelType) -> float:
        """Get threshold for specific model."""
        thresholds = {
            "siamese": self._siamese_threshold,
            "mpnet": self._mpnet_threshold,
            "bm25": self._bm25_threshold,
            "auto": self._siamese_threshold,
        }
        return thresholds.get(model, self._siamese_threshold)
    
    def get_batch_size(self, model: ModelType) -> int:
        """Get batch size for specific model."""
        batch_sizes = {
            "siamese": self._siamese_batch_size,
            "mpnet": self._mpnet_batch_size,
            "bm25": 32,
            "auto": self._siamese_batch_size,
        }
        return batch_sizes.get(model, self._siamese_batch_size)
    
    def is_model_available(self, model: ModelType) -> bool:
        """Check if model path exists and is valid."""
        if model == "siamese":
            path = Path(self._model_path)
            if not path.exists():
                return False
            required_files = ["config.json", "model.safetensors", "tokenizer.json"]
            return all((path / f).exists() for f in required_files)
        return True
    
    def is_fallback_enabled(self, model: ModelType) -> bool:
        """Check if fallback is enabled for model."""
        if model == "mpnet":
            return self._fallback_to_mpnet
        if model == "bm25":
            return self._fallback_to_bm25
        return False
    
    def __repr__(self) -> str:
        return (
            f"SiameseConfig("
            f"model_path={self._model_path}, "
            f"embedding_dim={self._embedding_dim}, "
            f"siamese_threshold={self._siamese_threshold}, "
            f"mpnet_threshold={self._mpnet_threshold}, "
            f"default_model={self._default_model}, "
            f"fusion_mode={self._fusion_mode})"
        )