"""Data generation pipeline for compiling SDET workflows into model weights.

Usage:
    python -m testsquad_workbench.sdet_procedure.pipeline \\
        --n-paths 10 --n-per-path 5 --output ./training_data.jsonl

This generates synthetic conversations by:
1. Enumerating all valid paths through the 16-node SDET procedure graph
2. Sampling scenario variables for each path
3. Generating turn-by-turn conversation via Claude API
4. Outputting training-ready JSONL for fine-tuning
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from testsquad_workbench.sdet_procedure.graph import (
    ProcedureGraph,
    Path,
    build_sdet_graph,
    enumerate_paths,
)
from testsquad_workbench.sdet_procedure.scenario import (
    ScenarioVariables,
    ScenarioSampler,
    FeatureType,
)
from testsquad_workbench.sdet_procedure.templates import (
    NODE_TEMPLATES,
    get_filled_template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1.  Mock LLM client  (swap with real Claude API calls in production)
# ---------------------------------------------------------------------------

class LLMClient:
    """Mock LLM client for local testing.  Replace with real API client."""

    def generate(self, system: str, instruction: str) -> str:
        """Pretend to generate a turn (used during dev, not training data gen)."""
        return (
            f"[Simulated {instruction[:60]}...]"
        )


class AnthropicClient(LLMClient):
    """Real Claude Sonnet 4.5 client for production data generation."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def generate(self, system: str, instruction: str) -> str:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": instruction}],
        )
        return msg.content[0].text


# ---------------------------------------------------------------------------
# 2.  Conversation generator
# ---------------------------------------------------------------------------

@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str
    node_id: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class GeneratedConversation:
    turns: List[ConversationTurn]
    path: Path
    scenario: ScenarioVariables
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_messages(self) -> List[Dict[str, str]]:
        return [t.to_dict() for t in self.turns]

    def to_training_format(self) -> Dict[str, Any]:
        return {
            "messages": self.to_messages(),
            "metadata": {
                "path_nodes": self.path.node_ids,
                "hub_decisions": self.path.hub_decisions,
                "scenario": self.scenario.to_dict(),
                **self.metadata,
            },
        }


def generate_conversation(
    graph: ProcedureGraph,
    path: Path,
    scenario: ScenarioVariables,
    llm: LLMClient,
) -> GeneratedConversation:
    node_ids = path.node_ids
    hub_decisions = path.hub_decisions

    scenario_vars = scenario.template_vars()
    turns: List[ConversationTurn] = []
    conversation_history = ""

    for i, nid in enumerate(node_ids):
        if nid in ("T_SUCCESS", "T_ABANDON", "T_ESCALATE"):
            continue

        node = graph.get_node(nid)
        if node is None:
            continue

        node_context: Dict[str, Any] = {}

        if node.is_decision_hub and nid in hub_decisions:
            node_context["chosen_branch"] = hub_decisions[nid]
            node_context["clarify_decision_text"] = (
                f"I need more details to proceed. "
                f"[Branch: {hub_decisions[nid]}]"
            )
            if hub_decisions[nid] != "needs_clarification":
                node_context["clarify_decision_text"] = (
                    f"I have enough information to proceed. "
                    f"[Branch: {hub_decisions[nid]}]"
                )
            node_context["review_prompt"] = (
                "Here is the generated test above. "
                f"Do you accept, request revisions, or abandon? "
                f"[Branch: {hub_decisions[nid]}]"
            )
            if hub_decisions[nid] == "accept":
                turns.append(ConversationTurn(
                    role="assistant",
                    content="The test generation is complete. Do you accept this test, need revisions, or would you like to abandon?",
                    node_id=nid,
                ))
                continue
            elif hub_decisions[nid] == "abandon_request":
                continue

        if nid == "N0":
            template = get_filled_template(
                "open", node_context, scenario_vars, conversation_history
            )
            response = llm.generate(
                NODE_TEMPLATES["open"]["system"], template
            )
            role = "assistant"
        elif nid == "N1":
            template = get_filled_template(
                "user_request", node_context, scenario_vars, conversation_history
            )
            response = llm.generate(
                NODE_TEMPLATES["user_request"]["system"].format(**scenario_vars),
                template,
            )
            role = "user"
        elif nid == "N4":
            template = get_filled_template(
                "clarify_details", node_context, scenario_vars, conversation_history
            )
            response = llm.generate(
                NODE_TEMPLATES["clarify_details"]["system"].format(**scenario_vars),
                template,
            )
            role = "user"
        else:
            template_id = node.prompt_template_id
            template = get_filled_template(
                template_id, node_context, scenario_vars, conversation_history
            )
            sys_template = NODE_TEMPLATES.get(template_id, {}).get("system", "")
            response = llm.generate(sys_template, template)
            role = "assistant"

        turns.append(ConversationTurn(role=role, content=response, node_id=nid))

        turn_text = f"\n{role.upper()}: {response}"
        conversation_history += turn_text

    return GeneratedConversation(
        turns=turns,
        path=path,
        scenario=scenario,
    )


