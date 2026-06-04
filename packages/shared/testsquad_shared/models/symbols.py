from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum

class SymbolType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    COMPONENT = "component"
    VARIABLE = "variable"

class CodeSymbol(BaseModel):
    name: str
    type: SymbolType
    file_path: str
    start_line: int
    end_line: int
    summary: Optional[str] = Field(None, description="Semantic summary of the symbol's purpose")
    is_entry_point: bool = Field(False, description="Whether this symbol is a public entry point (API, CLI, etc.)")
    surface_type: Optional[str] = Field(None, description="The type of entry point (e.g., 'api', 'cli', 'export')")
    commit_count: int = Field(0, description="Number of times this symbol has been modified in git history")
    author_count: int = Field(0, description="Number of unique authors who have modified this symbol")
    is_covered: bool = Field(True, description="Whether this symbol is covered by tests")
    coverage_score: float = Field(1.0, description="Coverage percentage for this symbol (0.0 to 1.0)")
    priority_risk_index: float = Field(0.0, description="Synthesized risk score for prioritization (PRI)")
    content: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

class SymbolBatch(BaseModel):
    batch_id: str
    symbols: List[CodeSymbol]
    total_tokens: int
    metadata: dict = Field(default_factory=dict)
