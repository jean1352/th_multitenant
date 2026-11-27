import asyncio
import logging
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal

# --- IMPORTACIONES CRÍTICAS DE TODOS LOS MODELOS ---
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.benefits.models
import app.modules.disciplinary.models
import app.modules.dietary.models

from app.modules.employees.models import Employee
from app.modules.auth.models import User, UserRole
from app.modules.organization.models import Position, Area
from app.core.security import get_password_hash

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "Up.2025!"  # Contraseña por defecto para los nuevos usuarios

async def create_missing_users():
    logger.info("🚀 Iniciando generación de usuarios para colaboradores existentes...")
    
    async with AsyncSessionLocal() as db:
        # 1. Obtener colaboradores activos con email institucional
        # Cargamos la posición y el área para asignar correctamente los permisos de visualización
        stmt = (
            select(Employee)
            .options(
                selectinload(Employee.position_obj).selectinload(Position.area)
            )
            .where(
                Employee.is_active == True,
                Employee.institutional_email.is_not(None),
                Employee.institutional_email != ""
            )
        )
        result = await db.execute(stmt)
        employees = result.scalars().all()
        
        created_count = 0
        linked_count = 0
        skipped_count = 0
        errors_count = 0

        logger.info(f"📋 Se encontraron {len(employees)} colaboradores activos con email.")

        for emp in employees:
            try:
                email = emp.institutional_email.strip()
                
                # 2. Verificar si ya existe un usuario (por email o por ID de empleado)
                stmt_check = select(User).where(
                    or_(
                        User.email == email,
                        User.employee_id == emp.id
                    )
                )
                existing_user = (await db.execute(stmt_check)).scalar_one_or_none()

                # Datos de Área/Sede derivados del cargo del empleado
                area_id = None
                sede_id = None
                if emp.position_obj and emp.position_obj.area:
                    area_id = emp.position_obj.area.id
                    sede_id = emp.position_obj.area.sede_id

                if existing_user:
                    # CASO A: El usuario existe pero no está vinculado
                    if not existing_user.employee_id:
                        existing_user.employee_id = emp.id
                        existing_user.full_name = emp.full_name # Actualizar nombre
                        existing_user.area_id = area_id
                        existing_user.sede_id = sede_id
                        
                        db.add(existing_user)
                        linked_count += 1
                        logger.info(f"🔗 VINCULADO: Usuario existente '{email}' asociado al colaborador ID {emp.id}")
                    else:
                        # CASO B: Ya existe y está vinculado
                        skipped_count += 1
                else:
                    # CASO C: No existe usuario -> CREARLO
                    hashed_pwd = get_password_hash(DEFAULT_PASSWORD)
                    
                    new_user = User(
                        email=email,
                        full_name=emp.full_name,
                        hashed_password=hashed_pwd,
                        role=UserRole.EMPLOYEE, # Rol por defecto
                        is_active=True,
                        employee_id=emp.id,
                        area_id=area_id,
                        sede_id=sede_id
                    )
                    db.add(new_user)
                    created_count += 1
                    logger.info(f"✨ CREADO: Usuario para '{email}' (Pass: {DEFAULT_PASSWORD})")

            except Exception as e:
                logger.error(f"❌ Error procesando colaborador {emp.full_name}: {e}")
                errors_count += 1

        await db.commit()
        
        logger.info("-" * 50)
        logger.info("🏁 RESUMEN DEL PROCESO:")
        logger.info(f"   ✅ Usuarios Creados: {created_count}")
        logger.info(f"   🔗 Usuarios Vinculados: {linked_count}")
        logger.info(f"   ⏭️  Omitidos (Ya correctos): {skipped_count}")
        logger.info(f"   ❌ Errores: {errors_count}")
        logger.info("-" * 50)
        if created_count > 0:
            logger.info(f"ℹ️  Nota: La contraseña para los nuevos usuarios es '{DEFAULT_PASSWORD}'")

if __name__ == "__main__":
    asyncio.run(create_missing_users())