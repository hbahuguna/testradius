from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Relationship, JSON

class User(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)  # Using Supabase UID (uuid) as primary key
    email: str = Field(index=True, unique=True)
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    projects: List["Project"] = Relationship(back_populates="owner")

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    owner_id: Optional[str] = Field(default=None, foreign_key="user.id")
    owner: Optional[User] = Relationship(back_populates="projects")
    
    repositories: List["Repository"] = Relationship(back_populates="project")
    style_capsule: Optional["StyleCapsule"] = Relationship(
        back_populates="project", 
        sa_relationship_kwargs={"uselist": False}
    )

class StyleCapsule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", unique=True)
    framework: str = "pytest"
    foundational_patterns: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    negative_patterns: List[str] = Field(default_factory=list, sa_type=JSON)
    reference_examples: List[Dict[str, str]] = Field(default_factory=list, sa_type=JSON)
    
    project: Project = Relationship(back_populates="style_capsule")

class FeatureFlag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    flag_name: str = Field(index=True)
    enabled: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

class Repository(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    url: str = Field(index=True)
    language: str
    branch: str = "main"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    project: Project = Relationship(back_populates="repositories")
    scans: List["Scan"] = Relationship(back_populates="repository")

class Scan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repository_id: int = Field(foreign_key="repository.id")
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
    sha: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    
    repository: Repository = Relationship(back_populates="scans")
