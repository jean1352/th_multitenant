from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.tenants.models import Tenant
from app.core.tenants import set_current_tenant
import logging

logger = logging.getLogger(__name__)

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.url.hostname
        # Supongamos que el dominio base es algo como 'localhost' o 'tuapp.com'
        # Si host es 'cliente1.localhost', el subdominio es 'cliente1'
        
        parts = host.split(".")
        subdomain = None
        
        # Lógica simple para extraer subdominio. 
        # Si es localhost y tiene más de una parte: parte[0] es subdominio.
        # Si es un dominio real (ej: app.com) y tiene 3 partes: parte[0] es subdominio.
        if len(parts) > 1:
            # Caso especial para localhost: 'tenant.localhost' -> parts = ['tenant', 'localhost']
            if parts[-1] == "localhost":
                if len(parts) > 1:
                    subdomain = parts[0]
            # Caso para dominios de segundo nivel: 'tenant.myapp.com' -> parts = ['tenant', 'myapp', 'com']
            elif len(parts) >= 3:
                subdomain = parts[0]

        if subdomain and subdomain != "www":
            async with AsyncSessionLocal() as db:
                # Importante: Aquí todavía no hemos seteado el search_path, 
                # pero el modelo Tenant tiene __table_args__ = {"schema": "public"}
                # por lo que SQLAlchemy debería encontrarlo.
                result = await db.execute(select(Tenant).where(Tenant.subdomain == subdomain, Tenant.is_active == True))
                tenant = result.scalar_one_or_none()
                
                if not tenant:
                    raise HTTPException(status_code=404, detail=f"Tenant '{subdomain}' no encontrado o inactivo.")
                
                set_current_tenant(tenant)
                request.state.tenant = tenant
        else:
            request.state.tenant = None

        response = await call_next(request)
        return response
