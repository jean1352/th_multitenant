from pydantic import BaseModel
from typing import Optional

class TenantBase(BaseModel):
    name: str
    subdomain: str

class TenantCreate(TenantBase):
    pass

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class Tenant(TenantBase):
    id: int
    schema_name: str
    is_active: bool

    class Config:
        from_attributes = True
