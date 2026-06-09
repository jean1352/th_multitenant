#!/usr/bin/env python3
"""
Script de carga y limpieza quirúrgica de datos semilla (Seed Data) para un Tenant específico.
Permite poblar y limpiar bases de datos de demostración de manera segura sin afectar usuarios reales.
"""

import os
import sys
import argparse
import asyncio
from datetime import date, datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Asegurar que el directorio raíz está en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.database import AsyncSessionLocal, engine
from app.core.config import settings
from app.core.security import get_password_hash

# Importar Modelos
from app.modules.tenants.models import Tenant
from app.modules.tenants.service import create_tenant, get_tenant_by_subdomain
from app.modules.organization.models import (
    Sede, Area, Position, Company, ContractType, WorkingDayType,
    SalaryType, Currency, PaymentMethod, Bank
)
from app.modules.auth.models import User, UserRole
from app.modules.employees.models import Employee, EmployeePosition, EmergencyContact, EmploymentStatus
from app.modules.dietary.models import DietaryRestriction
from app.modules.benefits.models import (
    BenefitType, EmployeeBenefit, BenefitRequest, BenefitRequestItem,
    BenefitRequestType, BenefitSubtype, BenefitGrantReason, AuthorizationLevel,
    BenefitModality, BenefitFrequency
)
from app.modules.disciplinary.models import Sanction, Recognition, SanctionType, RecognitionType
from app.modules.calendar.models import CalendarEvent, CalendarEventType
from app.modules.recruitment.models import (
    RecruitmentProcess, HiringReason, ProcessStage, Vacancy, VacancyStage, ProcessStatus, StageOwner, VacancyType
)
from app.modules.trainings.models import (
    TrainingProvider, Training, TrainingEnrollment, TrainingType, TrainingStatus, EnrollmentStatus
)

