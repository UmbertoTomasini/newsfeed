# News item data model will be defined here. 
from pydantic import BaseModel, ConfigDict
from typing import Optional, ClassVar, Dict
from datetime import datetime

class NewsItem(BaseModel):
    id: str
    source: str
    title: str
    body: Optional[str] = None
    published_at: datetime
    relevance_score: Optional[float] = None
    recency_weight: Optional[float] = None
    final_score: Optional[float] = None
    top_relevant_label: Optional[str] = None

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda dt: dt.isoformat()
        }
    )

    model_json_schema_extra: ClassVar[Dict] = {
        "example": {
            "id": "some-unique-id-123",
            "source": "reddit/sysadmin",
            "title": "Example News Title",
            "body": "This is an example news item body.",
            "published_at": "2024-07-15T10:00:00Z",
            "relevance_score": 0.95,
            "recency_weight": 0.85,
            "final_score": 0.81,
            "top_relevant_label": "Outage (critical and urgent for a IT manager of a company)"
        }
    } 