# ---------------------------------------------------------------------------
# 3.  Full pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    llm: LLMClient,
    n_paths: int = 60,
    n_per_path: int = 20,
    output_path: str = "./training_data.jsonl",
    seed: int = 42,
    domains: Optional[List[str]] = None,
) -> List[GeneratedConversation]:
    graph = build_sdet_graph()
    all_paths = enumerate_paths(graph)
    logger.info(f"Enumerated {len(all_paths)} unique structural paths")

    selected_paths = random.Random(seed).sample(
        all_paths, min(n_paths, len(all_paths))
    )
    sampler = ScenarioSampler(seed=seed)

    conversations: List[GeneratedConversation] = []
    total = len(selected_paths) * n_per_path

    for pi, path in enumerate(selected_paths):
        logger.info(
            f"Path {pi + 1}/{len(selected_paths)}: "
            f"{path.turn_count} turns, hubs={path.hub_decisions}"
        )

        for si in range(n_per_path):
            scenario = sampler.sample()
            conv = generate_conversation(graph, path, scenario, llm)
            conversations.append(conv)

            if (pi * n_per_path + si + 1) % 20 == 0:
                logger.info(f"  Generated {pi * n_per_path + si + 1}/{total}")

    with open(output_path, "w") as f:
        for conv in conversations:
            f.write(json.dumps(conv.to_training_format()) + "\n")

    logger.info(f"Wrote {len(conversations)} conversations to {output_path}")
    return conversations


# ---------------------------------------------------------------------------
# 4.  CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic SDET conversation data for fine-tuning"
    )
    parser.add_argument(
        "--n-paths", type=int, default=60,
        help="Number of structural paths to sample (default: 60)"
    )
    parser.add_argument(
        "--n-per-path", type=int, default=20,
        help="Scenarios per path (default: 20)"
    )
    parser.add_argument(
        "--output", type=str, default="./training_data.jsonl",
        help="Output JSONL file path"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed"
    )
    parser.add_argument(
        "--mock", action="store_true", default=True,
        help="Use mock LLM (no API key needed)"
    )
    parser.add_argument(
        "--real", action="store_true",
        help="Use real Claude API (requires ANTHROPIC_API_KEY)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.real:
        llm = AnthropicClient()
    else:
        llm = LLMClient()

    total = args.n_paths * args.n_per_path
    logger.info(
        f"Starting pipeline: {args.n_paths} paths × {args.n_per_path} scenarios "
        f"= {total} conversations | seed={args.seed} | real_api={args.real}"
    )

    start = time.time()
    run_pipeline(
        llm=llm,
        n_paths=args.n_paths,
        n_per_path=args.n_per_path,
        output_path=args.output,
        seed=args.seed,
    )
    elapsed = time.time() - start
    logger.info(f"Pipeline complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
