import logging
import os
from typing import List, Dict, Optional
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

logger = logging.getLogger(__name__)


class CrossEncoderScorer:
    """Score method-test pairs using a fine-tuned CodeBERT cross-encoder.

    Takes (method_code, test_code) as input, outputs similarity score (0-1).
    Reranks HeuristicMapper candidates by keeping top-K per method.
    """

    def __init__(
        self,
        model_path: str = "models/cross_encoder/",
        max_length: int = 512,
        batch_size: int = 16,
        device: str = None
    ):
        self.model_path = model_path
        self.max_length = max_length
        self.batch_size = batch_size
        if device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
            elif torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        else:
            self.device = device

        self.tokenizer = None
        self.model = None

    def _load(self):
        if self.model is not None:
            return True
        try:
            if self.device == "mps":
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
            logger.info(f"Loading cross-encoder from {self.model_path}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
            self.model.to(self.device)
            self.model.eval()
            logger.info(f"Cross-encoder loaded (device: {self.device})")
            return True
        except Exception as e:
            logger.warning(f"Failed to load cross-encoder: {e}")
            return False

    def score_pairs(
        self,
        candidates: List[Dict]
    ) -> List[Dict]:
        """Score a list of candidate pairs in batches.

        Each candidate dict must have:
            - symbol_name, symbol_file
            - test_name, test_file
            - symbol_code: str (method source code or signature)
            - test_code: str (test source code or signature)

        Returns the same list with 'cross_encoder_score' added.
        """
        if not candidates:
            return []

        if not self._load():
            logger.warning("Cross-encoder not available, returning candidates unscored")
            for c in candidates:
                c["cross_encoder_score"] = 0.0
            return candidates

        texts_a = [c.get("symbol_code") or c.get("summary") or c.get("symbol_name", "") for c in candidates]
        texts_b = [c.get("test_code") or c.get("summary") or c.get("test_name", "") for c in candidates]

        scores = []
        for i in range(0, len(candidates), self.batch_size):
            batch_a = texts_a[i:i + self.batch_size]
            batch_b = texts_b[i:i + self.batch_size]

            encoded = self.tokenizer(
                batch_a, batch_b,
                truncation=True,
                padding=True,
                max_length=self.max_length,
                return_tensors="pt"
            )
            encoded = {k: v.to(self.device) for k, v in encoded.items()}

            with torch.no_grad():
                outputs = self.model(**encoded)
                logits = outputs.logits.squeeze(-1)
                batch_scores = torch.sigmoid(logits).cpu().numpy().tolist()
                if isinstance(batch_scores, float):
                    batch_scores = [batch_scores]
                scores.extend(batch_scores)

        for c, s in zip(candidates, scores):
            c["cross_encoder_score"] = round(s, 4)

        return candidates

    def rerank(
        self,
        candidates: List[Dict],
        top_k: int = 20
    ) -> List[Dict]:
        """Score and rerank candidates, keeping top-K per symbol."""
        scored = self.score_pairs(candidates)

        symbol_groups = {}
        for c in scored:
            key = (c["symbol_name"], c["symbol_file"])
            if key not in symbol_groups:
                symbol_groups[key] = []
            symbol_groups[key].append(c)

        reranked = []
        for key, group in symbol_groups.items():
            group.sort(key=lambda x: x.get("cross_encoder_score", 0), reverse=True)
            reranked.extend(group[:top_k])

        return reranked

    def update_features(self, candidates: List[Dict]) -> List[Dict]:
        """Add cross_encoder score to the EVIDENCE features dict."""
        for c in candidates:
            if "features" not in c:
                c["features"] = {}
            c["features"]["cross_encoder"] = c.get("cross_encoder_score", 0.0)
            c["final_confidence"] = None
            c["reasoning"] = (
                f"Cross-encoder: {c['cross_encoder_score']:.2f}, "
                f"Heuristic: {c['features'].get('heuristic', 0):.2f}"
            )
        return candidates
