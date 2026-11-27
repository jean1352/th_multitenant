"""
Migra los correos institucionales desde ``Lista_de_correos.xlsx`` hacia la tabla
``employees``, emparejando por el documento de identidad (CI).

Contexto del problema
---------------------
El campo ``employees.document_id`` (el CI) quedó inconsistente por fallos en
migraciones previas:

* Valores con un ``.0`` al final, ej. ``4873804.0`` en lugar de ``4873804``.
* Valores con separador de miles, ej. ``4.759.319`` en lugar de ``4759319``.
* Algunos valores no numéricos de relleno ("No aplica", "N/A", "Falta cargar"...).

Este script normaliza el CI (quita ``.0`` y cualquier carácter no numérico) para
emparejar el listado con los colaboradores, y de forma opcional limpia esos
valores en la base de datos.

Uso
---
    python migrate_correos.py                 # Dry-run: muestra el plan sin escribir
    python migrate_correos.py --apply         # Aplica la migración de correos
    python migrate_correos.py --apply --clean-ci   # Además normaliza el CI en la BD
    python migrate_correos.py --apply --overwrite   # Sobrescribe correos existentes

Parámetros útiles: ``--excel`` (ruta), ``--host``, ``--port``.
"""

import argparse
import asyncio
import os
import re

import asyncpg
from dotenv import load_dotenv

# --- Configuración por defecto -------------------------------------------------

DEFAULT_EXCEL = "Lista_de_correos.xlsx"

# Encabezados que se buscan (sin tildes/acentos, case-insensitive) para detectar
# la fila de cabecera dentro de la hoja.
HEADER_MARKERS = ("doc", "correo")

# Umbral de similitud de nombres por debajo del cual se considera que el CI
# normalizado apunta a una persona distinta de la del listado (posible error de
# datos). Se omite la asignación y se reporta como "sospechoso".
SUSPICIOUS_OVERLAP = 0.3


# --- Utilidades ---------------------------------------------------------------

def normalize_ci(value) -> str:
    """Normaliza un CI/documento a su forma numérica pura.

    - "4873804.0"    -> "4873804"
    - "4.759.319"    -> "4759319"
    - 4873804 (int)  -> "4873804"
    - "No aplica"    -> "" (sin dígitos)
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # "4873804.0" -> "4873804"
    text = re.sub(r"\.0+$", "", text)
    # Quitar cualquier otro carácter que no sea dígito (separadores de miles, etc.)
    text = re.sub(r"[^0-9]", "", text)
    return text


def is_numeric_ci(raw) -> bool:
    """True si el documento es un CI numérico candidato a normalización.

    Acepta formatos como "4873804", "4873804.0" o "4.759.319" (separador de
    miles), pero descarta placeholders de texto aunque contengan algún dígito
    (p. ej. "Salió2", "Cargar-", "n/ap").
    """
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return False
    return bool(re.fullmatch(r"\d+(?:\.\d{3})*(?:\.0+)?", text))


def normalize_name(value) -> str:
    """Normaliza un nombre para comparaciones tolerantes (solo diagnóstico)."""
    if value is None:
        return ""
    text = str(value).strip().upper()
    replacements = {
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "Ñ": "N", "Ü": "U",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", " ", text).strip()


def token_overlap(a, b) -> float:
    """Similitud de Jaccard entre los conjuntos de palabras de dos nombres.

    Sirve para detectar cuando un CI normalizado apunta a una persona distinta
    de la que indica el nombre (p. ej. dos personas distintas con el mismo CI).
    1.0 = mismo conjunto de palabras; 0.0 = sin palabras en común.
    """
    set_a = {t for t in normalize_name(a).split() if t}
    set_b = {t for t in normalize_name(b).split() if t}
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def read_excel(path: str):
    """Lee el listado y devuelve una lista de dicts con doc_raw, name y email.

    La hoja tiene una fila de título y una fila de cabecera; se detecta la fila
    que contiene "doc" y "correo" para no depender de posiciones fijas.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    if not wb.sheetnames:
        raise ValueError(f"El archivo {path} no tiene hojas.")

    ws = wb[wb.sheetnames[0]]

    # Localizar la fila de cabecera
    header_row = None
    for r in range(1, ws.max_row + 1):
        row_values = [
            str(ws.cell(row=r, column=c).value or "").strip().lower()
            for c in range(1, ws.max_column + 1)
        ]
        if all(any(marker in v for v in row_values) for marker in HEADER_MARKERS):
            header_row = r
            break

    if header_row is None:
        raise ValueError(
            f"No se pudo detectar la cabecera (se buscaron: {HEADER_MARKERS})."
        )

    # Mapear columnas por nombre de cabecera
    col_index = {}
    for c in range(1, ws.max_column + 1):
        raw = str(ws.cell(row=header_row, column=c).value or "").strip().lower()
        if "doc" in raw:
            col_index["doc"] = c
        elif "correo" in raw or "email" in raw or "mail" in raw:
            col_index["correo"] = c
        elif "nombre" in raw or "apellido" in raw:
            col_index["nombre"] = c

    if "doc" not in col_index or "correo" not in col_index:
        raise ValueError(
            "No se encontraron las columnas 'Doc.' y 'Correo' en la cabecera."
        )

    records = []
    for r in range(header_row + 1, ws.max_row + 1):
        doc = ws.cell(row=r, column=col_index["doc"]).value
        email = ws.cell(row=r, column=col_index["correo"]).value
        name = (
            ws.cell(row=r, column=col_index["nombre"]).value
            if "nombre" in col_index
            else None
        )
        # Omitir filas totalmente vacías
        if doc is None and (email is None or str(email).strip() == ""):
            continue
        records.append(
            {
                "doc_raw": doc,
                "name": name,
                "email": str(email).strip() if email is not None else "",
            }
        )

    return records


