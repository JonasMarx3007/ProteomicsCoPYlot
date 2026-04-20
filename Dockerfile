# syntax=docker/dockerfile:1.7

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ENV VITE_APP_MODE=analysis
RUN npm run build

FROM python:3.11-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    COPYLOT_FRONTEND_DIST=/app/frontend_dist

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY launch.py /app/launch.py
COPY launch_tool.py /app/launch_tool.py
COPY launch_viewer.py /app/launch_viewer.py
COPY viewer_config.json /app/viewer_config.json
RUN mkdir -p /app/data /app/viewer_data
COPY data/db /app/data/db
COPY data/report /app/data/report

COPY --from=frontend-build /build/frontend/dist /app/frontend_dist

EXPOSE 10000

CMD ["sh", "-c", "python /app/launch.py --host 0.0.0.0 --port ${PORT:-10000} --no-browser"]
