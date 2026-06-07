from contextvars import ContextVar
from typing import Optional
from app.modules.tenants.models import Tenant

_current_tenant: ContextVar[Optional[Tenant]] = ContextVar("current_tenant", default=None)

def get_current_tenant() -> Optional[Tenant]:
    return _current_tenant.get()

def set_current_tenant(tenant: Tenant) -> None:
    _current_tenant.set(tenant)

def get_tenant_base_url() -> str:
    from app.core.config import settings
    tenant = get_current_tenant()
    if not tenant:
        return settings.BASE_URL
    
    # Supongamos que BASE_URL es 'http://localhost:8006' o 'https://myapp.com'
    from urllib.parse import urlparse
    parsed = urlparse(settings.BASE_URL)
    
    # Si es localhost
    if parsed.hostname == "localhost":
        return f"{parsed.scheme}://{tenant.subdomain}.localhost:{parsed.port}" if parsed.port else f"{parsed.scheme}://{tenant.subdomain}.localhost"
    
    # Si es un dominio real, insertamos el subdominio
    return f"{parsed.scheme}://{tenant.subdomain}.{parsed.hostname}"
