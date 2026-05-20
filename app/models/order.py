from pydantic import BaseModel


class OrderDetails(BaseModel):
    name: str
    flavour: str
    size: str
    message: str
    phone: str
    allergies: str
