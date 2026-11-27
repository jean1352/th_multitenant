import asyncio
import pandas as pd
import sys
import math
from datetime import datetime, date, time
from sqlalchemy import select
from app.core.database import AsyncSessionLocal

# --- IMPORTACIONES DE MODELOS ---
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

from app.modules.organization.models import Sede, Area
from app.modules.recruitment.models import (
    Vacancy, RecruitmentProcess, ProcessStage, VacancyStage,
    ProcessStatus, VacancyType, StageOwner
)
from app.modules.auth.models import User, UserRole

FILE_PATH = "vacantes.xlsx"
SHEET_NAMES = ["San Martín", "PJC"]  # Pestañas a procesar

def get_scalar(val):
    """Si pandas devuelve una Serie, toma el primer valor."""
    if isinstance(val, pd.Series):
        return val.iloc[0]
    return val

def is_valid_value(val):
    """Verifica si un valor de celda es válido."""
    val = get_scalar(val)
    if val is None: return False
    if pd.isna(val): return False 
    if isinstance(val, float) and math.isnan(val): return False
    if isinstance(val, str) and val.strip() == "": return False
    return True

def parse_date(value):
    """Convierte fechas de Excel a date de Python."""
    value = get_scalar(value)
    if not is_valid_value(value): return None
    if value in ["00:00:00", "0", 0]: return None
    
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    
    try:
        dt = pd.to_datetime(value, errors='coerce')
        if pd.isna(dt) or dt is pd.NaT:
            return None
        return dt.date()
    except:
        return None

def map_vacancy_type(value: str) -> VacancyType | None:
    value = get_scalar(value)
    if not is_valid_value(value): return None
    val_lower = str(value).lower().strip()
    if "externa" in val_lower: return VacancyType.EXTERNAL
    if "interna" in val_lower: return VacancyType.INTERNAL
    if "traslado" in val_lower: return VacancyType.TRANSFER
    return None

def get_safe_int(value):
    value = get_scalar(value)
    if not is_valid_value(value): return 0
    try: return int(float(value))
    except: return 0

def normalize_header(columns):
    """Normaliza los nombres de columnas."""
    mapping = {
        'vacante': 'vacante',
        'área': 'area',
        'area': 'area',
        'etapa': 'etapa',
        'tipo de cierre': 'tipo_cierre',
        'cierre de vacante': 'tipo_cierre',
        'fecha de inicio': 'fecha_inicio',
        'fecha de finalización': 'fecha_fin',
        'fecha de cumplimiento': 'fecha_cumplimiento',
        'días tope reclutador': 'sla_reclutador',
        'días tope solicitante': 'sla_solicitante',
        'observaciones': 'observaciones'
    }
    
    new_cols = []
    for col in columns:
        col_lower = str(col).strip().lower()
        found = False
        for key, val in mapping.items():
            if key in col_lower:
                new_cols.append(val)
                found = True
                break
        if not found:
            new_cols.append(col_lower)
    return new_cols

