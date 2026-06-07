"""
Fachada de Servicios para el módulo de Reclutamiento.
Agrupa y expone las funciones de los sub-servicios para mantener compatibilidad.
"""

# Importar funciones de los sub-servicios
from app.modules.recruitment.services.audit import log_audit
from app.modules.recruitment.services.processes import (
    get_processes,
    get_process_detail,
    create_process,
    update_process,
    delete_process,
    add_stage_to_process,
    update_process_stage,
    delete_process_stage
)
from app.modules.recruitment.services.stage_edit_reasons import (
    get_stage_edit_reasons,
    get_stage_edit_reason_by_id,
    create_stage_edit_reason,
    update_stage_edit_reason,
    delete_stage_edit_reason
)
from app.modules.recruitment.services.vacancies import (
    get_users_for_assignment,
    get_recruiters,
    get_vacancy_counts,
    get_vacancies_paginated,
    get_vacancies_paginated,
    get_vacancy_detail,
    get_vacancy_by_id,
    create_vacancy,
    update_vacancy,
    delete_vacancy,
    notify_vacancy_status
)
from app.modules.recruitment.services.stages import (
    update_stage,
    notify_stage_responsible
)
from app.modules.recruitment.services.reports import (
    generate_excel_report,
    generate_pdf_report
)
from app.modules.recruitment.services.dashboard import (
    get_dashboard_metrics,
    get_monthly_stats,
    get_stage_performance_stats
)
from app.modules.recruitment.services.hiring_reasons import (
    get_hiring_reasons,
    get_hiring_reason_by_id,
    create_hiring_reason,
    update_hiring_reason,
    delete_hiring_reason
)

# Exportar explícitamente para que los IDEs y linters lo reconozcan
__all__ = [
    "log_audit",
    "get_processes",
    "get_process_detail",
    "create_process",
    "update_process",
    "delete_process",
    "add_stage_to_process",
    "update_process_stage",
    "delete_process_stage",
    "delete_process_stage",
    "get_users_for_assignment",
    "get_recruiters",
    "get_vacancy_counts",
    "get_vacancies_paginated",
    "get_vacancy_detail",
    "create_vacancy",
    "update_vacancy",
    "delete_vacancy",
    "notify_vacancy_status",
    "update_stage",
    "notify_stage_responsible",
    "generate_excel_report",
    "generate_pdf_report",
    "get_dashboard_metrics",
    "get_monthly_stats",
    "get_stage_performance_stats",
    "get_vacancy_by_id"
]