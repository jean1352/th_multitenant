#!/usr/bin/env python3
"""
Script de carga y limpieza de datos semilla (Seed Data) para un Tenant específico.
Permite poblar y limpiar bases de datos multi-tenant de forma segura.
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
    Limpia todas las tablas de datos dentro del esquema del Tenant usando TRUNCATE CASCADE.
    De esta forma se eliminan los datos de prueba sin alterar el esquema público.
    """
    print(f"🧹 Limpiando todos los datos existentes en el esquema: '{schema_name}'...")
    
    # Listado de tablas del inquilino en orden seguro
    tables = [
        "emergency_contacts", "event_enrollments", "calendar_events", "calendar_event_types",
        "training_enrollments", "trainings", "training_providers", "employee_dietary_association",
        "dietary_restrictions", "sanctions", "recognitions", "employee_benefits",
        "benefit_request_items", "benefit_requests", "benefit_types", "benefit_request_types",
        "benefit_subtypes", "benefit_grant_reasons", "authorization_levels", "benefit_modalities",
        "benefit_frequencies", "users", "employees", "employee_positions", "positions",
        "areas", "sedes", "companies", "contract_types", "working_day_types", "salary_types",
        "currencies", "payment_methods", "banks", "recruitment_processes", "hiring_reasons",
        "stage_edit_reasons", "process_stages", "vacancies", "vacancy_stages"
    ]
    
    for table in tables:
        try:
            # PostgreSQL Truncate Cascade elimina de forma segura incluyendo foreign keys vinculadas
            await session.execute(text(f'TRUNCATE TABLE "{schema_name}"."{table}" CASCADE;'))
        except Exception as e:
            # Omitir de forma segura si la tabla aún no existe o no tiene registros
            await session.rollback()
            continue
            
    await session.commit()
    print("✅ Esquema de base de datos limpio con éxito.")

