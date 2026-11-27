import re
from pydantic import BaseModel, field_validator
from typing import Optional

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$")
_RESERVED_SUBDOMAINS = {
    "www", "admin", "api", "localhost", "public",
    "pg_catalog", "information_schema", "root", "app",
}


class TenantBase(BaseModel):
    name: str
    subdomain: str

class TenantCreate(TenantBase):
    @field_validator("subdomain")
    @classmethod
    def validate_subdomain(cls, v: str) -> str:
        val = (v or "").strip().lower()
        if not _SUBDOMAIN_RE.fullmatch(val) or "--" in val:
            raise ValueError(
                "El subdominio solo puede contener letras minúsculas, números y guiones simples (2-32 caracteres)."
            )
        if val in _RESERVED_SUBDOMAINS:
            raise ValueError(f"El subdominio '{val}' está reservado.")
        return val

class TenantUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class Tenant(TenantBase):
    id: int
    schema_name: str
    is_active: bool

    class Config:
        from_attributes = True
