# N4MI DXCC Analyzer — same base and layout as Dan's other NAS apps (DXMon).
FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so code-only changes rebuild quickly.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/

# The SQLite database lives here. The stack bind-mounts the NAS folder
# /volume2/docker/n4mi-dxcc-analyzer/data onto it. If the mount is missing,
# the app says so on every page instead of quietly using an empty database.
ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

EXPOSE 8086
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8086"]
