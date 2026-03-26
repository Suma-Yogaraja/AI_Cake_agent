from pydantic import BaseModel
from typing import Optional

class OrderSchema(BaseModel):
    customer_name: str
    cake_flavour: str
    cake_size: str
    cake_message: Optional[str] = ""
    customer_phone: str

class OrderResponse(BaseModel):
    order_id: str
    message: str

class TranscriptRequest(BaseModel):
    call_sid: str
    transcript: str

class VoiceRequest(BaseModel):
    call_sid: str
    phone_number: Optional[str] = ""