"""
Lógica de negocio para el módulo de Autenticación.
Maneja la verificación de credenciales, hashing y operaciones CRUD.
"""

from datetime import timedelta
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.core.email_utils import send_email_async
from app.modules.auth.models import User
from app.modules.auth.schemas import UserCreate, UserLogin, UserUpdate


async def authenticate_user(
    db: AsyncSession, credentials: UserLogin
) -> Optional[User]:
    """Verifica email y contraseña de un usuario."""
    normalized_email = credentials.email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        return None
    if not verify_password(credentials.password, user.hashed_password):
        return None
    return user


def create_user_token(user: User) -> str:
    """Genera un token JWT para un usuario autenticado, fijado al esquema del tenant actual."""
    tenant = get_current_tenant()
    tenant_schema = tenant.schema_name if tenant else "public"
    return create_access_token(
        data={"sub": user.email, "role": user.role.value, "id": user.id, "tenant": tenant_schema}
    )


async def get_users(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> List[User]:
    """Obtiene lista de usuarios con su Área cargada."""
    stmt = (
        select(User)
        .options(selectinload(User.area))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Busca un usuario por su ID."""
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Busca un usuario por su Email."""
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_user(db: AsyncSession, user_in: UserCreate) -> User:
    """Crea un nuevo usuario en la base de datos."""
    normalized_email = user_in.email.strip().lower()
    existing = await get_user_by_email(db, normalized_email)
    if existing:
        raise HTTPException(400, "Ya existe un usuario con ese correo electrónico.")

    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=normalized_email,
        full_name=user_in.full_name,
        hashed_password=hashed_password,
        role=user_in.role,
        is_active=user_in.is_active,
        sede_id=user_in.sede_id,
        area_id=user_in.area_id,
        role_id=user_in.role_id,
    )
    db.add(db_user)
    await db.flush()
    await db.refresh(db_user)
    await db.commit()
    return db_user


async def update_user(
    db: AsyncSession, user_id: int, user_in: UserUpdate
) -> Optional[User]:
    """Actualiza los datos de un usuario y sincroniza su email con el empleado vinculado."""
    db_user = await get_user_by_id(db, user_id)
    if not db_user:
        return None

    update_data = user_in.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"]:
        new_email = update_data["email"].strip().lower()
        conflict = await db.scalar(
            select(User).where(
                func.lower(User.email) == new_email,
                User.id != user_id,
            )
        )
        if conflict:
            raise HTTPException(400, "Ya existe otro usuario con ese correo electrónico.")
        update_data["email"] = new_email
        if db_user.employee_id:
            from app.modules.employees.models import Employee
            emp = await db.get(Employee, db_user.employee_id)
            if emp:
                emp.institutional_email = new_email
                db.add(emp)
    elif "email" in update_data:
        update_data.pop("email")

    # Si envían password, lo hasheamos. Si es None o vacío, lo ignoramos.
    if "password" in update_data:
        password = update_data.pop("password")
        if password:
            update_data["hashed_password"] = get_password_hash(password)

    for key, value in update_data.items():
        setattr(db_user, key, value)

    await db.flush()
    await db.refresh(db_user)
    await db.commit()
    return db_user


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    """Elimina un usuario por su ID."""
    db_user = await get_user_by_id(db, user_id)
    if not db_user:
        return False
    await db.delete(db_user)
    await db.commit()
    return True


async def ensure_superadmin(db: AsyncSession) -> User:
    """Asegura que el superadmin configurado en .env exista en la tabla pública."""
    from app.core.config import settings
    from app.modules.auth.models import UserRole
    
    stmt = select(User).where(User.email == settings.SUPERADMIN_EMAIL)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        hashed_password = get_password_hash(settings.SUPERADMIN_PASSWORD)
        user = User(
            email=settings.SUPERADMIN_EMAIL,
            full_name="Super Administrador",
            hashed_password=hashed_password,
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    return user


from app.core.tenants import get_tenant_base_url, get_current_tenant

# ...

# --- LÓGICA DE RECUPERACIÓN DE CONTRASEÑA ---

async def send_recovery_email(user: User, is_invite: bool = False) -> bool:
    """
    Genera un token de un solo uso (JWT corto) y envía el correo.
    Sirve tanto para 'Olvidé contraseña' como para 'Reenviar invitación'.
    """
    # Token expira en 24 horas para invitaciones, 1 hora para reset
    expire = timedelta(hours=24) if is_invite else timedelta(hours=1)
    
    tenant = get_current_tenant()
    tenant_schema = tenant.schema_name if tenant else "public"

    # Creamos un token especial con type='reset' ligado al tenant actual
    reset_token = create_access_token(
        data={"sub": user.email, "type": "reset", "id": user.id, "tenant": tenant_schema},
        expires_delta=expire
    )
    
    base_url = get_tenant_base_url()
    business_name = tenant.name if tenant else settings.BUSINESS_NAME
    
    link = f"{base_url}/reset-password?token={reset_token}"
    
    if is_invite:
        subject = f"Invitación al Sistema - {business_name}"
        title = "Bienvenido al Sistema"
        message = "Se ha creado tu cuenta. Por favor, configura tu contraseña para acceder."
        btn_text = "Configurar Cuenta"
    else:
        subject = "Recuperación de Contraseña"
        title = "Restablecer Contraseña"
        message = "Hemos recibido una solicitud para restablecer tu contraseña."
        btn_text = "Restablecer Contraseña"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 8px;">
        <div style="text-align: center; margin-bottom: 20px;">
            <h2 style="color: #003366;">{title}</h2>
        </div>
        <p>Hola <strong>{user.full_name}</strong>,</p>
        <p>{message}</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{link}" style="background-color: #003366; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                {btn_text}
            </a>
        </div>
        <p style="font-size: 12px; color: #666;">Si no solicitaste esto, puedes ignorar este correo. El enlace expirará pronto.</p>
    </div>
    """
    
    return await send_email_async(user.email, subject, html_body, is_html=True)


async def process_password_reset(db: AsyncSession, token: str, new_password: str) -> bool:
    """Valida el token (incluido el tenant) y actualiza la contraseña."""
    payload = decode_access_token(token)
    if not payload or payload.get("type") != "reset":
        return False

    tenant = get_current_tenant()
    expected_tenant = tenant.schema_name if tenant else "public"
    if payload.get("tenant") != expected_tenant:
        return False
    
    user_id = payload.get("id")
    user = await get_user_by_id(db, user_id)
    
    if not user:
        return False
        
    user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return True