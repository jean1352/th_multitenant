# Usamos una imagen base oficial de Python ligera
FROM python:3.11-slim

# Variables de entorno para optimizar Python en Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Directorio de trabajo
WORKDIR /app

# Instalamos dependencias del sistema
# Agregamos: pango, cairo, gdk-pixbuf (Para WeasyPrint) y libfreetype (Para Matplotlib)
# Agregamos g++ para compilar numpy si no encuentra binarios compatibles
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       g++ \
       libpq-dev \
       libpango-1.0-0 \
       libpangoft2-1.0-0 \
       libjpeg-dev \
       libopenjp2-7-dev \
       libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copiamos primero los requerimientos
COPY requirements.txt /app/requirements.txt

# Actualizamos pip e instalamos las dependencias de Python
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiamos el resto del código
COPY . /app

# Creamos usuario no-root
RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app
USER appuser

# Exponemos el puerto
EXPOSE 8000

# Comando de ejecución
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]