import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal

# Import all models to configure the SQLAlchemy class registry
import app.modules.auth.models
import app.modules.organization.models
import app.modules.recruitment.models
import app.modules.employees.models
import app.modules.trainings.models
import app.modules.notifications.models
import app.modules.calendar.models
import app.modules.scheduler.models
import app.modules.benefits.models
import app.modules.disciplinary.models
import app.modules.dietary.models

from app.modules.benefits.models import BenefitRequest, BenefitRequestAuthorizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_authorizers():
    logger.info("Starting migration of single-authorizer fields to benefit_request_authorizers...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Seleccionar todas las solicitudes que tengan un autorizante asignado
            stmt = select(BenefitRequest).where(BenefitRequest.authorizer_id != None)
            result = await db.execute(stmt)
            requests = result.scalars().all()
            
            migrated_count = 0
            skipped_count = 0
            
            for req in requests:
                # Verificar si ya existe este autorizante en la tabla de múltiples autorizantes
                check_stmt = select(BenefitRequestAuthorizer).where(
                    BenefitRequestAuthorizer.benefit_request_id == req.id,
                    BenefitRequestAuthorizer.authorizer_id == req.authorizer_id
                )
                check_res = await db.execute(check_stmt)
                existing = check_res.scalar_one_or_none()
                
                if not existing:
                    # Crear nuevo autorizante múltiple
                    new_auth = BenefitRequestAuthorizer(
                        benefit_request_id=req.id,
                        authorizer_id=req.authorizer_id,
                        authorizer_position_id=req.authorizer_position_id,
                        authorization_level_id=req.authorization_level_id
                    )
                    db.add(new_auth)
                    migrated_count += 1
                else:
                    skipped_count += 1
                    
            if migrated_count > 0:
                await db.commit()
                logger.info(f"Successfully migrated {migrated_count} authorizers.")
            else:
                logger.info("No new authorizers needed migration.")
                
            logger.info(f"Migration completed. Total migrated: {migrated_count}, Skipped (already existing): {skipped_count}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error during migration: {e}")
            raise e

if __name__ == "__main__":
    asyncio.run(migrate_authorizers())
