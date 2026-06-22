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
        host = request.url.hostname or ""
        
        # Extraemos el host base configurado en la aplicación
        from app.core.config import settings
        from urllib.parse import urlparse
        
        parsed_base = urlparse(settings.BASE_URL)
        base_host = parsed_base.hostname or "localhost"
        
        subdomain = None
        
        # Si el host actual es distinto al host base, determinamos si hay subdominio
        if host != base_host:
            if host.endswith(f".{base_host}"):
                subdomain = host[:-len(base_host)-1]

        if subdomain and subdomain != "www":
            async with AsyncSessionLocal() as db:
                # Importante: Aquí todavía no hemos seteado el search_path, 
                # pero el modelo Tenant tiene __table_args__ = {"schema": "public"}
                # por lo que SQLAlchemy debería encontrarlo.
                result = await db.execute(select(Tenant).where(Tenant.subdomain == subdomain, Tenant.is_active == True))
                tenant = result.scalar_one_or_none()
                
                if not tenant:
                    from app.core.templates import templates
                    return templates.TemplateResponse(
                        request=request, 
                        name="tenant_not_found.html", 
                        context={"request": request, "subdomain": subdomain, "settings": settings}, 
                        status_code=404
                    )
                
                set_current_tenant(tenant)
                request.state.tenant = tenant
        else:
            request.state.tenant = None

        response = await call_next(request)
        return response
