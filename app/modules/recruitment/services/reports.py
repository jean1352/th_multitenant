import base64
import io
from datetime import date, datetime
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from weasyprint import HTML

from app.modules.organization.models import Area, Position
from app.modules.recruitment import schemas
from app.core.config import settings
from app.modules.recruitment.models import (
    ProcessStatus,
    RecruitmentAudit,
    RecruitmentProcess,
    Vacancy,
    VacancyStage
)

# Configuración de Matplotlib para servidor (sin interfaz gráfica)
matplotlib.use('Agg')

def _apply_report_filters(
    stmt, area_id=None, status=None, start_date=None, end_date=None
):
    """Aplica filtros comunes a las consultas de reportes."""
    if area_id:
        stmt = stmt.where(Vacancy.area_id == area_id)
    if status and status != "all":
        stmt = stmt.where(Vacancy.status == status)
    if start_date and end_date:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        stages_subquery = select(VacancyStage.vacancy_id).where(
            VacancyStage.end_date.between(start_date, end_date)
        )
        stmt = stmt.where(
            or_(
                Vacancy.created_at.between(start_dt, end_dt),
                Vacancy.closed_at.between(start_dt, end_dt),
                Vacancy.id.in_(stages_subquery),
            )
        )
    return stmt


async def generate_excel_report(
    db: AsyncSession,
    area_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> io.BytesIO:
    """Genera un archivo Excel con el reporte de vacantes."""
    stmt = (
        select(
            Vacancy,
            Area.name.label("area_name"),
            RecruitmentProcess.name.label("process_name"),
        )
        .join(Area, Vacancy.area_id == Area.id)
        .join(RecruitmentProcess, Vacancy.process_id == RecruitmentProcess.id)
        .options(
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.position).selectinload(Position.parent),
            selectinload(Vacancy.position).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Vacancy.audits).selectinload(RecruitmentAudit.user),
        )
    )
    stmt = _apply_report_filters(stmt, area_id, status, start_date, end_date)
    stmt = stmt.order_by(desc(Vacancy.created_at))
    result = await db.execute(stmt)
    data = []
    for row in result:
        vac = row[0]
        vac.area_name = row[1]
        vac.process_name = row[2]
        dto = schemas.VacancyDetail.model_validate(vac)
        data.append(
            {
                "ID": vac.id,
                "Título": vac.title,
                "Cargo": vac.position.name if vac.position else "-",
                "Área": vac.area_name,
                "Proceso": vac.process_name,
                "Estado": vac.status.value,
                "Tipo": vac.vacancy_type.value if vac.vacancy_type else "Pendiente",
                "Aumento Dotación": "Sí" if vac.is_headcount_increase else "No",
                "SLA": "OK" if dto.global_sla_status == "ok" else "Vencido",
                "Progreso": f"{dto.progress_percent}%",
                "Fecha Creación": vac.created_at.strftime("%Y-%m-%d"),
            }
        )
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return output


def generate_chart_base64(data: dict, title: str, chart_type="bar"):
    """Genera un gráfico en base64 para incrustar en PDF."""
    plt.figure(figsize=(6, 4))
    labels = list(data.keys())
    values = list(data.values())
    if sum(values) == 0:
        plt.text(
            0.5, 0.5, "Sin datos", ha="center", va="center", color="gray"
        )
        plt.axis("off")
    else:
        if chart_type == "bar":
            plt.barh(labels, values, color="#003366")
            plt.xlabel("Cantidad")
        elif chart_type == "pie":
            plt.pie(
                values,
                labels=labels,
                autopct="%1.1f%%",
                colors=["#10B981", "#EF4444", "#F59E0B"],
            )
    plt.title(title)
    plt.tight_layout()
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    plt.close()
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


async def generate_pdf_report(
    db: AsyncSession,
    templates: Jinja2Templates,
    area_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> bytes:
    """Genera un reporte PDF ejecutivo."""
    stmt = (
        select(Vacancy)
        .join(Area)
        .options(
            selectinload(Vacancy.stages).selectinload(VacancyStage.responsible),
            selectinload(Vacancy.process),
            selectinload(Vacancy.area),
            selectinload(Vacancy.position).selectinload(Position.parent),
            selectinload(Vacancy.position).selectinload(Position.area).selectinload(Area.sede),
            selectinload(Vacancy.audits).selectinload(RecruitmentAudit.user),
        )
    )
    stmt = _apply_report_filters(stmt, area_id, status, start_date, end_date)
    stmt = stmt.order_by(Area.name, desc(Vacancy.created_at))
    result = await db.execute(stmt)
    vacancies = result.scalars().all()
    total = len(vacancies)
    open_count = sum(1 for v in vacancies if v.status == ProcessStatus.OPEN)
    closed_count = sum(
        1 for v in vacancies if v.status == ProcessStatus.CLOSED
    )
    sla_ok = 0
    sla_overdue = 0
    areas_data = {}
    for vac in vacancies:
        dto = schemas.VacancyDetail.model_validate(vac)
        if dto.global_sla_status == "ok":
            sla_ok += 1
        else:
            sla_overdue += 1
        area_name = vac.area.name
        if area_name not in areas_data:
            areas_data[area_name] = []
        areas_data[area_name].append(
            {
                "title": vac.title,
                "status": vac.status.value,
                "created_at": vac.created_at,
                "sla_status": dto.global_sla_status,
                "progress": dto.progress_percent,
                "days_elapsed": dto.total_days_elapsed,
                "sla_total": dto.total_sla_days,
            }
        )
    sla_rate = round((sla_ok / total * 100), 1) if total > 0 else 0
    chart_sla_data = {"A Tiempo": sla_ok, "Fuera de Plazo": sla_overdue}
    chart_sla_img = generate_chart_base64(
        chart_sla_data, "Cumplimiento SLA", "pie"
    )
    chart_area_img = None
    if not area_id:
        chart_area_data = {k: len(v) for k, v in areas_data.items()}
        chart_area_img = generate_chart_base64(
            chart_area_data, "Vacantes por Área", "bar"
        )
    report_areas = [{"name": k, "vacancies": v} for k, v in areas_data.items()]
    filter_text = "Todos los registros"
    if start_date and end_date:
        filter_text = (
            f"Actividad entre {start_date.strftime('%d/%m/%Y')} y "
            f"{end_date.strftime('%d/%m/%Y')}"
        )
    html_content = templates.get_template("reports/pdf_template.html").render(
        date=datetime.now().strftime("%d/%m/%Y"),
        filter_text=filter_text,
        metrics={
            "total": total,
            "open": open_count,
            "closed": closed_count,
            "sla_rate": sla_rate,
        },
        charts={"area": chart_area_img, "sla": chart_sla_img},
        areas=report_areas,
        settings=settings,
    )
    return HTML(string=html_content).write_pdf()