async def seed_tenant_data(session: AsyncSession, tenant: Tenant):
    """
    Puebla el esquema del Tenant con datos de muestra realistas con distintas marcas temporales.
    """
    schema_name = tenant.schema_name
    print(f"🌱 Población de datos iniciada en el esquema: '{schema_name}'...")
    
    # Establecer la búsqueda de esquema para la sesión actual
    await session.execute(text(f'SET search_path TO "{schema_name}", public'))
    
    # ---------------------------------------------------------
    # 1. Catálogos Generales y Configuración Básica
    # ---------------------------------------------------------
    print("   -> Creando catálogos generales...")
    
    # Monedas
    cur_pyg = Currency(name="Guaraníes", symbol="PYG", description="Moneda local de Paraguay")
    cur_usd = Currency(name="Dólares", symbol="USD", description="Dólares estadounidenses")
    session.add_all([cur_pyg, cur_usd])
    await session.flush()
    
    # Tipos de Contrato
    ct_indef = ContractType(name="Indefinido", description="Contrato de duración indefinida")
    ct_temp = ContractType(name="Plazo Fijo", description="Contrato por un plazo determinado")
    session.add_all([ct_indef, ct_temp])
    await session.flush()
    
    # Tipos de Jornada
    wdt_full = WorkingDayType(name="Tiempo Completo", description="Jornada completa tradicional")
    wdt_remote = WorkingDayType(name="Remoto", description="Trabajo 100% a distancia")
    session.add_all([wdt_full, wdt_remote])
    await session.flush()
    
    # Tipos de Salario
    st_fijo = SalaryType(name="Fijo", description="Salario mensual garantizado")
    session.add_all([st_fijo])
    await session.flush()
    
    # Bancos y Métodos de Pago
    bank_itau = Bank(name="Banco Itaú Paraguay")
    pm_transfer = PaymentMethod(name="Transferencia Bancaria")
    session.add_all([bank_itau, pm_transfer])
    await session.flush()
    
    # Empresas (Razón Social)
    comp_up = Company(name="Universidad del Pacífico S.A.", tax_id="80170151-1")
    comp_serv = Company(name="Servicios Educativos UP", tax_id="80170152-2")
    session.add_all([comp_up, comp_serv])
    await session.flush()

    # ---------------------------------------------------------
    # 2. Sedes, Áreas y Estructura Organizativa
    # ---------------------------------------------------------
    print("   -> Creando estructura organizativa (Sedes, Áreas, Cargos)...")
    
    sede_central = Sede(name="Campus Central", address="Av. España 123, Asunción")
    sede_norte = Sede(name="Sede Miraflores", address="Av. Aviadores del Chaco 456, Asunción")
    session.add_all([sede_central, sede_norte])
    await session.flush()
    
    area_th = Area(name="Talento Humano", responsible_email="th@universidad.edu.py",  sede=sede_central)
    area_ti = Area(name="Tecnología de la Información", responsible_email="ti@universidad.edu.py", sede=sede_central)
    area_ops = Area(name="Operaciones", responsible_email="ops@universidad.edu.py",  sede=sede_norte)
    session.add_all([area_th, area_ti, area_ops])
    await session.flush()
    
    # Jerarquía de Cargos
    pos_director_th = Position(name="Director de Talento Humano", area=area_th, is_leader=True)
    pos_gerente_ti = Position(name="Gerente de TI", area=area_ti, is_leader=True)
    session.add_all([pos_director_th, pos_gerente_ti])
    await session.flush()
    
    pos_analista_th = Position(name="Analista de Talento Humano", area=area_th, is_leader=False, parent_id=pos_director_th.id)
    pos_dev_sr = Position(name="Desarrollador Senior", area=area_ti, is_leader=False, parent_id=pos_gerente_ti.id)
    session.add_all([pos_analista_th, pos_dev_sr])
    await session.flush()

    # ---------------------------------------------------------
    # Restricciones Alimenticias (Comedor) - Creadas temprano para asignación segura
    # ---------------------------------------------------------
    dr_gluten = DietaryRestriction(name="Celíaco", description="Intolerancia médica al gluten")
    dr_veg = DietaryRestriction(name="Vegetariano", description="Persona con alimentación basada en plantas")
    dr_lactose = DietaryRestriction(name="Intolerante a la Lactosa", description="Intolerancia a productos lácteos")
    session.add_all([dr_gluten, dr_veg, dr_lactose])
    await session.flush()

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
    brt_alta = BenefitRequestType(name="Alta")
    brt_mod = BenefitRequestType(name="Modificación")
    session.add_all([brt_alta, brt_mod])
    await session.flush()
    
    bs_seguro = BenefitSubtype(name="Seguro Médico")
    bs_vale = BenefitSubtype(name="Vales de Combustible")
    session.add_all([bs_seguro, bs_vale])
    await session.flush()
    
    bgr_politica = BenefitGrantReason(name="Por Política")
    bgr_rendimiento = BenefitGrantReason(name="Por Rendimiento")
    session.add_all([bgr_politica, bgr_rendimiento])
    await session.flush()
    
    al_gerencia = AuthorizationLevel(name="Gerencia de Personas")
    al_rector = AuthorizationLevel(name="Rectorado")
    session.add_all([al_gerencia, al_rector])
    await session.flush()
    
    bm_fijo = BenefitModality(name="Fijo")
    bm_variable = BenefitModality(name="Variable")
    session.add_all([bm_fijo, bm_variable])
    await session.flush()
    
    bf_mensual = BenefitFrequency(name="Mensual")
    bf_unico = BenefitFrequency(name="Único")
    session.add_all([bf_mensual, bf_unico])
    await session.flush()
    
    # Tipos de Beneficios
    bt_seguro = BenefitType(name="Seguro de Salud Premium", description="Cobertura prepaga familiar para cargos jerárquicos")
    bt_combustible = BenefitType(name="Ayuda de Combustible", description="Monto mensual para movilidad y traslados")
    session.add_all([bt_seguro, bt_combustible])
    await session.flush()
    
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
        grant_reason_id=bgr_politica.id, justification="Beneficio por modalidad remota distante",
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
        email="contacto@techacademy.com.py", contact_person="Ing. Roberto Downey", address="Av. Mcal. López 789"
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
    
    et_social = CalendarEventType(name="Social", color="#3B82F6", description="Cumpleaños, aniversarios e integración")
    et_capacita = CalendarEventType(name="Capacitación", color="#10B981", description="Cursos de inducción obligatorios")
    session.add_all([et_social, et_capacita])
    await session.flush()
    
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
    
    hr_reemplazo = HiringReason(name="Reemplazo de Personal")
    hr_aumento = HiringReason(name="Aumento de Estructura")
    session.add_all([hr_reemplazo, hr_aumento])
    await session.flush()
    
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
    print(f"🎉 ¡Tenant '{tenant.name}' poblado con éxito con datos semilla completos!")

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
                
        # 2. Ejecutar la Acción Solicitada
        if args.action == "clean":
            await clean_tenant_data(session, tenant.schema_name)
        elif args.action == "seed":
            # Asegurar que el esquema se limpie primero para evitar duplicados
            await clean_tenant_data(session, tenant.schema_name)
            await seed_tenant_data(session, tenant)

if __name__ == "__main__":
    asyncio.run(main())
