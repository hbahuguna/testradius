import modal
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch

MODEL_PATH = "/model/qwen-3-8B-sdet"

def download_model():
    from huggingface_hub import snapshot_download
    snapshot_download("hbahuguna/qwen-3-8B-sdet", local_dir=MODEL_PATH)

image = (
    modal.Image.debian_slim()
    .pip_install(
        "torch", "transformers", "accelerate", "huggingface_hub",
        "fastapi[standard]", "bitsandbytes",
    )
    .run_function(download_model, secrets=[modal.Secret.from_name("hf-token")])
)

app = modal.App("qwen-3-8b-sdet")

@app.cls(gpu="T4", image=image, scaledown_window=300, secrets=[modal.Secret.from_name("hf-token")])
class QwenSDET:
    def __init__(self):
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            quantization_config=quantization_config,
            device_map="auto",
        )
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

    @modal.fastapi_endpoint(method="POST")
    def generate(self, body: dict):
        prompt = body["prompt"]
        max_tokens = body.get("max_tokens", 512)
        temperature = body.get("temperature", 0.7)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True,
        )
        return {"response": self.tokenizer.decode(outputs[0], skip_special_tokens=True)}
