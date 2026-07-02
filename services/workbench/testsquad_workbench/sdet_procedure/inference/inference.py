from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from testsquad_workbench.sdet_procedure.inference.page_scraper import (
    PageSnapshot,
    InteractiveElement,
)
from testsquad_workbench.sdet_procedure.inference.repo_scanner import (
    RepoContext,
)

_DEFAULT_SYSTEM_PROMPT = """You are an expert Senior SDET specializing in Playwright UI automation.
You follow a structured workflow to generate reliable tests.
Given the page context and a test scenario, produce a complete test.
Be concise. Include locator strategy, action sequence, assertions, and test code."""  # noqa: E501


@dataclass
class InferenceConfig:
    model_path: str
    base_model_name: str = "Qwen/Qwen3-8B"
    max_seq_length: int = 8192
    max_new_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    load_in_4bit: bool = True
    use_lora: bool = False
    device: str = "auto"


def _fmt_elements(elements: List[InteractiveElement]) -> str:
    lines = []
    for el in elements:
        parts = [f"<{el.tag.lower()}>"]
        if el.label:
            parts.append(f'label="{el.label}"')
        if el.role:
            parts.append(f"role={el.role}")
        if el.type and el.type != "text":
            parts.append(f"type={el.type}")
        if el.id:
            parts.append(f"id=#{el.id}")
        if el.name:
            parts.append(f"name={el.name}")
        if el.href:
            href = el.href[:60]
            parts.append(f"href={href}")
        lines.append("  " + " ".join(parts))
    return "\n".join(lines)


def format_page_context(snapshot: PageSnapshot) -> str:
    elements_text = _fmt_elements(snapshot.elements)
    a11y_text = json.dumps(snapshot.a11y_tree, indent=2)[:2000] if snapshot.a11y_tree else "N/A"

    return f"""=== Page Context ===
URL: {snapshot.url}
Title: {snapshot.title}

=== Interactive Elements ===
{elements_text}

=== Accessibility Tree ===
{a11y_text}
"""


class SDETInference:
    def __init__(self, config: InferenceConfig):
        self._config = config
        self._model = None
        self._tokenizer = None
        self._device = None

    def _detect_device(self) -> str:
        if self._config.device != "auto":
            return self._config.device
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def load(self):
        import torch
        self._device = self._detect_device()

        try:
            self._load_unsloth()
        except (ImportError, Exception) as e:
            print(f"Unsloth not available ({e}), falling back to plain transformers")
            self._load_transformers()

    def _load_unsloth(self):
        from unsloth import FastLanguageModel

        if self._config.use_lora and os.path.isdir(self._config.model_path):
            from peft import PeftModel
            base, tokenizer = FastLanguageModel.from_pretrained(
                model_name=self._config.base_model_name,
                max_seq_length=self._config.max_seq_length,
                dtype=None,
                load_in_4bit=self._config.load_in_4bit,
            )
            model = PeftModel.from_pretrained(base, self._config.model_path)
        else:
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=self._config.model_path,
                max_seq_length=self._config.max_seq_length,
                dtype=None,
                load_in_4bit=self._config.load_in_4bit,
            )

        FastLanguageModel.for_inference(model)
        self._model = model
        self._tokenizer = tokenizer

    def _load_transformers(self):
        import numpy
        if not hasattr(numpy, "_core") and hasattr(numpy, "core"):
            numpy._core = numpy.core
        import torch
        from transformers.utils import versions as tv
        import transformers.utils.import_utils as iu
        tv.require_version_core = lambda r, h=None: None
        iu._torch_available = True
        from transformers.models.qwen3 import Qwen3ForCausalLM
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self._config.model_path)

        self._device = "cpu"
        self._model = Qwen3ForCausalLM.from_pretrained(
            self._config.model_path,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
        )
        self._model.eval()

    def _build_prompt(
        self,
        scenario: str,
        page_snapshot: Optional[PageSnapshot] = None,
        system_prompt: Optional[str] = None,
        repo_context: Optional[RepoContext] = None,
    ) -> str:
        parts = []
        if system_prompt:
            parts.append(system_prompt)
        if repo_context and not repo_context.is_empty():
            parts.append(repo_context.format_with_source(scenario, max_chars=7500))
        else:
            if page_snapshot:
                parts.append(format_page_context(page_snapshot))
            parts.append(f"=== Task ===\n{scenario}")
            parts.append(
                "Follow the SDET workflow: analyze the feature, identify elements and locators, "
                "plan the action sequence with assertions, apply reliability hardening, "
                "then produce the complete Playwright test code."
            )
        return "\n\n".join(parts)

    def generate(
        self,
        scenario: str,
        page_snapshot: Optional[PageSnapshot] = None,
        system_prompt: Optional[str] = None,
        repo_context: Optional[RepoContext] = None,
    ) -> str:
        if not self._model or not self._tokenizer:
            raise RuntimeError("call .load() before .generate()")

        user_content = self._build_prompt(scenario, page_snapshot, system_prompt, repo_context)
        messages = [{"role": "user", "content": user_content}]
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer([text], return_tensors="pt", padding=True)

        import torch
        if self._device:
            inputs = {k: v.to(self._device) if hasattr(v, "to") else v for k, v in inputs.items()}

        input_len = inputs["input_ids"].shape[1]
        max_tokens = min(self._config.max_new_tokens, 256 if self._device == "cpu" else 2048)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=self._config.temperature or 0.7,
                top_p=self._config.top_p or 0.9,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )

        new_tokens = outputs[0][input_len:]
        raw = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        think_start = raw.find("<think>")
        if think_start != -1:
            think_end = raw.find("</think>", think_start)
            if think_end != -1:
                raw = raw[:think_start] + raw[think_end + len("</think>"):]
        raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
        return raw

    def generate_batch(
        self,
        scenarios: List[str],
        page_snapshot: Optional[PageSnapshot] = None,
    ) -> List[str]:
        return [self.generate(s, page_snapshot) for s in scenarios]

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
