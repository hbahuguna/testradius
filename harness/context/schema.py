from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional


class ContextBundle(BaseModel):
    ticket_id: str = Field(..., description="Ticket ID")
    title: str
    description: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    figma_links: List[HttpUrl] = Field(default_factory=list)
    prd_link: Optional[HttpUrl] = None
    prior_bugs: List[str] = Field(default_factory=list)
    env_details: dict = Field(default_factory=dict)
    repo: Optional[str] = None
    branch: Optional[str] = None
