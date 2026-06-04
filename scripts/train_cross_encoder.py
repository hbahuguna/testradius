#!/usr/bin/env python3
"""Train a CodeBERT cross-encoder for method-test pair scoring.

Usage:
    source venv/bin/activate
    python scripts/train_cross_encoder.py --project-id 888 \\
        --pos-limit 25000 --neg-limit 10000 --epochs 3 \\
        --output models/cross_encoder/
"""
import argparse
import logging
import os
import sys

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer, AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup
)
from torch.optim import AdamW

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'core'))
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.training_data import TrainingDataExporter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeTestPairDataset(Dataset):
    """Dataset of (method_code, test_code, label) triples."""

    def __init__(
        self,
        pairs: list,
        tokenizer,
        max_length: int = 512,
        label_key: str = "label"
    ):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.examples = []

        for pair in pairs:
            method_code = pair.get("symbol_code") or pair.get("symbol_name", "")
            test_code = pair.get("test_code") or pair.get("test_name", "")
            label = pair.get(label_key, 0)

            encoding = tokenizer(
                str(method_code),
                str(test_code),
                truncation=True,
                padding="max_length",
                max_length=max_length,
                return_tensors=None
            )
            self.examples.append({
                "input_ids": encoding["input_ids"],
                "attention_mask": encoding["attention_mask"],
                "labels": float(label)
            })

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        item = self.examples[idx]
        return {
            "input_ids": torch.tensor(item["input_ids"], dtype=torch.long),
            "attention_mask": torch.tensor(item["attention_mask"], dtype=torch.long),
            "labels": torch.tensor(item["labels"], dtype=torch.float),
        }


def train(args):
    logger.info(f"Loading tokenizer: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    logger.info(f"Loading model: {args.model_name}")
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=1
    )

    logger.info("Exporting training pairs from Neo4j...")
    client = Neo4jClient(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password
    )
    exporter = TrainingDataExporter(client)
    pos_pairs, neg_pairs = exporter.export_all(
        args.project_id,
        pos_limit=args.pos_limit,
        neg_limit=args.neg_limit,
        hard_neg_limit=args.hard_neg_limit
    )

    for p in pos_pairs:
        p["label"] = 1.0
    for n in neg_pairs:
        n["label"] = 0.0

    all_pairs = pos_pairs + neg_pairs
    np.random.shuffle(all_pairs)
    logger.info(f"Total pairs: {len(all_pairs)} ({len(pos_pairs)} pos, {len(neg_pairs)} neg)")

    split = int(len(all_pairs) * 0.9)
    train_pairs = all_pairs[:split]
    val_pairs = all_pairs[split:]

    train_dataset = CodeTestPairDataset(train_pairs, tokenizer, args.max_length)
    val_dataset = CodeTestPairDataset(val_pairs, tokenizer, args.max_length)

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size)

    optimizer = AdamW(model.parameters(), lr=args.learning_rate)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * 0.1),
        num_training_steps=total_steps
    )

    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
    logger.info(f"Using device: {device}")
    model.to(device)

    os.makedirs(args.output_dir, exist_ok=True)

    best_val_loss = float("inf")
    for epoch in range(args.epochs):
        logger.info(f"Epoch {epoch + 1}/{args.epochs}")
        model.train()
        total_loss = 0

        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                labels=batch["labels"].unsqueeze(1)
            )
            loss = outputs.loss
            total_loss += loss.item()

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

        avg_train_loss = total_loss / len(train_loader)
        logger.info(f"Train loss: {avg_train_loss:.4f}")

        model.eval()
        val_loss = 0
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                    labels=batch["labels"].unsqueeze(1)
                )
                val_loss += outputs.loss.item()

        avg_val_loss = val_loss / len(val_loader)
        logger.info(f"Val loss: {avg_val_loss:.4f}")

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            model.save_pretrained(args.output_dir)
            tokenizer.save_pretrained(args.output_dir)
            logger.info(f"Saved model to {args.output_dir}")

    client.close()
    logger.info("Training complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=888)
    parser.add_argument("--model-name", default="microsoft/codebert-base")
    parser.add_argument("--output-dir", default="models/cross_encoder")
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--pos-limit", type=int, default=25000)
    parser.add_argument("--neg-limit", type=int, default=10000)
    parser.add_argument("--hard-neg-limit", type=int, default=5000)
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="testsquad_password")
    args = parser.parse_args()
    train(args)
