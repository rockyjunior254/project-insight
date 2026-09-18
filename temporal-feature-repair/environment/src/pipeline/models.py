from pydantic import BaseModel, Field
from typing import Optional

class RawEventRecord(BaseModel):
    event_id: str
    customer_id: int
    event_time: str
    ingestion_time: str
    operation: str
    event_type: str
    amount: float
    status: str
    version: int

class CustomerProfileRecord(BaseModel):
    customer_id: int
    segment: str
    risk_tier: str
    country: str
    credit_limit: float
    effective_from: str
    effective_to: str
    is_current: bool

class PredictionCutoffRecord(BaseModel):
    cutoff_id: str
    cutoff_time: str

class CustomerFeatureVector(BaseModel):
    cutoff_id: str
    cutoff_time: str
    customer_id: int
    segment: str
    risk_tier: str
    country: str
    credit_limit: float
    window_30d_tx_count: int
    window_30d_total_spend: float
    window_90d_tx_count: int
    window_90d_total_spend: float
    days_since_last_purchase: Optional[float]
    lifetime_completed_tx_count: int
    lifetime_completed_total_spend: float
    limit_utilization_30d: float

