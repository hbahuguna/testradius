from pydantic import BaseModel
from typing import Optional, List, Dict
from .symbols import CodeSymbol, SymbolBatch, SymbolType

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "0.1.0"

class ExecutionRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None

class ExecutionResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    run_id: str

class LLMModelInfo(BaseModel):
    name: str
    description: Optional[str] = None
    context_window: int = 8192

class ProviderConfig(BaseModel):
    provider_name: str
    api_key: str
    models: List[LLMModelInfo] = []

class TraceMetadata(BaseModel):
    trace_id: str
    span_id: str
    model_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    token_usage: Dict[str, int] = {}

class LLMRequest(BaseModel):
    prompt: str
    provider_name: str
    model_name: str
    trace: Optional[TraceMetadata] = None
    schema_name: Optional[str] = None
    max_tokens: Optional[int] = 1024
    temperature: float = 0.0

class LLMResponse(BaseModel):
    content: str
    parsed_json: Optional[Dict] = None
    model_name: str
    provider_name: str
    trace: Optional[TraceMetadata] = None

class RunRequest(BaseModel):
    repo_url: str
    ref: str = "main"
    command: str
    env: Dict[str, str] = {}
    trace_id: str

class RunStatus(BaseModel):
    run_id: str
    status: str
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
