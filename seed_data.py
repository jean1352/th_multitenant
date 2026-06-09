#!/usr/bin/env python3
"""
Script de carga y limpieza quirúrgica de datos semilla (Seed Data) para un Tenant específico.
Permite poblar y limpiar bases de datos de demostración a escala empresarial sin afectar usuarios reales.
"""

import os
import sys
import argparse
import asyncio
import random
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
    RecruitmentProcess, HiringReason, ProcessStage, Vacancy, VacancyStage, ProcessStatus, StageOwner, VacancyType, RecruitmentAudit
)
from app.modules.trainings.models import (
    TrainingProvider, Training, TrainingEnrollment, TrainingType, TrainingStatus, EnrollmentStatus
)

async def clean_tenant_data(session: AsyncSession, schema_name: str):
    """
    Limpia de forma quirúrgica únicamente los datos de prueba (demo) del esquema del tenant,
    sin afectar a los usuarios, administradores o datos creados de manera real por el cliente.
    """
    print(f"🧹 Iniciando limpieza quirúrgica de datos de prueba en esquema: '{schema_name}'...")
    
    # Asegurar el search_path en la sesión
    await session.execute(text(f'SET search_path TO "{schema_name}", public'))
    
    # 1. Borrar auditoría de reclutamiento demo
    try:
        await session.execute(text(
            "DELETE FROM recruitment_audits WHERE vacancy_id IN "
            "(SELECT id FROM vacancies WHERE title = 'Desarrollador Fullstack Junior' OR title LIKE 'Convocatoria %')"
        ))
    except Exception:
        await session.rollback()

    # 2. Borrar vacantes demo (deben ir primero ya que referencian a recruiters en la tabla users)
    try:
        await session.execute(text(
            "DELETE FROM vacancies WHERE title = 'Desarrollador Fullstack Junior' OR title LIKE 'Convocatoria %'"
        ))
    except Exception:
        await session.rollback()
        
    # 3. Borrar procesos de selección demo
    try:
        # Borrar primero las etapas del proceso de selección demo
        await session.execute(text(
            "DELETE FROM process_stages WHERE process_id IN "
            "(SELECT id FROM recruitment_processes WHERE name LIKE '%Proceso de Selección%')"
        ))
        # Borrar el proceso de selección demo
        await session.execute(text(
            "DELETE FROM recruitment_processes WHERE name LIKE '%Proceso de Selección%'"
        ))
    except Exception:
        await session.rollback()

    # 4. Borrar capacitaciones demo e inscripciones (deben ir antes de borrar los colaboradores ya que uno de ellos es instructor interno)
    try:
        # Borrar inscripciones de capacitaciones demo
        await session.execute(text(
            "DELETE FROM training_enrollments WHERE training_id IN "
            "(SELECT id FROM trainings WHERE name IN ('FastAPI Avanzado y SQL Server', 'Habilidades Blandas en Talento Humano') OR name LIKE 'Curso de %')"
        ))
        # Borrar capacitaciones
        await session.execute(text(
            "DELETE FROM trainings WHERE name IN ('FastAPI Avanzado y SQL Server', 'Habilidades Blandas en Talento Humano') OR name LIKE 'Curso de %'"
        ))
        # Borrar proveedores demo
        await session.execute(text(
            "DELETE FROM training_providers WHERE ruc IN ('80099999-9', '80011111-1', '80022222-2')"
        ))
    except Exception:
        await session.rollback()

    # 5. Borrar en cascada todos los registros de los colaboradores demo mediante subconsultas puras SQL
    # De esta manera evitamos problemas de mapeo o expansión de listas en SQLAlchemy, y garantizamos que
    # si el cliente creó usuarios reales o administradores en su cuenta, estos queden 100% INTACTOS.
    try:
        # Contactos de emergencia
        await session.execute(text(
            "DELETE FROM emergency_contacts WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Calendario e inscripciones
        await session.execute(text(
            "DELETE FROM event_enrollments WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Capacitaciones e inscripciones generales
        await session.execute(text(
            "DELETE FROM training_enrollments WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Asociación de comedor / dietario
        await session.execute(text(
            "DELETE FROM employee_dietary_association WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Sanciones
        await session.execute(text(
            "DELETE FROM sanctions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Reconocimientos
        await session.execute(text(
            "DELETE FROM recognitions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Solicitudes de Beneficios (Items y Cabecera)
        await session.execute(text(
            "DELETE FROM benefit_request_items WHERE benefit_request_id IN "
            "(SELECT id FROM benefit_requests WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%'))"
        ))
        await session.execute(text(
            "DELETE FROM benefit_requests WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Beneficios activos asignados
        await session.execute(text(
            "DELETE FROM employee_benefits WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Cargos históricos / Contratos
        await session.execute(text(
            "DELETE FROM employee_positions WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%')"
        ))
        
        # Usuarios de acceso demo (solamente borra las 4 cuentas fijas demo y cuentas asociadas a empleados demo,
        # protegiendo por completo a los administradores reales y usuarios creados legítimamente por el cliente)
        await session.execute(text(
            "DELETE FROM users WHERE employee_id IN "
            "(SELECT id FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%') "
            "OR email IN ('maria.lopez@sectoruno.com.py', 'ana.benitez@sectoruno.com.py', "
            "'carlos.gomez@sectoruno.com.py', 'diego.torres@sectoruno.com.py')"
        ))
        
        # Finalmente, los Colaboradores demo
        await session.execute(text(
            "DELETE FROM employees WHERE document_id IN ('1234567', '2345678', '3456789', '4567890') OR document_id LIKE 'DEMO-%'"
        ))
    except Exception as e:
        await session.rollback()
        print(f"⚠️ Error borrando relaciones de empleados: {e}")
            
    # 6. Borrar eventos de calendario demo
    try:
        await session.execute(text(
            "DELETE FROM calendar_events WHERE title IN ('Almuerzo de Fin de Año', 'Taller de Inducción de Seguridad') OR title LIKE 'Integración %'"
        ))
    except Exception:
        await session.rollback()

    await session.commit()
    print("✅ Limpieza quirúrgica de datos demo completada con éxito.")

async def seed_tenant_data(session: AsyncSession, schema_name: str, tenant_name: str):
    """
    Puebla el esquema del Tenant con un dataset demo masivo (escala de 250+ colaboradores y reclutamientos),
    con marcas temporales variables realistas de años anteriores o del año actual (nunca a futuro).
    """
    print(f"🌱 Población masiva de datos iniciada en el esquema: '{schema_name}'...")
    
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

    # Nombres de muestra para generar datos masivos
    nombres_f = ["María", "Ana", "Laura", "Patricia", "Sofía", "Gabriela", "Elena", "Sandra", "Beatriz", "Clara", "Andrea", "Camila", "Lucía", "Natalia", "Isabel"]
    nombres_m = ["Juan", "Carlos", "Carlos Gómez", "Diego", "Carlos", "Roberto", "Jorge", "Guillermo", "David", "Luis", "José", "Alejandro", "Fernando", "Ricardo", "Andrés"]
    apellidos = ["Pérez", "Gómez", "Rodríguez", "González", "Torres", "Benítez", "López", "Giménez", "Martínez", "Cardozo", "Sánchez", "Ortiz", "Díaz", "Silva", "Vera", "Ríos", "Acuña", "Duarte", "Cáceres", "Gamarra"]

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
    ct_serv = await get_or_create(ContractType, "name", "Servicios Profesionales", description="Prestación de servicios de consultoría")
    
    # Tipos de Jornada
    wdt_full = await get_or_create(WorkingDayType, "name", "Tiempo Completo", description="Jornada completa tradicional de 44 horas semanales")
    wdt_remote = await get_or_create(WorkingDayType, "name", "Remoto", description="Trabajo 100% virtual a distancia")
    wdt_hybrid = await get_or_create(WorkingDayType, "name", "Híbrido", description="Formato mixto presencial y remoto")
    
    # Tipos de Salario
    st_fijo = await get_or_create(SalaryType, "name", "Fijo", description="Salario mensual estándar")
    
    # Bancos y Métodos de Pago
    bank_itau = await get_or_create(Bank, "name", "Banco Itaú Paraguay")
    bank_conti = await get_or_create(Bank, "name", "Banco Continental")
    pm_transfer = await get_or_create(PaymentMethod, "name", "Transferencia Bancaria")
    
    # Empresas (Razón Social)
    comp_main = await get_or_create(Company, "name", "Sector Uno S.A.", tax_id="80170001-1")
    comp_serv = await get_or_create(Company, "name", "Servicios Sector Uno", tax_id="80170002-2")

    # ---------------------------------------------------------
    # 2. Sedes, Áreas y Estructura Organizativa
    # ---------------------------------------------------------
    print("   -> Creando sedes físicas y áreas de trabajo...")
    
    sede_central = await get_or_create(Sede, "name", "Sede Central (Asunción)", address="Av. Aviadores del Chaco 1129, Asunción")
    sede_cde = await get_or_create(Sede, "name", "Sede Ciudad del Este", address="Av. Mcal. Estigarribia 450, Ciudad del Este")
    sede_enc = await get_or_create(Sede, "name", "Sede Encarnación", address="Ruta 1 Km 2, Encarnación")
    
    # 6 Áreas de trabajo realistas
    area_th = await get_or_create(Area, "name", "Talento Humano", responsible_email="th@sectoruno.com.py", sede_id=sede_central.id)
    area_ti = await get_or_create(Area, "name", "Tecnología de la Información", responsible_email="ti@sectoruno.com.py", sede_id=sede_central.id)
    area_ops = await get_or_create(Area, "name", "Operaciones y Logística", responsible_email="ops@sectoruno.com.py", sede_id=sede_cde.id)
    area_fin = await get_or_create(Area, "name", "Administración y Finanzas", responsible_email="finanzas@sectoruno.com.py", sede_id=sede_central.id)
    area_cs = await get_or_create(Area, "name", "Atención al Cliente", responsible_email="soporte@sectoruno.com.py", sede_id=sede_enc.id)
    area_leg = await get_or_create(Area, "name", "Legales y Cumplimiento", responsible_email="legales@sectoruno.com.py", sede_id=sede_central.id)
    
    print("   -> Creando jerarquía de cargos...")
    # Cargos Líderes
    pos_dir_th = await get_or_create(Position, "name", "Director de Talento Humano", area_id=area_th.id, is_leader=True)
    pos_ger_ti = await get_or_create(Position, "name", "Gerente de TI", area_id=area_ti.id, is_leader=True)
    pos_ger_ops = await get_or_create(Position, "name", "Gerente de Operaciones", area_id=area_ops.id, is_leader=True)
    pos_ger_fin = await get_or_create(Position, "name", "Director de Finanzas", area_id=area_fin.id, is_leader=True)
    
    # Cargos Especialistas (Línea de reporte)
    pos_analista_th = await get_or_create(Position, "name", "Analista de Talento Humano", area_id=area_th.id, is_leader=False, parent_id=pos_dir_th.id)
    pos_dev_sr = await get_or_create(Position, "name", "Desarrollador Senior", area_id=area_ti.id, is_leader=False, parent_id=pos_ger_ti.id)
    pos_dev_jr = await get_or_create(Position, "name", "Desarrollador Junior", area_id=area_ti.id, is_leader=False, parent_id=pos_ger_ti.id)
    pos_analista_ops = await get_or_create(Position, "name", "Analista de Logística", area_id=area_ops.id, is_leader=False, parent_id=pos_ger_ops.id)
    pos_analista_fin = await get_or_create(Position, "name", "Especialista en Tesorería", area_id=area_fin.id, is_leader=False, parent_id=pos_ger_fin.id)
    pos_agent_cs = await get_or_create(Position, "name", "Agente de Soporte", area_id=area_cs.id, is_leader=False)
    pos_abogado = await get_or_create(Position, "name", "Asesor Jurídico", area_id=area_leg.id, is_leader=False)

    # Restricciones Alimenticias (Comedor)
    dr_gluten = await get_or_create(DietaryRestriction, "name", "Celíaco", description="Intolerancia médica al gluten")
    dr_veg = await get_or_create(DietaryRestriction, "name", "Vegetariano", description="Persona con alimentación basada en plantas")
    dr_lactose = await get_or_create(DietaryRestriction, "name", "Intolerante a la Lactosa", description="Intolerancia a productos lácteos")

    # ---------------------------------------------------------
    # 3. Datos Masivos de Colaboradores (250 Registros)
    # ---------------------------------------------------------
    print("   -> Generando un lote masivo de 250 colaboradores con contratos históricos y actuales...")
    
    # 4 Líderes fijos iniciales (para mantener accesos admin)
    emp_director = Employee(
        first_name="María", last_name="López", full_name="María López", document_id="1234567",
        position_id=pos_dir_th.id, gender="Femenino", marital_status="Soltero", nationality="Paraguaya",
        personal_email="maria.lopez@gmail.com", institutional_email="maria.lopez@sectoruno.com.py",
        phone="0981111222", birthday=date(1985, 5, 12), employment_status=EmploymentStatus.ACTIVE, company_id=comp_main.id,
        dietary_restrictions=[dr_lactose]
    )
    emp_analista = Employee(
        first_name="Ana", last_name="Benítez", full_name="Ana Benítez", document_id="2345678",
        position_id=pos_analista_th.id, gender="Femenino", marital_status="Soltero", nationality="Paraguaya",
        personal_email="ana.benitez@gmail.com", institutional_email="ana.benitez@sectoruno.com.py",
        phone="0982222333", birthday=date(1992, 8, 20), employment_status=EmploymentStatus.ACTIVE, company_id=comp_main.id
    )
    emp_gerente = Employee(
        first_name="Carlos", last_name="Gómez", full_name="Carlos Gómez", document_id="3456789",
        position_id=pos_ger_ti.id, gender="Masculino", marital_status="Casado", nationality="Paraguaya",
        personal_email="carlos.gomez@gmail.com", institutional_email="carlos.gomez@sectoruno.com.py",
        phone="0983333444", birthday=date(1980, 11, 30), employment_status=EmploymentStatus.ACTIVE, company_id=comp_main.id
    )
    emp_dev = Employee(
        first_name="Diego", last_name="Torres", full_name="Diego Torres", document_id="4567890",
        position_id=pos_dev_sr.id, gender="Masculino", marital_status="Casado", nationality="Paraguaya",
        personal_email="diego.torres@gmail.com", institutional_email="diego.torres@sectoruno.com.py",
        phone="0984444555", birthday=date(1990, 3, 15), employment_status=EmploymentStatus.ACTIVE, company_id=comp_serv.id,
        dietary_restrictions=[dr_veg]
    )
    
    session.add_all([emp_director, emp_analista, emp_gerente, emp_dev])
    await session.flush()

    # Contratos fijos iniciales
    ep_director = EmployeePosition(
        employee_id=emp_director.id, position_id=pos_dir_th.id, company_id=comp_main.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=14000000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes",
        start_date=date(2021, 6, 1)
    )
    ep_analista = EmployeePosition(
        employee_id=emp_analista.id, position_id=pos_analista_th.id, company_id=comp_main.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=6500000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes",
        start_date=date(2023, 2, 1)
    )
    ep_gerente = EmployeePosition(
        employee_id=emp_gerente.id, position_id=pos_ger_ti.id, company_id=comp_main.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=18000000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes",
        start_date=date(2020, 10, 1)
    )
    # Ejemplo de CARRERA HISTÓRICA para el Desarrollador Diego Torres (2 Contratos)
    # Contrato Pasado (Cerrado en 2024)
    ep_dev_old = EmployeePosition(
        employee_id=emp_dev.id, position_id=pos_dev_jr.id, company_id=comp_serv.id,
        contract_type_id=ct_temp.id, working_day_type_id=wdt_full.id, salary_type_id=st_fijo.id,
        base_salary=4500000.0, currency_id=cur_pyg.id, work_schedule="08:00 - 17:00", work_days="Lunes a Viernes",
        start_date=date(2023, 1, 15), end_date=date(2024, 7, 31)
    )
    # Contrato Actual (Activo)
    ep_dev = EmployeePosition(
        employee_id=emp_dev.id, position_id=pos_dev_sr.id, company_id=comp_serv.id,
        contract_type_id=ct_indef.id, working_day_type_id=wdt_remote.id, salary_type_id=st_fijo.id,
        base_salary=9500000.0, currency_id=cur_pyg.id, work_schedule="09:00 - 18:00", work_days="Lunes a Viernes",
        start_date=date(2024, 8, 1)
    )
    
    session.add_all([ep_director, ep_analista, ep_gerente, ep_dev_old, ep_dev])
    await session.flush()

    # Generación masiva mediante bucle
    posiciones = [pos_analista_th, pos_dev_sr, pos_dev_jr, pos_analista_ops, pos_analista_fin, pos_agent_cs, pos_abogado]
    empresas = [comp_main, comp_serv]
    jornadas = [wdt_full, wdt_remote, wdt_hybrid]
    contratos = [ct_indef, ct_temp]
    
    bulk_employees = []
    bulk_positions = []
    
    for i in range(250):
        # Datos del Colaborador
        gender = random.choice(["Masculino", "Femenino"])
        first_name = random.choice(nombres_f if gender == "Femenino" else nombres_m)
        last_name = f"{random.choice(apellidos)} {random.choice(apellidos)}"
        full_name = f"{first_name} {last_name}"
        doc_id = f"DEMO-{random.randint(1000000, 8000000)}"
        email_prefix = f"{first_name.lower()}.{last_name.split()[0].lower()}{random.randint(1,99)}"
        personal_email = f"{email_prefix}@gmail.com"
        inst_email = f"{email_prefix}@sectoruno.com.py"
        phone = f"09{random.randint(71, 99)}{random.randint(100000, 999999)}"
        
        # Fecha de Nacimiento (Edad 20-60)
        birthday = date.today() - timedelta(days=random.randint(7300, 21900))
        
        # Fecha de contratación (Últimos 4 años, nunca a futuro)
        hire_date = date.today() - timedelta(days=random.randint(15, 1460))
        
        pos = random.choice(posiciones)
        emp = Employee(
            first_name=first_name, last_name=last_name, full_name=full_name, document_id=doc_id,
            position_id=pos.id, gender=gender, marital_status=random.choice(["Soltero", "Casado", "Divorciado"]),
            nationality="Paraguaya", personal_email=personal_email, institutional_email=inst_email,
            phone=phone, birthday=birthday, employment_status=EmploymentStatus.ACTIVE, company_id=random.choice(empresas).id,
            # Añadir restricciones alimentarias aleatoriamente (15% de probabilidad)
            dietary_restrictions=[random.choice([dr_gluten, dr_veg, dr_lactose])] if random.random() < 0.15 else []
        )
        session.add(emp)
        bulk_employees.append(emp)
        
    await session.flush()
    
    # Crear asignación EmployeePosition para todos los colaboradores masivos
    for i, emp in enumerate(bulk_employees):
        # Determinar el nombre del cargo de forma segura usando la lista local
        pos = next((p for p in posiciones if p.id == emp.position_id), None)
        pos_name = pos.name if pos else ""
        
        # Determinar un salario coherente con el cargo
        if "Senior" in pos_name:
            salario = random.randint(8500000, 13000000)
        elif "Director" in pos_name or "Gerente" in pos_name:
            salario = random.randint(13500000, 18000000)
        elif "Junior" in pos_name or "Agente" in pos_name:
            salario = random.randint(3500000, 4800000)
        else:
            salario = random.randint(5000000, 7800000)
            
        ep = EmployeePosition(
            employee_id=emp.id, position_id=emp.position_id, company_id=emp.company_id,
            contract_type_id=random.choice(contratos).id, working_day_type_id=random.choice(jornadas).id,
            salary_type_id=st_fijo.id, base_salary=float(salario), currency_id=cur_pyg.id,
            work_schedule="08:00 - 17:00" if random.random() < 0.7 else "09:00 - 18:00",
            work_days="Lunes a Viernes", start_date=date.today() - timedelta(days=random.randint(100, 1000))
        )
        session.add(ep)
        
    await session.flush()

    # ---------------------------------------------------------
    # 4. Usuarios de Acceso al Sistema (Auth)
    # ---------------------------------------------------------
    print("   -> Creando credenciales para personal directivo (Auth)...")
    
    hashed_pwd = get_password_hash("password123")
    user_director = User(
        email="maria.lopez@sectoruno.com.py", full_name="María López", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.TH, employee_id=emp_director.id, sede_id=sede_central.id, area_id=area_th.id
    )
    user_analista = User(
        email="ana.benitez@sectoruno.com.py", full_name="Ana Benítez", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.EMPLOYEE, employee_id=emp_analista.id, sede_id=sede_central.id, area_id=area_th.id
    )
    user_gerente = User(
        email="carlos.gomez@sectoruno.com.py", full_name="Carlos Gómez", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.MANAGER, employee_id=emp_gerente.id, sede_id=sede_central.id, area_id=area_ti.id
    )
    user_dev = User(
        email="diego.torres@sectoruno.com.py", full_name="Diego Torres", hashed_password=hashed_pwd,
        is_active=True, role=UserRole.EMPLOYEE, employee_id=emp_dev.id, sede_id=sede_cde.id, area_id=area_ti.id
    )
    session.add_all([user_director, user_analista, user_gerente, user_dev])
    await session.flush()

    # ---------------------------------------------------------
    # 5. Beneficios e Historial Masivo (60 Solicitudes con Tiempos Variables)
    # ---------------------------------------------------------
    print("   -> Creando catálogo de beneficios y 60 solicitudes históricas...")
    
    # Catálogos
    brt_alta = await get_or_create(BenefitRequestType, "name", "Alta")
    brt_mod = await get_or_create(BenefitRequestType, "name", "Modificación")
    
    bs_seguro = await get_or_create(BenefitSubtype, "name", "Seguro Médico")
    bs_vale = await get_or_create(BenefitSubtype, "name", "Vales de Combustible")
    bs_estu = await get_or_create(BenefitSubtype, "name", "Ayuda de Estudios")
    
    bgr_politica = await get_or_create(BenefitGrantReason, "name", "Por Política")
    bgr_rendimiento = await get_or_create(BenefitGrantReason, "name", "Por Rendimiento")
    bgr_social = await get_or_create(BenefitGrantReason, "name", "Ayuda Social")
    
    al_gerencia = await get_or_create(AuthorizationLevel, "name", "Gerencia de Personas")
    al_director = await get_or_create(AuthorizationLevel, "name", "Dirección General")
    
    bm_fijo = await get_or_create(BenefitModality, "name", "Fijo")
    bm_var = await get_or_create(BenefitModality, "name", "Variable")
    
    bf_mensual = await get_or_create(BenefitFrequency, "name", "Mensual")
    bf_unico = await get_or_create(BenefitFrequency, "name", "Único")
    
    # Beneficios principales
    bt_seguro = await get_or_create(BenefitType, "name", "Seguro de Salud Premium", description="Cobertura prepaga familiar para cargos jerárquicos")
    bt_combustible = await get_or_create(BenefitType, "name", "Ayuda de Combustible", description="Monto mensual para viáticos y movilidad")
    bt_beca = await get_or_create(BenefitType, "name", "Subsidio de Becas Universitarias", description="Financiamiento parcial de carreras o posgrados")
    
    # 60 solicitudes simuladas distribuidas en los últimos 18 meses
    statuses = ["Aprobada", "Pendiente", "Rechazada"]
    beneficios_list = [bt_seguro, bt_combustible, bt_beca]
    subtipos_list = [bs_seguro, bs_vale, bs_estu]
    modalidades = [bm_fijo, bm_var]
    frecuencias = [bf_mensual, bf_unico]
    motivos = [bgr_politica, bgr_rendimiento, bgr_social]
    
    for count in range(1, 61):
        emp = random.choice(bulk_employees)
        status = random.choices(statuses, weights=[0.75, 0.15, 0.10])[0]
        req_date = date.today() - timedelta(days=random.randint(5, 540))
        
        req = BenefitRequest(
            request_code=f"BE{count:03d}", employee_id=emp.id,
            request_type_id=brt_alta.id, request_date=req_date,
            grant_reason_id=random.choice(motivos).id, justification=f"Justificación técnica y laboral para el expediente BE{count:03d}",
            requester_id=emp_director.id, status=status, benefit_status="Activo" if status == "Aprobada" else "Pendiente",
            created_at=datetime.combine(req_date, datetime.min.time()) + timedelta(hours=random.randint(8,16))
        )
        if status == "Aprobada":
            req.authorizer_id = emp_director.id
            req.grant_date = req_date + timedelta(days=random.randint(1, 5))
            req.resolution_number = f"RES-2026-SO{count:02d}"
            req.approval_comments = "Evaluado y validado según disponibilidad de presupuesto anual."
            
        session.add(req)
        await session.flush()
        
        # Detalle de la solicitud (item)
        bt = random.choice(beneficios_list)
        monto = random.choice([350000.0, 500000.0, 1000000.0, 1500000.0]) if bt != bt_seguro else 0.0
        
        item = BenefitRequestItem(
            benefit_request_id=req.id, benefit_type_id=bt.id, benefit_subtype_id=random.choice(subtipos_list).id,
            currency_id=cur_pyg.id, approved_amount=monto if status == "Aprobada" else 0.0,
            validity_start_date=req_date + timedelta(days=5), benefit_modality_id=random.choice(modalidades).id,
            benefit_frequency_id=random.choice(frecuencias).id, description_notes=f"Notas operativas del beneficio item BE{count:03d}"
        )
        session.add(item)
        
    await session.flush()

    # ---------------------------------------------------------
    # 6. Méritos, Reconocimientos y Disciplina (35 Registros de cada uno)
    # ---------------------------------------------------------
    print("   -> Generando 35 amonestaciones y 35 reconocimientos históricos...")
    
    # Amonestaciones / Sanciones
    sanc_reasons = [
        "Amonestación por retrasos recurrentes en las marcaciones semanales.",
        "Ausencia injustificada al puesto de trabajo en horario vespertino.",
        "Incumplimiento de las normas de confidencialidad en manejo de expedientes.",
        "Falta de respeto o comportamiento no profesional en reuniones corporativas.",
        "No reportar de forma oportuna la justificación de reposo médico."
    ]
    for _ in range(35):
        emp = random.choice(bulk_employees)
        sanc = Sanction(
            employee_id=emp.id, type=random.choice([SanctionType.VERBAL, SanctionType.WRITTEN, SanctionType.SUSPENSION]),
            date=date.today() - timedelta(days=random.randint(10, 400)),
            reason=random.choice(sanc_reasons), sent_to_ministry=False,
            notes="Expediente registrado en legajo por TH."
        )
        session.add(sanc)
        
    # Reconocimientos / Méritos
    recog_titles = [
        "Colaborador Estrella del Mes",
        "Premio a la Innovación en Procesos",
        "Mención de Honor al Compromiso",
        "Destacado por Excelente Servicio",
        "Premio de Superación de Metas del Periodo"
    ]
    for _ in range(35):
        emp = random.choice(bulk_employees)
        recog = Recognition(
            employee_id=emp.id, type=random.choice([RecognitionType.EXCELLENCE, RecognitionType.ACHIEVEMENT, RecognitionType.INNOVATION]),
            date=date.today() - timedelta(days=random.randint(10, 400)),
            title=random.choice(recog_titles),
            description="Otorgado formalmente por la gerencia por demostrar un alto nivel de eficiencia en sus metas asignadas."
        )
        session.add(recog)
        
    await session.flush()

    # ---------------------------------------------------------
    # 7. Capacitaciones (Trainings)
    # ---------------------------------------------------------
    print("   -> Creando capacitaciones institucionales y matriculaciones...")
    
    prov_tech = TrainingProvider(
        business_name="Tech Academy S.A.", ruc="80099999-9", phone="021600700",
        email="contacto@techacademy.com.py", contact_person="Ing. Robert Downey", address="Av. Mcal. López 789"
    )
    prov_ops = TrainingProvider(
        business_name="Consultores del Cono Sur", ruc="80011111-1", phone="021400500",
        email="soporte@conosur.com.py", contact_person="Dra. Cynthia Pratt", address="Av. Santa Teresa 1400"
    )
    session.add_all([prov_tech, prov_ops])
    await session.flush()
    
    # 5 Cursos distribuidos en el tiempo (pasados o actuales, nunca futuro)
    course_fastapi = Training(
        name="FastAPI Avanzado y SQL Server", description="Profundización de microservicios, seguridad OAuth2 e integraciones asíncronas",
        type=TrainingType.EXTERNAL, provider_id=prov_tech.id, cost_per_person=1500000.0, company_cost=6000000.0,
        start_date=date.today() - timedelta(days=40), end_date=date.today() - timedelta(days=15), status=TrainingStatus.COMPLETED
    )
    course_liderazgo = Training(
        name="Habilidades Blandas en Talento Humano", description="Empatía, gestión de crisis internas y comunicación con sindicatos",
        type=TrainingType.INTERNAL, internal_instructor_id=emp_director.id, cost_per_person=0.0, company_cost=100000.0,
        start_date=date.today() - timedelta(days=10), end_date=date.today() + timedelta(days=5), status=TrainingStatus.IN_PROGRESS
    )
    course_iso = Training(
        name="Curso de Auditoría Interna ISO 9001", description="Normativas de calidad aplicadas a servicios logísticos y de soporte",
        type=TrainingType.EXTERNAL, provider_id=prov_ops.id, cost_per_person=2000000.0, company_cost=8000000.0,
        start_date=date.today() - timedelta(days=90), end_date=date.today() - timedelta(days=70), status=TrainingStatus.COMPLETED
    )
    session.add_all([course_fastapi, course_liderazgo, course_iso])
    await session.flush()
    
    # Matricular aleatoriamente a 40 empleados en cada curso finalizado o activo
    for emp in random.sample(bulk_employees, 35):
        enroll = TrainingEnrollment(
            training_id=course_fastapi.id, employee_id=emp.id, status=EnrollmentStatus.ATTENDED,
            invitation_sent_at=course_fastapi.start_date - timedelta(days=10), knowledge_score=random.randint(70, 100),
            feedback="Excelente curso teórico y práctico."
        )
        session.add(enroll)
        
    for emp in random.sample(bulk_employees, 25):
        enroll = TrainingEnrollment(
            training_id=course_liderazgo.id, employee_id=emp.id, status=EnrollmentStatus.ENROLLED,
            invitation_sent_at=course_liderazgo.start_date - timedelta(days=5)
        )
        session.add(enroll)
        
    await session.flush()

    # ---------------------------------------------------------
    # 8. Calendario de Eventos Institucionales
    # ---------------------------------------------------------
    print("   -> Creando eventos en el calendario de Sector Uno...")
    
    et_social = await get_or_create(CalendarEventType, "name", "Social", color="#3B82F6", description="Cumpleaños, aniversarios e integración")
    et_capacita = await get_or_create(CalendarEventType, "name", "Capacitación", color="#10B981", description="Cursos de inducción obligatorios")
    
    ev_social = CalendarEvent(
        title="Almuerzo de Fin de Año", description="Festejo anual de cierre de periodo laboral con la familia Sector Uno.",
        date=date.today() - timedelta(days=15), event_type_id=et_social.id, is_enrollable=True
    )
    ev_capacita = CalendarEvent(
        title="Taller de Inducción de Seguridad", description="Seguridad de la información y protección de legajos privados de Sector Uno.",
        date=date.today() - timedelta(days=1), event_type_id=et_capacita.id, is_enrollable=False
    )
    session.add_all([ev_social, ev_capacita])
    await session.flush()

    # ---------------------------------------------------------
    # 9. Reclutamiento y Vacantes Masivas (50 Vacantes, 4-8 Etapas)
    # ---------------------------------------------------------
    print("   -> Creando procesos de selección complejos con múltiples etapas...")
    
    hr_reemplazo = await get_or_create(HiringReason, "name", "Reemplazo de Personal")
    hr_aumento = await get_or_create(HiringReason, "name", "Aumento de Estructura")
    
    # Proceso 1: TI (7 Etapas)
    proc_tech = RecruitmentProcess(
        name="Proceso de Selección - Tecnología", description="Flujo exhaustivo de 7 etapas para programadores de Sector Uno"
    )
    session.add(proc_tech)
    await session.flush()
    
    stages_ti_objects = []
    stages_ti = [
        "Filtro Curricular", "Entrevista de Recursos Humanos", "Evaluación Técnica (FastAPI/React)",
        "Entrevista Técnica con Líderes", "Entrevista Final de Dirección", "Exámenes Médicos", "Oferta Económica"
    ]
    for idx, name in enumerate(stages_ti, 1):
        stage = ProcessStage(process_id=proc_tech.id, name=name, sla_days=random.choice([2, 3, 5]), owner=StageOwner.RECRUITER if idx in [1, 2, 7] else StageOwner.AREA, order_index=idx)
        session.add(stage)
        stages_ti_objects.append(stage)
        
    # Proceso 2: Operaciones y Logística (5 Etapas)
    proc_ops = RecruitmentProcess(
        name="Proceso de Selección - Operaciones y Logística", description="Evaluación rápida para cargos logísticos"
    )
    session.add(proc_ops)
    await session.flush()
    
    stages_ops_objects = []
    stages_ops = [
        "Filtro de Perfil", "Test Psicométrico e Inteligencia", "Dinámica de Grupo e Integración", "Entrevista Individual con Supervisor", "Oferta y Firma de Contrato"
    ]
    for idx, name in enumerate(stages_ops, 1):
        stage = ProcessStage(process_id=proc_ops.id, name=name, sla_days=random.choice([2, 3, 4]), owner=StageOwner.RECRUITER if idx in [1, 5] else StageOwner.AREA, order_index=idx)
        session.add(stage)
        stages_ops_objects.append(stage)
        
    await session.flush()

    # Generar 50 Vacantes con fechas de creación variables y estados realistas
    print("   -> Poblando 50 vacantes activas/cerradas e historiales de auditoría...")
    
    recruiter_user_id = user_director.id
    manager_user_id = user_gerente.id
    
    vacancy_titles_ti = ["Desarrollador Fullstack Junior", "DevOps Engineer", "QA Engineer", "Diseñador UI/UX", "Data Analyst", "Scrum Master"]
    vacancy_titles_ops = ["Coordinador de Almacén", "Supervisor de Despacho", "Operador Logístico", "Asistente de Importación", "Analista de Inventario"]
    
    for v_count in range(1, 51):
        is_ti = random.random() < 0.5
        title_base = random.choice(vacancy_titles_ti if is_ti else vacancy_titles_ops)
        title = f"Convocatoria {title_base} - Código #{1000 + v_count}"
        
        status = random.choices(
            [ProcessStatus.OPEN, ProcessStatus.CLOSED, ProcessStatus.CANCELLED],
            weights=[0.60, 0.30, 0.10]
        )[0]
        
        # Fecha de creación (Últimos 12 meses, nunca futura)
        start_date = date.today() - timedelta(days=random.randint(10, 360))
        
        vac = Vacancy(
            title=title, description=f"Descripción completa del puesto laboral para {title}. Buscamos un perfil proactivo y orientado a resultados.",
            status=status, vacancy_type=random.choice([VacancyType.EXTERNAL, VacancyType.INTERNAL]),
            is_headcount_increase=random.random() < 0.3, start_date=start_date,
            area_id=random.choice([area_ti, area_th, area_ops]).id, position_id=random.choice(posiciones).id,
            requester_id=manager_user_id, process_id=proc_tech.id if is_ti else proc_ops.id,
            hiring_reason_id=random.choice([hr_reemplazo, hr_aumento]).id, recruiter_id=recruiter_user_id,
            created_at=datetime.combine(start_date, datetime.min.time()) + timedelta(hours=random.randint(8,16))
        )
        session.add(vac)
        await session.flush()
        
        # Generar etapas individuales para esta vacante específica (VacancyStage)
        stages_list = stages_ti_objects if is_ti else stages_ops_objects
        current_stage_date = start_date
        
        # Determinar cuántas etapas se completaron según el estado de la vacante
        if status == ProcessStatus.CLOSED:
            num_completed_stages = len(stages_list) # todas completadas
        elif status == ProcessStatus.CANCELLED:
            num_completed_stages = random.randint(1, len(stages_list) - 1)
        else: # OPEN (activa)
            num_completed_stages = random.randint(1, len(stages_list) - 1)
            
        for s_idx, p_stage in enumerate(stages_list, 1):
            deadline_date = current_stage_date + timedelta(days=p_stage.sla_days)
            
            if s_idx <= num_completed_stages:
                # Etapa completada
                actual_days = random.randint(1, p_stage.sla_days + 2) # a veces con retraso
                end_date = current_stage_date + timedelta(days=actual_days)
                if end_date >= date.today():
                    end_date = date.today() - timedelta(days=1)
                
                notes = f"Etapa de '{p_stage.name}' finalizada y aprobada de forma satisfactoria. Se registraron todas las observaciones del comité evaluador de Sector Uno."
                next_stage_start = end_date
            else:
                # Etapa pendiente o futura
                end_date = None
                notes = "Pendiente de inicio. Esperando finalización de etapas previas del proceso." if status == ProcessStatus.OPEN else "Etapa cancelada debido a finalización prematura de la vacante."
                next_stage_start = current_stage_date + timedelta(days=p_stage.sla_days)
                
            v_stage = VacancyStage(
                vacancy_id=vac.id,
                name=p_stage.name,
                owner=p_stage.owner,
                responsible_id=recruiter_user_id if p_stage.owner == StageOwner.RECRUITER else manager_user_id,
                sla_days_snapshot=p_stage.sla_days,
                order_index=p_stage.order_index,
                start_date=current_stage_date,
                end_date=end_date,
                deadline_date=deadline_date,
                notes=notes
            )
            session.add(v_stage)
            current_stage_date = next_stage_start

        # Generar historial de AUDITORÍA para cada vacante (3-5 registros por vacante con tiempos variables)
        actions = ["CREATED", "STAGE_UPDATE", "STATUS_CHANGE"]
        details_list = [
            "Vacante aperturada con éxito en el sistema.",
            "Cambio de etapa de selección. Candidatos avanzados en el embudo.",
            "Cambio de estado general de la convocatoria."
        ]
        
        # Auditoría 1: Creación
        audit1 = RecruitmentAudit(
            vacancy_id=vac.id, user_id=recruiter_user_id, action="CREATED",
            details="Se aperturó y publicó formalmente la vacante para el reclutamiento.",
            timestamp=vac.created_at
        )
        session.add(audit1)
        
        # Auditorías 2 y 3: Modificaciones a lo largo de los días
        for idx in range(1, random.randint(2, 4)):
            audit_date = start_date + timedelta(days=random.randint(1, 8))
            if audit_date >= date.today():
                audit_date = date.today() - timedelta(days=1)
                
            act = random.choice(actions)
            det = random.choice(details_list) if act != "CREATED" else "Configuración inicial guardada."
            
            audit = RecruitmentAudit(
                vacancy_id=vac.id, user_id=recruiter_user_id, action=act, details=det,
                timestamp=datetime.combine(audit_date, datetime.min.time()) + timedelta(hours=random.randint(8,16))
            )
            session.add(audit)
            
    await session.commit()
    print(f"🎉 ¡Tenant '{tenant_name}' poblado masivamente con {len(bulk_employees)+4} colaboradores y 50 convocatorias completas!")

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
