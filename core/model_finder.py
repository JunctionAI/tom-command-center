#!/usr/bin/env python3
"""
Model Finder — Auto-selects best AI model for the task.
Maintains registry of models from OpenAI, Anthropic, Open Source providers.
Scores by: performance, cost, speed, quality.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Model registry (updated monthly, cached locally)
MODEL_REGISTRY = {
    "reasoning": [
        {
            "name": "claude-opus-4-6",
            "provider": "anthropic",
            "cost_per_1m_input": 15,
            "cost_per_1m_output": 45,
            "speed": "slow",
            "quality": "best",
            "use_cases": ["complex reasoning", "long-form analysis", "strategic decisions"],
        },
        {
            "name": "gpt-4-turbo",
            "provider": "openai",
            "cost_per_1m_input": 10,
            "cost_per_1m_output": 30,
            "speed": "medium",
            "quality": "excellent",
            "use_cases": ["reasoning", "code generation", "analysis"],
        },
    ],
    "speed": [
        {
            "name": "claude-haiku-4-5",
            "provider": "anthropic",
            "cost_per_1m_input": 0.80,
            "cost_per_1m_output": 4,
            "speed": "fastest",
            "quality": "good",
            "use_cases": ["classification", "extraction", "quick decisions", "summarization"],
        },
        {
            "name": "gpt-4-mini",
            "provider": "openai",
            "cost_per_1m_input": 0.15,
            "cost_per_1m_output": 0.60,
            "speed": "very_fast",
            "quality": "good",
            "use_cases": ["simple tasks", "extraction", "classification"],
        },
    ],
    "balance": [
        {
            "name": "claude-sonnet-4-6",
            "provider": "anthropic",
            "cost_per_1m_input": 3,
            "cost_per_1m_output": 15,
            "speed": "fast",
            "quality": "excellent",
            "use_cases": ["general purpose", "marketing", "content", "analysis"],
        },
        {
            "name": "gpt-4o",
            "provider": "openai",
            "cost_per_1m_input": 2.50,
            "cost_per_1m_output": 10,
            "speed": "fast",
            "quality": "excellent",
            "use_cases": ["general purpose", "multimodal", "fast reasoning"],
        },
    ],
    "open_source": [
        {
            "name": "llama-2-70b",
            "provider": "meta",
            "cost_per_1m_input": 0.70,
            "cost_per_1m_output": 0.70,
            "speed": "medium",
            "quality": "good",
            "use_cases": ["open source preference", "cost sensitive", "privacy critical"],
        },
        {
            "name": "mistral-large",
            "provider": "mistral",
            "cost_per_1m_input": 0.27,
            "cost_per_1m_output": 0.81,
            "speed": "fast",
            "quality": "good",
            "use_cases": ["cost sensitive", "fast inference", "open source"],
        },
    ],
}


class ModelFinder:
    """Find and recommend best model for a task."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.registry_path = base_dir / "data" / "model_registry.json"
        self.cache_age = timedelta(days=30)  # Update monthly
        self.load_registry()

    def load_registry(self):
        """Load model registry from cache or use default."""
        if self.registry_path.exists():
            age = datetime.now() - datetime.fromtimestamp(self.registry_path.stat().st_mtime)
            if age < self.cache_age:
                with open(self.registry_path) as f:
                    return json.load(f)

        # Use bundled registry
        logger.info("Using bundled model registry (cache expired or missing)")
        return MODEL_REGISTRY

    def find_model(
        self,
        task: str,
        priority: str = "balance",
        budget: Optional[float] = None,
    ) -> Dict:
        """
        Find best model for task.

        Args:
            task: Task description or type (e.g., "summarization", "code_generation")
            priority: "speed" | "quality" | "balance" | "cost" (default: balance)
            budget: Max cost per 1M input tokens (optional)

        Returns:
            Dict with model recommendation and scoring
        """
        registry = self.load_registry()

        # Get candidates based on priority
        if priority == "speed":
            candidates = registry.get("speed", [])
        elif priority == "quality":
            candidates = registry.get("reasoning", [])
        elif priority == "cost":
            candidates = registry.get("open_source", [])
        else:  # balance
            candidates = registry.get("balance", [])

        # Filter by budget if specified
        if budget:
            candidates = [m for m in candidates if m["cost_per_1m_input"] <= budget]

        if not candidates:
            logger.warning(f"No models found for priority={priority}, budget={budget}")
            return {"error": "No suitable models found", "recommendation": None}

        # Score models
        scored = self._score_models(candidates, task, priority)
        best = sorted(scored, key=lambda x: x["score"], reverse=True)[0]

        return {
            "recommended": best["name"],
            "provider": best["provider"],
            "reasoning": best["score_breakdown"],
            "cost_estimate": {
                "per_1m_input": best["cost_per_1m_input"],
                "per_1m_output": best["cost_per_1m_output"],
                "estimated_cost_100k_tokens": (best["cost_per_1m_input"] * 0.1) + (best["cost_per_1m_output"] * 0.1),
            },
            "speed": best["speed"],
            "quality": best["quality"],
            "alternatives": [m["name"] for m in scored[1:3]],  # Top 2 alternatives
        }

    def _score_models(self, candidates: List[Dict], task: str, priority: str) -> List[Dict]:
        """Score models based on task fit and priority."""
        for model in candidates:
            score = 0
            breakdown = {}

            # Task relevance
            if any(uc in task.lower() for uc in model.get("use_cases", [])):
                score += 30
                breakdown["task_match"] = "+30 (task match)"
            else:
                score += 10
                breakdown["task_match"] = "+10 (general purpose)"

            # Priority weights
            if priority == "speed":
                speed_weight = {"fastest": 30, "very_fast": 25, "fast": 20, "medium": 10, "slow": 0}
                score += speed_weight.get(model["speed"], 0)
                breakdown["speed_bonus"] = f"+{speed_weight.get(model['speed'], 0)}"
            elif priority == "quality":
                quality_weight = {"best": 30, "excellent": 25, "good": 15}
                score += quality_weight.get(model["quality"], 0)
                breakdown["quality_bonus"] = f"+{quality_weight.get(model['quality'], 0)}"
            elif priority == "cost":
                cost_score = max(0, 30 - (model["cost_per_1m_input"] * 2))
                score += cost_score
                breakdown["cost_bonus"] = f"+{int(cost_score)}"
            else:  # balance
                score += 15  # Neutral baseline
                breakdown["balance_baseline"] = "+15"

            model["score"] = score
            model["score_breakdown"] = breakdown

        return candidates


def recommend_model(
    task: str,
    priority: str = "balance",
    budget: Optional[float] = None,
) -> Dict:
    """
    Standalone function to get model recommendation.
    Usage: recommend_model("summarization", priority="speed")
    """
    base_dir = Path(__file__).resolve().parent.parent
    finder = ModelFinder(base_dir)
    return finder.find_model(task, priority, budget)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    base_dir = Path(__file__).resolve().parent.parent
    finder = ModelFinder(base_dir)

    # Example recommendations
    print("\n=== SUMMARIZATION (balance) ===")
    rec = finder.find_model("summarization", priority="balance")
    print(json.dumps(rec, indent=2))

    print("\n=== CODE GENERATION (quality) ===")
    rec = finder.find_model("code generation", priority="quality")
    print(json.dumps(rec, indent=2))

    print("\n=== QUICK CLASSIFICATION (speed, budget=1) ===")
    rec = finder.find_model("classification", priority="speed", budget=1)
    print(json.dumps(rec, indent=2))
