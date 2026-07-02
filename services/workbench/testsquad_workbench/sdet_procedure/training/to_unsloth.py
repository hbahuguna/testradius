"""Convert bigpickle dataset to Unsloth-compatible ShareGPT format.

Usage:
    python to_unsloth.py --input training_data_bigpickle.jsonl --output training_unsloth.jsonl

Output format (ShareGPT):
    {"conversations": [{"from": "human", "value": "..."}, {"from": "gpt", "value": "..."}]}
"""
from __future__ import annotations

import argparse
import json
import logging

logger = logging.getLogger(__name__)

_ROLE_MAP = {"user": "human", "assistant": "gpt"}


def convert_line(line: str) -> str:
    data = json.loads(line)
    messages = data["messages"]
    conversations = []
    for m in messages:
        role = _ROLE_MAP.get(m["role"])
        if role is None:
            continue
        conversations.append({"from": role, "value": m["content"]})
    return json.dumps({"conversations": conversations, "metadata": data.get("metadata", {})})


def convert(input_path: str, output_path: str) -> None:
    count = 0
    with open(input_path) as fin, open(output_path, "w") as fout:
        for line in fin:
            fout.write(convert_line(line) + "\n")
            count += 1
    logger.info(f"Converted {count} conversations to {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="training_data_bigpickle.jsonl")
    parser.add_argument("--output", default="training_unsloth.jsonl")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    convert(args.input, args.output)


if __name__ == "__main__":
    main()
