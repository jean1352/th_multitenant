from fastapi import Request
from fastapi.templating import Jinja2Templates
from app.core.config import settings

def tenant_context_processor(request: Request):
    return {"tenant": getattr(request.state, "tenant", None)}

templates = Jinja2Templates(
    directory="app/templates", 
    context_processors=[tenant_context_processor]
)
