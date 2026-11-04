from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class JobCreate(BaseModel):
    module: str
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)

class JobResponse(BaseModel):
    id: str
    module: str
    action: str
    status: str
    progress: int = 0
    total: int = 0
    success_count: int = 0
    fail_count: int = 0
    message: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    result_file: Optional[str] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

class JobListResponse(BaseModel):
    jobs: List[JobResponse]
    total: int
