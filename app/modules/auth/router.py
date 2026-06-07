"""
Router para el módulo de Autenticación.
"""

from typing import Annotated, List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    BackgroundTasks
)
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.modules.auth import schemas, service
from app.modules.auth.dependencies import is_admin, is_authenticated
from app.modules.auth.models import User
from app.modules.organization import schemas as org_schemas
from app.modules.organization.models import Area, Sede

router = APIRouter()


# --- VISTAS AUTH (Públicas) ---

@router.get("/login", response_class=HTMLResponse)
async def login_view(request: Request):
    return templates.TemplateResponse(request=request, name="auth/login.html", context= {"request": request, "settings": settings})


@router.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_view(request: Request, token: str):
    payload = decode_access_token(token)
    valid = payload is not None and payload.get("type") == "reset"
    
    return templates.TemplateResponse(request=request, name="auth/reset_password.html", context= 
        {"request": request, "token": token, "valid": valid, "settings": settings}
    )


# --- VISTA GESTIÓN USUARIOS (Protegida: Solo Admin) ---

# CORRECCIÓN: Cambiado de "/users" a "/auth/users" para coincidir con el sidebar/navbar
@router.get("/auth/users", response_class=HTMLResponse)
@is_admin
async def users_view(
    request: Request, 
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User
):
    users = await service.get_users(db)

    areas_orm = await db.execute(
        select(Area).options(
            selectinload(Area.sede),
            selectinload(Area.positions),
        )
    )
    areas = [
        org_schemas.AreaRead.model_validate(a).model_dump()
        for a in areas_orm.scalars().all()
    ]

    sedes_orm = await db.execute(select(Sede))
    sedes = [
        org_schemas.SedeRead.model_validate(s).model_dump()
        for s in sedes_orm.scalars().all()
    ]

    return templates.TemplateResponse(request=request, name="auth/users.html", context=
        {
            "request": request,
            "users": users,
            "areas": areas,
            "sedes": sedes,
            "current_user": current_user,
            "settings": settings,
        },
    )


# --- API AUTH ---

@router.post("/api/auth/login", response_model=schemas.Token)
async def login_api(
    response: Response,
    credentials: schemas.UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Login público."""
    user = await service.authenticate_user(db, credentials)
    if not user:
        raise HTTPException(
            status_code=401, detail="Credenciales incorrectas"
        )

    token = service.create_user_token(user)
    
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        samesite="lax",
    )
    
    return {
        "access_token": token, 
        "token_type": "bearer",
        "role": user.role.value,
        "is_superadmin": user.email == settings.SUPERADMIN_EMAIL,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/api/auth/refresh", response_model=schemas.Token)
@is_authenticated
async def refresh_token_api(
    response: Response,
    current_user: User
):
    new_token = service.create_user_token(current_user)
    
    response.set_cookie(
        key="access_token",
        value=f"Bearer {new_token}",
        httponly=True,
        samesite="lax",
    )
    
    return {
        "access_token": new_token, 
        "token_type": "bearer",
        "role": current_user.role.value,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/api/auth/forgot-password")
async def forgot_password_api(
    data: schemas.ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks
):
    user = await service.get_user_by_email(db, data.email)
    if user:
        background_tasks.add_task(service.send_recovery_email, user, is_invite=False)
    return {"message": "Si el correo existe, recibirás instrucciones."}


@router.post("/api/auth/reset-password")
async def reset_password_api(
    data: schemas.ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    success = await service.process_password_reset(db, data.token, data.new_password)
    if not success:
        raise HTTPException(400, "Token inválido o expirado.")
    return {"message": "Contraseña actualizada correctamente."}


# --- API USUARIOS (CRUD Protegido: Solo Admin) ---

@router.get("/api/users", response_model=List[schemas.UserRead])
@is_admin
async def read_users(db: Annotated[AsyncSession, Depends(get_db)]):
    return await service.get_users(db)


@router.post("/api/users", response_model=schemas.UserRead, status_code=201)
@is_admin
async def create_user(
    user: schemas.UserCreate, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create_user(db, user)


@router.put("/api/users/{user_id}", response_model=schemas.UserRead)
@is_admin
async def update_user(
    user_id: int,
    user: schemas.UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await service.update_user(db, user_id, user)
    if not updated:
        raise HTTPException(404, "Usuario no encontrado")
    return updated


@router.delete("/api/users/{user_id}", status_code=204)
@is_admin
async def delete_user(
    user_id: int, db: Annotated[AsyncSession, Depends(get_db)]
):
    if not await service.delete_user(db, user_id):
        raise HTTPException(404, "Usuario no encontrado")
    return None


@router.post("/api/users/{user_id}/resend-invite")
@is_admin
async def resend_invite_api(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks
):
    user = await service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    
    background_tasks.add_task(service.send_recovery_email, user, is_invite=True)
    return {"message": "Invitación reenviada correctamente."}