async def seed_data_from_excel():
    print(f"📄 Leyendo archivo Excel: {FILE_PATH}...")
    print(f"📋 Pestañas a procesar: {', '.join(SHEET_NAMES)}\n")
    
    total_vacancies = 0
    total_stages = 0
    
    for sheet_name in SHEET_NAMES:
        print(f"\n{'='*60}")
        print(f"🏢 PROCESANDO SEDE: {sheet_name}")
        print(f"{'='*60}")
        
        try:
            # 1. Detectar cabecera
            df_preview = pd.read_excel(FILE_PATH, sheet_name=sheet_name, header=None, nrows=20)
            header_idx = -1
            
            for idx, row in df_preview.iterrows():
                row_vals = [str(x).lower() for x in row.values]
                if "vacante" in row_vals and "etapa" in row_vals:
                    header_idx = idx
                    break
            
            if header_idx == -1:
                print(f"❌ No se encontró la fila de cabecera en '{sheet_name}'. Saltando...")
                continue

            print(f"📍 Cabecera encontrada en fila {header_idx + 1}")
            
            # 2. Leer datos
            df = pd.read_excel(FILE_PATH, sheet_name=sheet_name, header=header_idx)
            df.columns = normalize_header(df.columns)
            df = df.loc[:, ~df.columns.duplicated()] # Eliminar columnas duplicadas
            
        except Exception as e:
            print(f"❌ Error leyendo pestaña '{sheet_name}': {e}")
            continue

        async with AsyncSessionLocal() as session:
            # --- SETUP ---
            admin = await session.scalar(select(User).where(User.email == "admin@upacifico.edu.py"))
            if not admin:
                # Crear admin dummy si no existe (para evitar crash)
                from app.core.security import get_password_hash
                admin = User(email="admin@upacifico.edu.py", full_name="Admin", hashed_password=get_password_hash("admin123"), role=UserRole.ADMIN)
                session.add(admin)
                await session.flush()

            # Buscar o crear la sede según el nombre de la pestaña
            sede = await session.scalar(select(Sede).where(Sede.name == sheet_name))
            if not sede:
                sede = Sede(name=sheet_name)
                session.add(sede)
                await session.flush()
                print(f"✨ Sede '{sheet_name}' creada")
            else:
                print(f"📍 Usando sede existente: '{sheet_name}'")

            process_name = "Carga Histórica Excel"
            proc = await session.scalar(select(RecruitmentProcess).where(RecruitmentProcess.name == process_name))
            if not proc:
                proc = RecruitmentProcess(name=process_name, description="Importado")
                session.add(proc)
                await session.flush()

            # Caches
            area_cache = {}
            vacancy_stages_map = {}  # KEY: vacancy_id -> lista de (order_index, end_date)
            existing_stages = await session.execute(select(ProcessStage).where(ProcessStage.process_id == proc.id))
            process_stages_cache = {s.name: s for s in existing_stages.scalars().all()}

            current_vacancy = None
            current_vacancy_stages = []  # Etapas de la vacante actual
            current_area_id = None
            
            count_vacancies = 0
            count_stages = 0

            print(f"🔄 Procesando filas de '{sheet_name}'...")

            for idx, row in df.iterrows():
                raw_vacante = get_scalar(row.get('vacante'))
                raw_area = get_scalar(row.get('area'))
                raw_etapa = get_scalar(row.get('etapa'))
                
                if not is_valid_value(raw_etapa):
                    continue

                # --- 1. DETECCIÓN DE NUEVA VACANTE ---
                if is_valid_value(raw_vacante):
                    vac_title = str(raw_vacante).strip()
                    
                    if vac_title.lower() == 'vacante': 
                        continue

                    # Si había una vacante anterior, analizarla para cerrarla si corresponde
                    if current_vacancy is not None and current_vacancy_stages:
                        # Ordenar etapas por order_index para encontrar la última
                        stages_sorted = sorted(current_vacancy_stages, key=lambda x: x['order_index'])
                        last_stage = stages_sorted[-1]
                        
                        # Si la última etapa tiene fecha de fin, cerrar la vacante
                        if last_stage['end_date'] is not None:
                            end_dt = datetime.combine(last_stage['end_date'], time.min)
                            current_vacancy.status = ProcessStatus.CLOSED
                            current_vacancy.closed_at = end_dt
                            print(f"    🔒 Cerrada (última etapa: {last_stage['end_date']})")

                    # Área
                    area_name = str(raw_area).strip() if is_valid_value(raw_area) else "General"
                    if area_name not in area_cache:
                        area_obj = await session.scalar(select(Area).where(Area.name == area_name))
                        if not area_obj:
                            area_obj = Area(name=area_name, sede_id=sede.id, responsible_email="th@up.edu.pe")
                            session.add(area_obj)
                            await session.flush()
                        area_cache[area_name] = area_obj.id
                    current_area_id = area_cache[area_name]

                    # Datos Vacante
                    cierre_val = get_scalar(row.get('tipo_cierre'))
                    vac_type = map_vacancy_type(cierre_val)
                    
                    # FECHA CREACIÓN = Fecha Inicio de la PRIMERA etapa (esta fila)
                    start_date = parse_date(row.get('fecha_inicio'))
                    created_at = datetime.combine(start_date, time.min) if start_date else datetime.now()
                    
                    # Observaciones limpias
                    obs_val = get_scalar(row.get('observaciones'))
                    obs_text = str(obs_val).strip() if is_valid_value(obs_val) else ""
                    description = f"Vacante importada desde Excel.{' ' + obs_text if obs_text else ''}"

                    # Crear Vacante (Inicialmente OPEN)
                    current_vacancy = Vacancy(
                        title=vac_title,
                        description=description,
                        area_id=current_area_id,
                        requester_id=admin.id,
                        process_id=proc.id,
                        status=ProcessStatus.OPEN,
                        vacancy_type=vac_type,
                        created_at=created_at,
                        closed_at=None
                    )
                    session.add(current_vacancy)
                    await session.flush()
                    
                    # Reiniciar el registro de etapas para esta nueva vacante
                    current_vacancy_stages = []
                    
                    count_vacancies += 1
                    print(f"  ✨ [{count_vacancies}] {vac_title} | Tipo: {vac_type or 'N/A'} | Inicio: {created_at.date()}")

                # --- 2. PROCESAR ETAPA ---
                if current_vacancy:
                    etapa_name = str(raw_etapa).strip()
                    
                    # Definición de etapa (ProcessStage)
                    if etapa_name not in process_stages_cache:
                        sla_rec = get_safe_int(row.get('sla_reclutador'))
                        sla_sol = get_safe_int(row.get('sla_solicitante'))
                        owner = StageOwner.AREA if sla_sol > 0 else StageOwner.RECRUITER
                        sla = max(sla_rec, sla_sol, 2)
                        
                        new_ps = ProcessStage(
                            process_id=proc.id, name=etapa_name, owner=owner, sla_days=sla,
                            order_index=len(process_stages_cache)
                        )
                        session.add(new_ps)
                        await session.flush()
                        process_stages_cache[etapa_name] = new_ps

                    ps_def = process_stages_cache[etapa_name]

                    # Instancia de etapa (VacancyStage)
                    start = parse_date(row.get('fecha_inicio'))
                    deadline = parse_date(row.get('fecha_fin'))
                    end = parse_date(row.get('fecha_cumplimiento'))
                    
                    if not start: start = current_vacancy.created_at.date()
                    
                    obs_val = get_scalar(row.get('observaciones'))
                    obs_text = str(obs_val).strip() if is_valid_value(obs_val) else ""

                    vs = VacancyStage(
                        vacancy_id=current_vacancy.id,
                        name=ps_def.name,
                        owner=ps_def.owner,
                        responsible_id=None,
                        sla_days_snapshot=ps_def.sla_days,
                        order_index=ps_def.order_index,
                        start_date=start,
                        end_date=end,
                        deadline_date=deadline,
                        notes=obs_text
                    )
                    session.add(vs)
                    count_stages += 1
                    
                    # Guardar info de la etapa para la vacante actual
                    current_vacancy_stages.append({
                        'order_index': ps_def.order_index,
                        'end_date': end
                    })

            # --- PROCESAR LA ÚLTIMA VACANTE ---
            if current_vacancy is not None and current_vacancy_stages:
                stages_sorted = sorted(current_vacancy_stages, key=lambda x: x['order_index'])
                last_stage = stages_sorted[-1]
                
                if last_stage['end_date'] is not None:
                    end_dt = datetime.combine(last_stage['end_date'], time.min)
                    current_vacancy.status = ProcessStatus.CLOSED
                    current_vacancy.closed_at = end_dt
                    print(f"    🔒 Cerrada (última etapa: {last_stage['end_date']})")

            await session.commit()
            
            total_vacancies += count_vacancies
            total_stages += count_stages
            
            print(f"\n✅ Sede '{sheet_name}' completada:")
            print(f"   • Vacantes: {count_vacancies}")
            print(f"   • Etapas: {count_stages}")

    print("\n" + "="*60)
    print(f"✅ IMPORTACIÓN TOTAL FINALIZADA")
    print(f"   📊 Total Vacantes: {total_vacancies}")
    print(f"   📊 Total Etapas: {total_stages}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(seed_data_from_excel())