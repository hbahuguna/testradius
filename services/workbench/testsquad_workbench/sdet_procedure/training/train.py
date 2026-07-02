"""Fine-tune Qwen3-8B on SDET conversation data with DeepSpeed ZeRO-3.

Usage:
    torchrun --nproc_per_node=8 train.py \\
        --data_path ./training_data.jsonl \\
        --output_dir ./qwen3-8b-sdet \\
        --deepspeed deepspeed_config.json
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import torch
from datasets import Dataset, load_dataset
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    HfArgumentParser,
    Trainer,
    TrainingArguments,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1.  Conversation formatting
# ---------------------------------------------------------------------------

def format_conversation(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for msg in messages:
        role = msg["role"].capitalize()
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2.  Dataset loading
# ---------------------------------------------------------------------------

def load_training_data(data_path: str, tokenizer, max_length: int = 8192) -> Dataset:
    raw = []
    with open(data_path) as f:
        for line in f:
            raw.append(json.loads(line))

    texts = []
    for item in raw:
        text = format_conversation(item["messages"])
        texts.append(text)

    dataset = Dataset.from_dict({"text": texts})

    def tokenize_fn(examples):
        result = tokenizer(
            examples["text"],
            truncation=True,
            max_length=max_length,
            padding=False,
            return_tensors=None,
        )
        result["labels"] = result["input_ids"].copy()
        return result

    dataset = dataset.map(
        tokenize_fn,
        batched=True,
        remove_columns=["text"],
        num_proc=4,
    )
    return dataset


# ---------------------------------------------------------------------------
# 3.  Argument parsing
# ---------------------------------------------------------------------------

@dataclass
class ModelArguments:
    model_name_or_path: str = field(
        default="Qwen/Qwen3-8B",
        metadata={"help": "Pretrained model name or path"},
    )
    tokenizer_name: Optional[str] = field(
        default=None,
        metadata={"help": "Tokenizer name, defaults to model_name_or_path"},
    )


@dataclass
class DataArguments:
    data_path: str = field(
        default="./training_data.jsonl",
        metadata={"help": "Path to training data (JSONL)"},
    )
    max_length: int = field(
        default=8192,
        metadata={"help": "Max sequence length for tokenization"},
    )


@dataclass
class CustomTrainingArguments(TrainingArguments):
    output_dir: str = field(
        default="./qwen3-8b-sdet",
        metadata={"help": "Output directory for model checkpoints"},
    )
    num_train_epochs: int = field(
        default=10,
        metadata={"help": "Number of training epochs"},
    )
    per_device_train_batch_size: int = field(
        default=1,
        metadata={"help": "Batch size per GPU"},
    )
    gradient_accumulation_steps: int = field(
        default=4,
        metadata={"help": "Gradient accumulation steps"},
    )
    learning_rate: float = field(
        default=2e-5,
        metadata={"help": "Peak learning rate"},
    )
    warmup_steps: int = field(
        default=200,
        metadata={"help": "Warmup steps"},
    )
    logging_steps: int = field(
        default=10,
        metadata={"help": "Log every N steps"},
    )
    save_steps: int = field(
        default=500,
        metadata={"help": "Save checkpoint every N steps"},
    )
    save_total_limit: int = field(
        default=3,
        metadata={"help": "Keep only N most recent checkpoints"},
    )
    evaluation_strategy: str = field(
        default="no",
        metadata={"help": "Evaluation strategy"},
    )
    load_best_model_at_end: bool = field(
        default=False,
        metadata={"help": "Load best model at end"},
    )
    deepspeed: Optional[str] = field(
        default=None,
        metadata={"help": "Path to DeepSpeed config"},
    )
    report_to: str = field(
        default="wandb",
        metadata={"help": "Reporting integration"},
    )
    remove_unused_columns: bool = field(
        default=False,
    )


# ---------------------------------------------------------------------------
# 4.  Main
# ---------------------------------------------------------------------------

def main():
    parser = HfArgumentParser(
        (ModelArguments, DataArguments, CustomTrainingArguments)
    )
    model_args, data_args, training_args = parser.parse_args_into_dataclasses()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )

    logger.info("Loading tokenizer")
    tokenizer_name = model_args.tokenizer_name or model_args.model_name_or_path
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_name,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    logger.info(f"Loading training data from {data_args.data_path}")
    dataset = load_training_data(data_args.data_path, tokenizer, data_args.max_length)
    logger.info(f"Loaded {len(dataset)} examples")

    logger.info(f"Loading model: {model_args.model_name_or_path}")
    model = AutoModelForCausalLM.from_pretrained(
        model_args.model_name_or_path,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        use_cache=False,
    )
    model.config.use_cache = False

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    logger.info("Initializing trainer")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=data_collator,
        tokenizer=tokenizer,
    )

    logger.info("Starting training")
    train_result = trainer.train()
    logger.info(f"Training complete. Metrics: {train_result.metrics}")

    trainer.save_model(training_args.output_dir)
    tokenizer.save_pretrained(training_args.output_dir)
    logger.info(f"Model saved to {training_args.output_dir}")


if __name__ == "__main__":
    main()
