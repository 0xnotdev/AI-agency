from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, Any, Dict
from uuid import UUID

class WebhookLeadPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    client_id: UUID
    external_lead_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    source: str = Field(..., pattern="^(inbound|reactivation)$")
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
