from functools import wraps
from inspect import Parameter, signature
from typing import Annotated, List

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.exceptions import RolePermissionError
from app.core.security import decode_access_token
from app.modules.auth.models import User, UserRole
from app.modules.auth.service import get_user_by_id

class NeedsLoginException(Exception):
    """Excepción específica para usuarios no autenticados."""
    pass

async def get_current_user(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Obtiene el usuario actual desde Header o Cookie.
    """
    token = None
    
    # 1. Header Authorization (Prioridad API)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    
    # 2. Cookie fallback (Prioridad Navegador)
    if not token:
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            token = cookie_token.split(" ")[1] if " " in cookie_token else cookie_token

    if not token:
        raise NeedsLoginException("No has iniciado sesión.")

    # Validar fecha de vencimiento del token

    payload = decode_access_token(token)
    if not payload:
        raise NeedsLoginException("No has iniciado sesión.")

    user_id = payload.get("id")
    
    # 3. Validar usuario en el contexto del tenant actual
    # Si estamos en un tenant, get_db ya nos dio una sesión con el search_path correcto.
    user = await get_user_by_id(db, user_id)
    
    # Si no hay tenant (dominio principal), el usuario debe ser de la tabla pública.
    # El middleware ya maneja el search_path, así que get_user_by_id buscará en el esquema actual.
    
    if not user or not user.is_active:
        raise RolePermissionError("Usuario no encontrado o inactivo en este entorno.")
        
    return user


class RoleChecker:
    """Validador de roles (Callable Dependency)."""
    def __init__(self, allowed_roles: List[UserRole]):
        self.allowed_roles = allowed_roles

    async def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise RolePermissionError(
                f"Se requiere uno de los siguientes roles: {[r.value for r in self.allowed_roles]}"
            )
        return user


def create_role_decorator(allowed_roles: List[UserRole], require_superadmin: bool = False):
    """
    Crea un decorador que inyecta la validación de roles como una dependencia de FastAPI.
    """
    def decorator(func):
        checker = RoleChecker(allowed_roles)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 1. Identificar al usuario (inyectado por FastAPI vía Depends)
            user = kwargs.get("current_user")
            check_key = None
            if not user:
                for key, val in kwargs.items():
                    if key.startswith("__role_check_"):
                        user = val
                        check_key = key
                        break
            
            # 2. Check adicional para SuperAdmin si se requiere
            if require_superadmin:
                if not user or user.email != settings.SUPERADMIN_EMAIL:
                    raise RolePermissionError("Acceso denegado: Solo el Super Administrador Global puede acceder.")

            # 3. Limpiar parámetros internos para que la función original no explote
            if check_key:
                kwargs.pop(check_key)
            
            # 4. Ejecutar la función original
            return await func(*args, **kwargs)

        # Extraer la firma original
        sig = signature(func)
        params = list(sig.parameters.values())

        # Inyectar el checker como dependencia
        new_params = []
        found = False
        for p in params:
            if p.name == "current_user":
                new_params.append(p.replace(default=Depends(checker)))
                found = True
            else:
                new_params.append(p)

        if not found:
            # Añadir parámetro de check invisible al final (pero antes de **kwargs)
            check_param = Parameter(
                name=f"__role_check_{allowed_roles[0].value}",
                kind=Parameter.KEYWORD_ONLY,
                default=Depends(checker)
            )
            idx = len(new_params)
            for i, p in enumerate(new_params):
                if p.kind == Parameter.VAR_KEYWORD:
                    idx = i
                    break
            new_params.insert(idx, check_param)

        # Aplicar la nueva firma al wrapper (Esto quita *args y **kwargs de la vista de FastAPI)
        wrapper.__signature__ = sig.replace(parameters=new_params)
        return wrapper

    return decorator


# --- DECORADORES ---

# Solo Administradores (de tenant o globales)
is_admin = create_role_decorator([UserRole.ADMIN])

# Solo Super Administrador Global (definido por email en settings)
is_superadmin = create_role_decorator([UserRole.ADMIN], require_superadmin=True)

# Managers y Admins
is_manager = create_role_decorator([UserRole.ADMIN, UserRole.MANAGER])

# Reclutadores (TH), Managers y Admins
is_recruiter = create_role_decorator([UserRole.ADMIN, UserRole.MANAGER, UserRole.TH])

# Cualquier usuario logueado
is_authenticated = create_role_decorator([
    UserRole.ADMIN, UserRole.MANAGER, UserRole.TH, UserRole.EMPLOYEE
])

# --- PERMISOS GRANULARES (RBAC DINÁMICO) ---
def require_permission(permission_code: str):
    """
    Dependencia de FastAPI que valida que el usuario autenticado tenga el permiso granular especificado,
    ya sea a través de su rol estático (ADMIN tiene todo) o de su rol relacional dinámico (RBAC).
    """
    async def dependency(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        # 1. Los Administradores Globales (rol estático ADMIN) tienen acceso completo automático
        if user.role == UserRole.ADMIN:
            return user
            
        # 2. Si el usuario tiene asignado un rol dinámico en la DB (role_id), validar sus permisos
        if user.role_id:
            from app.modules.auth.models import Role
            stmt = (
                select(Role)
                .options(selectinload(Role.permissions))
                .where(Role.id == user.role_id)
            )
            role = (await db.execute(stmt)).scalar_one_or_none()
            if role:
                permission_codes = {p.code for p in role.permissions}
                if permission_code in permission_codes:
                    return user
                    
        raise RolePermissionError(
            f"Acceso denegado: Se requiere el permiso granular '{permission_code}'."
        )
    return Depends(dependency)