# --- Conexión -----------------------------------------------------------------

async def connect(args) -> asyncpg.Connection:
    user = os.getenv("POSTGRES_USER", "admin")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "talento_up_db")
    host = args.host or os.getenv("POSTGRES_SERVER", "127.0.0.1")
    port = args.port or int(os.getenv("POSTGRES_PORT", "5432"))

    print(f"Conectando a {host}:{port}/{database} como {user}...")
    return await asyncpg.connect(
        user=user, password=password, database=database, host=host, port=port
    )


# --- Lógica principal ---------------------------------------------------------

async def run(args):
    load_dotenv()

    print("=" * 70)
    print("MIGRACIÓN DE CORREOS (Lista_de_correos.xlsx -> employees)")
    print("=" * 70)

    records = read_excel(args.excel)
    print(f"📄 Leídas {len(records)} filas del listado {args.excel}.")

    # Índice del Excel por CI normalizado. Un CI puede aparecer repetido.
    from collections import defaultdict

    excel_by_ci = defaultdict(list)
    for rec in records:
        ci = normalize_ci(rec["doc_raw"])
        if ci:
            excel_by_ci[ci].append(rec)

    duplicates_excel = {
        ci: recs for ci, recs in excel_by_ci.items() if len(recs) > 1
    }
    if duplicates_excel:
        print(f"⚠️  CI duplicados en el listado ({len(duplicates_excel)}):")
        for ci, recs in duplicates_excel.items():
            names = [r["name"] or r["email"] or "?" for r in recs]
            print(f"    - CI {ci}: {names}")

    conn = await connect(args)
    try:
        employees = await conn.fetch(
            "SELECT id, document_id, full_name, institutional_email "
            "FROM employees ORDER BY id"
        )
        print(f"🗄️  Colaboradores en BD: {len(employees)}.")

        # ---- PASO 1: limpieza del CI en la base (opcional) ----
        clean_updates = []  # (id, old, new)
        if args.clean_ci:
            clean_updates = plan_ci_cleanup(employees)

        # ---- PASO 2: emparejamiento y migración de correos ----
        email_updates = []     # (id, old, new)
        no_match = []          # (id, document_id, full_name)
        no_email = []          # (id, document_id, full_name)
        conflicts = []         # (id, document_id, current, proposed)
        suspicious = []        # (emp, excel_name, proposed, overlap)
        for emp in employees:
            ci = normalize_ci(emp["document_id"])
            matched = excel_by_ci.get(ci) if ci else None

            if not matched:
                no_match.append(emp)
                continue

            # Elegir el primer correo no vacío del grupo (si hay duplicados)
            proposed = next((m["email"] for m in matched if m["email"]), "")
            if not proposed:
                no_email.append(emp)
                continue

            # Verificación por nombre: si el CI normalizado apunta a una persona
            # cuyo nombre no coincide con el listado, se marca como sospechoso.
            excel_name = next((m["name"] for m in matched if m["name"]), None)
            overlap = token_overlap(emp["full_name"], excel_name) if excel_name else 1.0
            if overlap < args.min_overlap and not args.force:
                suspicious.append((emp, excel_name, proposed, overlap))
                continue

            current = emp["institutional_email"] or ""
            if current and current.lower() != proposed.lower():
                conflicts.append((emp, current, proposed))
                if not args.overwrite:
                    continue
            if current.lower() == proposed.lower():
                continue

            email_updates.append((emp["id"], current, proposed))

        # ---- Reporte en dry-run ----
        mode = "APLICAR" if args.apply else "DRY-RUN"
        print("\n" + "-" * 70)
        print(f"RESUMEN [{mode}]")
        print("-" * 70)
        print(f"• Correos a migrar:              {len(email_updates)}")
        print(f"• Sin coincidencia por CI:       {len(no_match)}")
        print(f"• Coinciden pero sin correo:     {len(no_email)}")
        print(f"• Sospechosos (nombre no coincide): {len(suspicious)}")
        print(f"• Correo existente distinto:     {len(conflicts)}")
        print(f"• CI a limpiar en BD:            {len(clean_updates)}")

        if clean_updates:
            print("\nLimpieza de CI planificada:")
            for emp_id, old, new in clean_updates[:20]:
                print(f"    #{emp_id}: {old!r} -> {new!r}")
            if len(clean_updates) > 20:
                print(f"    ... y {len(clean_updates) - 20} más")

        if email_updates:
            print("\nCorreos planificados (primeros 20):")
            for emp_id, old, new in email_updates[:20]:
                print(f"    #{emp_id}: {old or '(vacío)'!r} -> {new!r}")
            if len(email_updates) > 20:
                print(f"    ... y {len(email_updates) - 20} más")

        if conflicts and not args.overwrite:
            print(
                "\n⚠️  Correos existentes distintos (use --overwrite para sobrescribir):"
            )
            for emp, cur, prop in conflicts[:20]:
                print(
                    f"    #{emp['id']} {emp['full_name']!r}: actual={cur!r} listado={prop!r}"
                )

        if suspicious:
            print(
                "\n🔎 Sospechosos: el CI coincide pero el nombre difiere (no se asigna)."
            )
            print("   Revise manualmente; use --force para ignorar la verificación.")
            for emp, excel_name, prop, overlap in suspicious[:30]:
                print(
                    f"    #{emp['id']} {emp['full_name']!r} (CI={emp['document_id']!r})"
                    f" vs listado {excel_name!r} overlap={overlap:.2f} correo={prop!r}"
                )
            if len(suspicious) > 30:
                print(f"    ... y {len(suspicious) - 30} más")

        if no_match:
            print("\nSin coincidencia por CI (primeros 20):")
            for emp in no_match[:20]:
                print(f"    #{emp['id']} CI={emp['document_id']!r} {emp['full_name']!r}")
            if len(no_match) > 20:
                print(f"    ... y {len(no_match) - 20} más")

        if not args.apply:
            print(
                "\nℹ️  Modo dry-run. Ejecute con --apply para escribir en la base."
            )
            return

        # ---- Aplicar cambios ----
        async with conn.transaction():
            for emp_id, _old, new in clean_updates:
                await conn.execute(
                    "UPDATE employees SET document_id = $1 WHERE id = $2",
                    new,
                    emp_id,
                )
            for emp_id, _old, new in email_updates:
                await conn.execute(
                    "UPDATE employees SET institutional_email = $1 WHERE id = $2",
                    new,
                    emp_id,
                )

        print("\n✅ Migración aplicada correctamente.")
        if clean_updates:
            print(f"   • {len(clean_updates)} CI normalizados.")
        if email_updates:
            print(f"   • {len(email_updates)} correos institucionales migrados.")

    finally:
        await conn.close()


