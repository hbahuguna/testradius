import json
import logging
from typing import List, Dict, Optional
import numpy as np

logger = logging.getLogger(__name__)


class EnsembleFuser:
    """Learn weights for evidence features and compute final_confidence.

    Trains a logistic regression on existing EVIDENCE coverage edges
    as ground truth, then predicts final_confidence for all edges.

    Feature vector per edge:
        heuristic, siamese, mpnet, cross_encoder,
        jaccard, call_graph, community_overlap, llm_verification
    """

    FEATURE_NAMES = [
        "heuristic", "siamese", "mpnet", "cross_encoder",
        "jaccard", "call_graph", "community_overlap", "llm_verification"
    ]

    def __init__(self, model=None):
        self.model = model
        self._trained = model is not None

    def extract_feature_vector(self, features) -> np.ndarray:
        """Convert features dict or JSON string to fixed-length vector."""
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except (json.JSONDecodeError, TypeError):
                features = {}
        vec = []
        for name in self.FEATURE_NAMES:
            vec.append(float(features.get(name, 0.0)))
        return np.array(vec)

    def train(
        self,
        positive_edges: List[Dict],
        negative_edges: List[Dict]
    ):
        """Train logistic regression on positive and negative edges."""
        from sklearn.linear_model import LogisticRegression

        X_pos = np.array([self.extract_feature_vector(e.get("features", {})) for e in positive_edges])
        X_neg = np.array([self.extract_feature_vector(e.get("features", {})) for e in negative_edges])

        y_pos = np.ones(len(X_pos))
        y_neg = np.zeros(len(X_neg))

        X = np.vstack([X_pos, X_neg])
        y = np.concatenate([y_pos, y_neg])

        logger.info(f"Training ensemble on {len(X)} samples ({len(X_pos)} pos, {len(X_neg)} neg)")

        self.model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)
        self.model.fit(X, y)

        self._trained = True

        weights = self.model.coef_[0]
        for name, w in zip(self.FEATURE_NAMES, weights):
            logger.info(f"  Weight {name}: {w:.4f}")
        logger.info(f"  Intercept: {self.model.intercept_[0]:.4f}")

    def predict(self, features) -> float:
        """Predict final_confidence from feature vector."""
        if not self._trained or self.model is None:
            if isinstance(features, dict):
                vals = [v for v in features.values() if isinstance(v, (int, float))]
                return max(vals) if vals else 0.0
            return 0.0

        vec = self.extract_feature_vector(features).reshape(1, -1)
        return float(self.model.predict_proba(vec)[0][1])

    def fuse_edges(self, edges: List[Dict]) -> List[Dict]:
        """Set final_confidence on each edge using trained model."""
        for edge in edges:
            features = edge.get("features", {})
            edge["final_confidence"] = round(self.predict(features), 4)
        return edges

    @property
    def weights(self) -> Dict[str, float]:
        if not self._trained or self.model is None:
            return {name: 0.0 for name in self.FEATURE_NAMES}
        return dict(zip(self.FEATURE_NAMES, self.model.coef_[0]))