async def clean_tenant_data(session: AsyncSession, schema_name: str):
    """
    Limpia de forma quirúrgica únicamente los datos de prueba (demo) del esquema del tenant,
    sin afectar a los usuarios, administradores o datos creados de manera real por el cliente.
    """
    print(f"🧹 Iniciando limpieza quirúrgica de datos demo en esquema: '{schema_name}'...")
    
    # Asegurar el search_path en la sesión
    await session.execute(text(f'SET search_path TO "{schema_name}", public'))
    
    # 1. Borrar vacantes demo (deben ir primero ya que referencian a recruiters en la tabla users)
    try:
        await session.execute(text(
            "DELETE FROM vacancies WHERE title = 'Desarrollador Fullstack Junior'"
        ))
    except Exception:
        pass
        
    # 2. Borrar procesos de selección demo
    try:
        # Borrar primero las etapas del proceso de selección demo
        await session.execute(text(
            "DELETE FROM process_stages WHERE process_id IN "
            "(SELECT id FROM recruitment_processes WHERE name = 'Proceso de Selección de Tecnología')"
        ))
        # Borrar el proceso de selección demo
        await session.execute(text(
            "DELETE FROM recruitment_processes WHERE name = 'Proceso de Selección de Tecnología'"
        ))
    except Exception:
        pass

    # 3. Borrar capacitaciones demo (deben ir antes de borrar los colaboradores ya que uno de ellos es instructor interno)
    try:
        # Borrar inscripciones de capacitaciones demo
        await session.execute(text(
            "DELETE FROM training_enrollments WHERE training_id IN "
            "(SELECT id FROM trainings WHERE name IN ('FastAPI Avanzado y SQL Server', 'Habilidades Blandas en Talento Humano'))"
        ))
        # Borrar capacitaciones
        await session.execute(text(
            "DELETE FROM trainings WHERE name IN ('FastAPI Avanzado y SQL Server', 'Habilidades Blandas en Talento Humano')"
        ))
        # Borrar proveedores demo
        await session.execute(text(
            "DELETE FROM training_providers WHERE ruc = '80099999-9'"
        ))
    except Exception:
        pass

    # 4. Borrar en cascada todos los registros de los colaboradores demo mediante subconsultas puras SQL
    # De esta manera evitamos problemas de mapeo o expansión de listas en SQLAlchemy, y garantizamos que
    # si el cliente creó usuarios reales o administradores en su cuenta, estos queden 100% INTACTOS.
    try:
        # Contactos de emergencia
        await session.execute(text(
            "DELETE FROM emergency_contacts WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Calendario e inscripciones
        await session.execute(text(
            "DELETE FROM event_enrollments WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Capacitaciones e inscripciones generales
        await session.execute(text(
            "DELETE FROM training_enrollments WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Asociación de comedor / dietario
        await session.execute(text(
            "DELETE FROM employee_dietary_association WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Sanciones
        await session.execute(text(
            "DELETE FROM sanctions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Reconocimientos
        await session.execute(text(
            "DELETE FROM recognitions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Solicitudes de Beneficios (Items y Cabecera)
        await session.execute(text(
            "DELETE FROM benefit_request_items WHERE benefit_request_id IN "
            "(SELECT id FROM benefit_requests WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890')))"
        ))
        await session.execute(text(
            "DELETE FROM benefit_requests WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Beneficios activos asignados
        await session.execute(text(
            "DELETE FROM employee_benefits WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Cargos históricos / Contratos
        await session.execute(text(
            "DELETE FROM employee_positions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890'))"
        ))
        
        # Usuarios de acceso demo (solamente se eliminan las credenciales con correos demo,
        # protegiendo por completo a los administradores y usuarios creados legítimamente por el cliente)
        await session.execute(text(
            "DELETE FROM users WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890')) "
            "OR email IN ('maria.lopez@universidad.edu.py', 'ana.benitez@universidad.edu.py', "
            "'carlos.gomez@universidad.edu.py', 'diego.torres@universidad.edu.py')"
        ))
        
        # Finalmente, los Colaboradores demo
        await session.execute(text(
            "DELETE FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890')"
        ))
    except Exception as e:
        await session.rollback()
        print(f"⚠️ Error borrando relaciones de empleados: {e}")
            
    # 5. Borrar eventos de calendario demo
    try:
        await session.execute(text(
            "DELETE FROM calendar_events WHERE title IN ('Almuerzo de Fin de Año UP', 'Taller de Inducción de Seguridad')"
        ))
    except Exception:
        pass
        
    # 7. Borrar catálogos creados por demo (únicamente si no tienen dependencias externas/reales)
    cat_tables = [
        ("benefit_request_types", "Alta"),
        ("benefit_request_types", "Modificación"),
        ("benefit_subtypes", "Seguro Médico"),
        ("benefit_subtypes", "Vales de Combustible"),
        ("benefit_grant_reasons", "Por Política"),
        ("benefit_grant_reasons", "Por Rendimiento"),
        ("authorization_levels", "Gerencia de Personas"),
        ("authorization_levels", "Rectorado"),
        ("benefit_modalities", "Fijo"),
        ("benefit_modalities", "Variable"),
        ("benefit_frequencies", "Mensual"),
        ("benefit_frequencies", "Único"),
        ("benefit_types", "Seguro de Salud Premium"),
        ("benefit_types", "Ayuda de Combustible"),
        ("hiring_reasons", "Reemplazo de Personal"),
        ("hiring_reasons", "Aumento de Estructura"),
        ("calendar_event_types", "Social"),
        ("calendar_event_types", "Capacitación"),
        ("dietary_restrictions", "Celíaco"),
        ("dietary_restrictions", "Vegetariano"),
        ("dietary_restrictions", "Intolerante a la Lactosa"),
        ("companies", "Universidad del Pacífico S.A."),
        ("companies", "Servicios Educativos UP"),
        ("contract_types", "Indefinido"),
        ("contract_types", "Plazo Fijo"),
        ("working_day_types", "Tiempo Completo"),
        ("working_day_types", "Remoto"),
        ("salary_types", "Fijo"),
        ("currencies", "Guaraníes"),
        ("currencies", "Dólares"),
        ("payment_methods", "Transferencia Bancaria"),
        ("banks", "Banco Itaú Paraguay")
    ]
    
    for tbl, name in cat_tables:
        try:
            await session.execute(
                text(f'DELETE FROM "{schema_name}"."{tbl}" WHERE name = :name'),
                {"name": name}
            )
            await session.commit()
        except Exception:
            # Si un elemento real del cliente está usando este catálogo, PostgreSQL lanzará un error de FK,
            # lo cual capturamos y omitimos de forma segura para no alterar sus datos reales.
            await session.rollback()
            continue
            
    # 8. Borrar cargos demo
    demo_pos_names = ["Director de Talento Humano", "Gerente de TI", "Analista de Talento Humano", "Desarrollador Senior"]
    for pos_name in demo_pos_names:
        try:
            await session.execute(
                text('DELETE FROM positions WHERE name = :name'),
                {"name": pos_name}
            )
            await session.commit()
        except Exception:
            await session.rollback()
            continue
            
    # 9. Borrar áreas de prueba
    demo_area_names = ["Talento Humano", "Tecnología de la Información", "Operaciones"]
    for area_name in demo_area_names:
        try:
            await session.execute(
                text('DELETE FROM areas WHERE name = :name'),
                {"name": area_name}
            )
            await session.commit()
        except Exception:
            await session.rollback()
            continue
            
    # 10. Borrar sedes demo
    demo_sede_names = ["Campus Central", "Sede Miraflores"]
    for S_name in demo_sede_names:
        try:
            await session.execute(
                text('DELETE FROM sedes WHERE name = :name'),
                {"name": S_name}
            )
            await session.commit()
        except Exception:
            await session.rollback()
            continue

    await session.commit()
    print("✅ Limpieza quirúrgica de datos demo completada con éxito.")

async def seed_tenant_data(session: AsyncSession, schema_name: str, tenant_name: str):
    """
    Puebla el esquema del Tenant con datos de muestra realistas con distintas marcas temporales.
    """
    print(f"🌱 Población de datos iniciada en el esquema: '{schema_name}'...")
    
    # Establecer la búsqueda de esquema para la sesión actual
    await session.execute(text(f'SET search_path TO "{schema_name}", public'))
    
    # Helper genérico para evitar violaciones de clave única (On Conflict Get Or Create)
    async def get_or_create(model, unique_field, value, **kwargs):
        res = await session.execute(select(model).where(getattr(model, unique_field) == value))
        obj = res.scalar_one_or_none()
        if not obj:
            obj = model(**{unique_field: value}, **kwargs)
            session.add(obj)
            await session.flush()
        return obj

    # ---------------------------------------------------------
    # 1. Catálogos Generales y Configuración Básica
    # ---------------------------------------------------------
    print("   -> Creando catálogos generales...")
    
    # Monedas
    cur_pyg = await get_or_create(Currency, "name", "Guaraníes", symbol="PYG", description="Moneda local de Paraguay")
    cur_usd = await get_or_create(Currency, "name", "Dólares", symbol="USD", description="Dólares estadounidenses")
    
    # Tipos de Contrato
    ct_indef = await get_or_create(ContractType, "name", "Indefinido", description="Contrato de duración indefinida")
    ct_temp = await get_or_create(ContractType, "name", "Plazo Fijo", description="Contrato por un plazo determinado")
    
    # Tipos de Jornada
    wdt_full = await get_or_create(WorkingDayType, "name", "Tiempo Completo", description="Jornada completa tradicional")
    wdt_remote = await get_or_create(WorkingDayType, "name", "Remoto", description="Trabajo 100% a distancia")
    
    # Tipos de Salario
    st_fijo = await get_or_create(SalaryType, "name", "Fijo", description="Salario mensual garantizado")
    
    # Bancos y Métodos de Pago
    bank_itau = await get_or_create(Bank, "name", "Banco Itaú Paraguay")
    pm_transfer = await get_or_create(PaymentMethod, "name", "Transferencia Bancaria")
    
    # Empresas (Razón Social)
    comp_up = await get_or_create(Company, "name", "Universidad del Pacífico S.A.", tax_id="80170151-1")
    comp_serv = await get_or_create(Company, "name", "Servicios Educativos UP", tax_id="80170152-2")

    # ---------------------------------------------------------
    # 2. Sedes, Áreas y Estructura Organizativa
    # ---------------------------------------------------------
    print("   -> Creando estructura organizativa (Sedes, Áreas, Cargos)...")
    
    sede_central = await get_or_create(Sede, "name", "Campus Central", address="Av. España 123, Asunción")
    sede_norte = await get_or_create(Sede, "name", "Sede Miraflores", address="Av. Aviadores del Chaco 456, Asunción")
    
    area_th = await get_or_create(Area, "name", "Talento Humano", responsible_email="th@universidad.edu.py", sede_id=sede_central.id)
    area_ti = await get_or_create(Area, "name", "Tecnología de la Información", responsible_email="ti@universidad.edu.py", sede_id=sede_central.id)
    area_ops = await get_or_create(Area, "name", "Operaciones", responsible_email="ops@universidad.edu.py", sede_id=sede_norte.id)
    
    # Jerarquía de Cargos
    pos_director_th = await get_or_create(Position, "name", "Director de Talento Humano", area_id=area_th.id, is_leader=True)
    pos_gerente_ti = await get_or_create(Position, "name", "Gerente de TI", area_id=area_ti.id, is_leader=True)
    
    pos_analista_th = await get_or_create(Position, "name", "Analista de Talento Humano", area_id=area_th.id, is_leader=False, parent_id=pos_director_th.id)
    pos_dev_sr = await get_or_create(Position, "name", "Desarrollador Senior", area_id=area_ti.id, is_leader=False, parent_id=pos_gerente_ti.id)

    # ---------------------------------------------------------
    # Restricciones Alimenticias (Comedor) - Creadas temprano para asignación segura
    # ---------------------------------------------------------
    dr_gluten = await get_or_create(DietaryRestriction, "name", "Celíaco", description="Intolerancia médica al gluten")
    dr_veg = await get_or_create(DietaryRestriction, "name", "Vegetariano", description="Persona con alimentación basada en plantas")
    dr_lactose = await get_or_create(DietaryRestriction, "name", "Intolerante a la Lactosa", description="Intolerancia a productos lácteos")

    # ---------------------------------------------------------
    # 3. Colaboradores y Contratos de Trabajo
    # ---------------------------------------------------------
    print("   -> Creando colaboradores y asignando cargos históricos...")
    
    # 4 Colaboradores de prueba
    emp_director = Employee(
        first_name="María", last_name="López", full_name="María López", document_id="1234567",
        position_id=pos_director_th.id, gender="Femenino", marital_status="Soltero", nationality="Paraguaya",
        personal_email="maria.lopez@gmail.com", institutional_email="maria.lopez@universidad.edu.py",
        phone="0981111222", birthday=date(1985, 5, 12), employment_status=EmploymentStatus.ACTIVE, company_id=comp_up.id,
        dietary_restrictions=[dr_lactose]
    )
    emp_analista = Employee(
        first_name="Ana", last_name="Benítez", full_name="Ana Benítez", document_id="2345678",
        position_id=pos_analista_th.id, gender="Femenino", marital_status="Soltero", nationality="Paraguaya",
        personal_email="ana.benitez@gmail.com", institutional_email="ana.benitez@universidad.edu.py",
        phone="0982222333", birthday=date(1992, 8, 20), employment_status=EmploymentStatus.ACTIVE, company_id=comp_up.id
    )
    emp_gerente = Employee(
        first_name="Carlos", last_name="Gómez", full_name="Carlos Gómez", document_id="3456789",
        position_id=pos_gerente_ti.id, gender="Masculino", marital_status="Casado", nationality="Paraguaya",
        personal_email="carlos.gomez@gmail.com", institutional_email="carlos.gomez@universidad.edu.py",
        phone="0983333444", birthday=date(1980, 11, 30), employment_status=EmploymentStatus.ACTIVE, company_id=comp_up.id
    )
    emp_dev = Employee(
        first_name="Diego", last_name="Torres", full_name="Diego Torres", document_id="4567890",
        position_id=pos_dev_sr.id, gender="Masculino", marital_status="Casado", nationality="Paraguaya",
        personal_email="diego.torres@gmail.com", institutional_email="diego.torres@universidad.edu.py",
        phone="0984444555", birthday=date(1990, 3, 15), employment_status=EmploymentStatus.ACTIVE, company_id=comp_serv.id,
        dietary_restrictions=[dr_veg]
    )
    session.add_all([emp_director, emp_analista, emp_gerente, emp_dev])
    await session.flush()
    
    # Asignaciones de contrato en EmployeePosition
    ep_director = EmployeePosition(
        employee_id=emp_director.id, position_id=pos_director_th.id, company_id=comp_up.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=12000000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes"
    )
    ep_analista = EmployeePosition(
        employee_id=emp_analista.id, position_id=pos_analista_th.id, company_id=comp_up.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=6000000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes"
    )
    ep_gerente = EmployeePosition(
        employee_id=emp_gerente.id, position_id=pos_gerente_ti.id, company_id=comp_up.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=15000000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes"
    )
    ep_dev = EmployeePosition(
        employee_id=emp_dev.id, position_id=pos_dev_sr.id, company_id=comp_serv.id,
        contract_type_id=ct_temp.id, working_day_type_id=wdt_remote.id, salary_type_id=st_fijo.id,
        base_salary=9000000.0, currency_id=cur_pyg.id, work_schedule="09:00 - 18:00", work_days="Lunes a Viernes",
        contract_end_date=date.today() + timedelta(days=180)
    )
    session.add_all([ep_director, ep_analista, ep_gerente, ep_dev])
    await session.flush()

    # ---------------------------------------------------------
    # 4. Usuarios de Acceso al Sistema (Auth)
    # ---------------------------------------------------------
    print("   -> Creando credenciales y perfiles de acceso (Auth)...")
    
    hashed_pwd = get_password_hash("password123")
    user_director = User(
        email="maria.lopez@universidad.edu.py", full_name="María López", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.TH, employee_id=emp_director.id, sede_id=sede_central.id, area_id=area_th.id
    )
    user_analista = User(
        email="ana.benitez@universidad.edu.py", full_name="Ana Benítez", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.EMPLOYEE, employee_id=emp_analista.id, sede_id=sede_central.id, area_id=area_th.id
    )
    user_gerente = User(
        email="carlos.gomez@universidad.edu.py", full_name="Carlos Gómez", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.MANAGER, employee_id=emp_gerente.id, sede_id=sede_central.id, area_id=area_ti.id
    )
    user_dev = User(
        email="diego.torres@universidad.edu.py", full_name="Diego Torres", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.EMPLOYEE, employee_id=emp_dev.id, sede_id=sede_norte.id, area_id=area_ti.id
    )
    session.add_all([user_director, user_analista, user_gerente, user_dev])
    await session.flush()

    # Contactos de Emergencia
    ec_maria = EmergencyContact(employee_id=emp_director.id, name="Juan López", phone="0981999888")
    ec_diego = EmergencyContact(employee_id=emp_dev.id, name="Laura Torres", phone="0981777666")
    session.add_all([ec_maria, ec_diego])
    await session.flush()

    # ---------------------------------------------------------
    # 5. Restricciones Alimenticias (Comedor)
    # ---------------------------------------------------------
    print("   -> Catálogo de comedor y restricciones alimenticias vinculadas correctamente.")

    # ---------------------------------------------------------
    # 6. Beneficios y Solicitudes con Distintas Marcas Temporales
    # ---------------------------------------------------------
    print("   -> Creando beneficios corporativos e histórico de solicitudes...")
    
    # Catálogos de Solicitudes
    brt_alta = await get_or_create(BenefitRequestType, "name", "Alta")
    brt_mod = await get_or_create(BenefitRequestType, "name", "Modificación")
    
    bs_seguro = await get_or_create(BenefitSubtype, "name", "Seguro Médico")
    bs_vale = await get_or_create(BenefitSubtype, "name", "Vales de Combustible")
    
    bgr_politica = await get_or_create(BenefitGrantReason, "name", "Por Política")
    bgr_rendimiento = await get_or_create(BenefitGrantReason, "name", "Por Rendimiento")
    
    al_gerencia = await get_or_create(AuthorizationLevel, "name", "Gerencia de Personas")
    al_rector = await get_or_create(AuthorizationLevel, "name", "Rectorado")
    
    bm_fijo = await get_or_create(BenefitModality, "name", "Fijo")
    bm_variable = await get_or_create(BenefitModality, "name", "Variable")
    
    bf_mensual = await get_or_create(BenefitFrequency, "name", "Mensual")
    bf_unico = await get_or_create(BenefitFrequency, "name", "Único")
    
    # Tipos de Beneficios
    bt_seguro = await get_or_create(BenefitType, "name", "Seguro de Salud Premium", description="Cobertura prepaga familiar para cargos jerárquicos")
    bt_combustible = await get_or_create(BenefitType, "name", "Ayuda de Combustible", description="Monto mensual para movilidad y traslados")
    
    # Asignación Directa Activa
    eb_director = EmployeeBenefit(
        employee_id=emp_director.id, benefit_type_id=bt_seguro.id,
        start_date=date.today() - timedelta(days=365), details="Asignación inicial", is_active=True
    )
    session.add_all([eb_director])
    await session.flush()
    
    # SOLICITUD 1: Aprobada (Hace 30 días)
    req_approved = BenefitRequest(
        request_code="BE001", employee_id=emp_dev.id, employee_position_id=ep_dev.id,
        request_type_id=brt_alta.id, request_date=date.today() - timedelta(days=30),
        grant_reason_id=bgr_politica.id, justification="Beneficio por modalidd remota distante",
        requester_id=emp_gerente.id, requester_position_id=ep_gerente.id,
        authorization_level_id=al_gerencia.id, authorizer_id=emp_director.id, authorizer_position_id=ep_director.id,
        grant_date=date.today() - timedelta(days=28), resolution_number="RES-2026-TH04",
        status="Aprobada", benefit_status="Activo", approval_comments="Validado con presupuesto de TI",
        created_at=datetime.now() - timedelta(days=30)
    )
    session.add_all([req_approved])
    await session.flush()
    
    item_approved = BenefitRequestItem(
        benefit_request_id=req_approved.id, benefit_type_id=bt_combustible.id, benefit_subtype_id=bs_vale.id,
        currency_id=cur_pyg.id, approved_amount=500000.0, validity_start_date=date.today() - timedelta(days=28),
        validity_end_date=date.today() + timedelta(days=120), benefit_modality_id=bm_fijo.id,
        benefit_frequency_id=bf_mensual.id, description_notes="Gasto de traslado asignado"
    )
    session.add_all([item_approved])
    await session.flush()
    
    # SOLICITUD 2: Pendiente (Hace 2 días)
    req_pending = BenefitRequest(
        request_code="BE002", employee_id=emp_analista.id, employee_position_id=ep_analista.id,
        request_type_id=brt_alta.id, request_date=date.today() - timedelta(days=2),
        grant_reason_id=bgr_rendimiento.id, justification="Excelente gestión en campaña de reclutamiento",
        requester_id=emp_director.id, requester_position_id=ep_director.id,
        status="Pendiente", benefit_status="Pendiente", created_at=datetime.now() - timedelta(days=2)
    )
    session.add_all([req_pending])
    await session.flush()
    
    item_pending = BenefitRequestItem(
        benefit_request_id=req_pending.id, benefit_type_id=bt_seguro.id, benefit_subtype_id=bs_seguro.id,
        currency_id=cur_pyg.id, approved_amount=0.0, validity_start_date=date.today() + timedelta(days=5),
        benefit_modality_id=bm_fijo.id, benefit_frequency_id=bf_mensual.id, description_notes="Ampliación seguro médico"
    )
    session.add_all([item_pending])
    await session.flush()

    # ---------------------------------------------------------
    # 7. Sanciones Disciplinarias y Reconocimientos
    # ---------------------------------------------------------
    print("   -> Creando amonestaciones y reconocimientos...")
    
    sanc_dev = Sanction(
        employee_id=emp_dev.id, type=SanctionType.VERBAL, date=date.today() - timedelta(days=45),
        reason="Amonestación verbal por retrasos en dailies obligatorias de tecnología.",
        sent_to_ministry=False, notes="El colaborador asume el compromiso de conectarse a tiempo."
    )
    recog_director = Recognition(
        employee_id=emp_director.id, type=RecognitionType.EXCELLENCE, date=date.today() - timedelta(days=15),
        title="Líder Sobresaliente UP 2026", description="Premio corporativo anual de reconocimiento a la gestión humana asertiva."
    )
    session.add_all([sanc_dev, recog_director])
    await session.flush()

    # ---------------------------------------------------------
    # 8. Módulo de Capacitaciones (Trainings)
    # ---------------------------------------------------------
    print("   -> Creando capacitadores, cursos e inscripciones...")
    
    prov_tech = TrainingProvider(
        business_name="Tech Academy S.A.", ruc="80099999-9", phone="021600700",
        email="contacto@techacademy.com.py", contact_person="Ing. Robert Downey", address="Av. Mcal. López 789"
    )
    session.add_all([prov_tech])
    await session.flush()
    
    course_fastapi = Training(
        name="FastAPI Avanzado y SQL Server", description="Profundización de microservicios, seguridad OAuth2 e integraciones asíncronas",
        type=TrainingType.EXTERNAL, provider_id=prov_tech.id, cost_per_person=1500000.0, company_cost=6000000.0,
        start_date=date.today() - timedelta(days=10), end_date=date.today() + timedelta(days=15), status=TrainingStatus.IN_PROGRESS
    )
    course_liderazgo = Training(
        name="Habilidades Blandas en Talento Humano", description="Empatía, gestión de crisis internas y comunicación con sindicatos",
        type=TrainingType.INTERNAL, internal_instructor_id=emp_director.id, cost_per_person=0.0, company_cost=100000.0,
        start_date=date.today() + timedelta(days=20), end_date=date.today() + timedelta(days=25), status=TrainingStatus.PLANNED
    )
    session.add_all([course_fastapi, course_liderazgo])
    await session.flush()
    
    enroll_dev = TrainingEnrollment(
        training_id=course_fastapi.id, employee_id=emp_dev.id, status=EnrollmentStatus.ENROLLED,
        invitation_sent_at=date.today() - timedelta(days=12)
    )
    enroll_analista = TrainingEnrollment(
        training_id=course_liderazgo.id, employee_id=emp_analista.id, status=EnrollmentStatus.ENROLLED,
        invitation_sent_at=date.today() - timedelta(days=2)
    )
    session.add_all([enroll_dev, enroll_analista])
    await session.flush()

    # ---------------------------------------------------------
    # 9. Calendario y Eventos de Integración
    # ---------------------------------------------------------
    print("   -> Creando eventos en el calendario institucional...")
    
    et_social = await get_or_create(CalendarEventType, "name", "Social", color="#3B82F6", description="Cumpleaños, aniversarios e integración")
    et_capacita = await get_or_create(CalendarEventType, "name", "Capacitación", color="#10B981", description="Cursos de inducción obligatorios")
    
    ev_social = CalendarEvent(
        title="Almuerzo de Fin de Año UP", description="Festejo anual de cierre de periodo lectivo y administrativo.",
        date=date.today() - timedelta(days=15), event_type_id=et_social.id, is_enrollable=True
    )
    ev_capacita = CalendarEvent(
        title="Taller de Inducción de Seguridad", description="Seguridad de la información y protección de legajos privados.",
        date=date.today() + timedelta(days=10), event_type_id=et_capacita.id, is_enrollable=True
    )
    session.add_all([ev_social, ev_capacita])
    await session.flush()

    # ---------------------------------------------------------
    # 10. Reclutamiento y Vacantes Activas
    # ---------------------------------------------------------
    print("   -> Creando procesos de selección y vacantes activas...")
    
    hr_reemplazo = await get_or_create(HiringReason, "name", "Reemplazo de Personal")
    hr_aumento = await get_or_create(HiringReason, "name", "Aumento de Estructura")
    
    proc_tech = RecruitmentProcess(
        name="Proceso de Selección de Tecnología", description="Flujo estándar con filtros curriculares y técnicos"
    )
    session.add_all([proc_tech])
    await session.flush()
    
    stage_cv = ProcessStage(process_id=proc_tech.id, name="Filtro Curricular", sla_days=3, owner=StageOwner.RECRUITER, order_index=1)
    stage_tech = ProcessStage(process_id=proc_tech.id, name="Prueba Técnica", sla_days=5, owner=StageOwner.AREA, order_index=2)
    stage_ent = ProcessStage(process_id=proc_tech.id, name="Entrevista Final", sla_days=3, owner=StageOwner.RECRUITER, order_index=3)
    session.add_all([stage_cv, stage_tech, stage_ent])
    await session.flush()
    
    vac_dev = Vacancy(
        title="Desarrollador Fullstack Junior", description="Buscamos un desarrollador junior enfocado en Python, FastAPI y VueJS",
        status=ProcessStatus.OPEN, vacancy_type=VacancyType.EXTERNAL, is_headcount_increase=False,
        start_date=date.today() - timedelta(days=5), area_id=area_ti.id, position_id=pos_dev_sr.id,
        requester_id=user_gerente.id, process_id=proc_tech.id, hiring_reason_id=hr_reemplazo.id,
        recruiter_id=user_director.id, created_at=datetime.now() - timedelta(days=5)
    )
    session.add_all([vac_dev])
    await session.flush()
    
    await session.commit()
    print(f"🎉 ¡Tenant '{tenant_name}' poblado con éxito con datos semilla completos!")

async def main():
    parser = argparse.ArgumentParser(description="Script para manejar la seed data de un inquilino (Tenant)")
    parser.add_argument("--subdomain", type=str, default="cliente1", help="Subdominio del tenant a poblar/limpiar (ej: cliente1)")
    parser.add_argument("--tenant-name", type=str, default=None, help="Nombre opcional del tenant si se va a crear uno nuevo")
    parser.add_argument("--action", type=str, required=True, choices=["seed", "clean"], help="Acción a realizar: 'seed' para cargar datos o 'clean' para borrarlos")
    
    args = parser.parse_args()
    
    async with AsyncSessionLocal() as session:
        # 1. Buscar el Tenant en la base de datos (esquema public)
        print(f"🔍 Buscando Tenant con subdominio: '{args.subdomain}'...")
        tenant = await get_tenant_by_subdomain(session, args.subdomain)
        
        if not tenant:
            if args.action == "clean":
                print(f"❌ Error: El Tenant '{args.subdomain}' no existe, no se puede limpiar nada.")
                sys.exit(1)
            
            # Si se va a poblar y no existe, se puede autocrear
            name = args.tenant_name if args.tenant_name else f"Inquilino {args.subdomain.upper()}"
            print(f"⚠️ El Tenant con subdominio '{args.subdomain}' no existe. Creando tenant '{name}'...")
            try:
                tenant = await create_tenant(session, name=name, subdomain=args.subdomain)
                print(f"✅ Tenant '{name}' creado con éxito.")
            except Exception as e:
                print(f"❌ Error creando el Tenant de forma automática: {e}")
                sys.exit(1)
                
        # Extraer variables primitivas antes de transacciones de base de datos
        schema_name = tenant.schema_name
        tenant_name = tenant.name

        # 2. Ejecutar la Acción Solicitada
        if args.action == "clean":
            await clean_tenant_data(session, schema_name)
        elif args.action == "seed":
            # Asegurar que el esquema se limpie primero para evitar duplicados
            await clean_tenant_data(session, schema_name)
            await seed_tenant_data(session, schema_name, tenant_name)

if __name__ == "__main__":
    asyncio.run(main())