def plan_ci_cleanup(employees):
    """Devuelve la lista de (id, old, new) de CI seguros de limpiar.

    Es conservadora: solo limpia cuando el valor normalizado es único (no colisiona
    con otro colaborador). Los grupos donde dos o más colaboradores comparten el
    mismo CI normalizado (duplicados de migraciones previas) se dejan intactos y
    se reportan.
    """
    from collections import defaultdict

    norm_groups = defaultdict(list)
    for emp in employees:
        norm = normalize_ci(emp["document_id"])
        if norm:  # solo agrupamos los que tienen algo numérico
            norm_groups[norm].append(emp)

    updates = []
    collisions = []
    for norm, group in norm_groups.items():
        dirty = [
            emp
            for emp in group
            if is_numeric_ci(emp["document_id"])
            and str(emp["document_id"]).strip() != norm
        ]
        if not dirty:
            continue
        if len(group) > 1:
            # Colisión: dos colaboradores mapearían al mismo CI. No se toca.
            collisions.append((norm, group))
            continue
        for emp in dirty:
            updates.append((emp["id"], str(emp["document_id"]).strip(), norm))

    if collisions:
        print(f"\n⚠️  {len(collisions)} CI no limpiados por colisión (duplicados):")
        for norm, group in collisions[:20]:
            ids = [f"#{e['id']}" for e in group]
            docs = [repr(str(e["document_id"])) for e in group]
            print(f"    CI {norm}: {ids} docs={docs}")

    return updates


def parse_args():
    parser = argparse.ArgumentParser(
        description="Migra correos desde Lista_de_correos.xlsx hacia employees."
    )
    parser.add_argument("--excel", default=DEFAULT_EXCEL, help="Ruta del listado.")
    parser.add_argument(
        "--apply", action="store_true", help="Escribe los cambios (por defecto es dry-run)."
    )
    parser.add_argument(
        "--clean-ci",
        action="store_true",
        help="Además normaliza el document_id en la BD (quita .0 y separadores).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescribe correos existentes que difieran del listado.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora la verificación por nombre y asigna aunque el nombre difiera.",
    )
    parser.add_argument(
        "--min-overlap",
        default=SUSPICIOUS_OVERLAP,
        type=float,
        help="Similitud mínima de nombres (0-1) para no marcar como sospechoso.",
    )
    parser.add_argument("--host", default=None, help="Host de PostgreSQL.")
    parser.add_argument("--port", default=None, type=int, help="Puerto de PostgreSQL.")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
