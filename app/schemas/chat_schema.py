from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from uuid import uuid4

class ChatRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    # Authenticated API routes replace this with the JWT subject. Optional only
    # for backwards-compatible parsing and direct local CLI usage.
    user_id: Optional[str] = None
    session_id: str
    message: str
    language: Optional[str] = "vi"
    stream: bool = False

class ChatResponse(BaseModel):
    request_id: str
    answer: str
    confidence: float
    route: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
