# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ARG FRONTEND_APP_MODE=analysis
ARG FRONTEND_AI_ENABLED=0
ARG FRONTEND_BASE_PATH=/
ARG FRONTEND_API_BASE=
ARG FRONTEND_VIEWER_PORTAL_AUTH=0
ARG FRONTEND_TOOL_ACCESS_AUTH=0
ARG FRONTEND_RESET_ON_BROWSER_LOAD=0
ENV VITE_APP_MODE=${FRONTEND_APP_MODE}
ENV VITE_AI_ENABLED=${FRONTEND_AI_ENABLED}
ENV VITE_BASE_PATH=${FRONTEND_BASE_PATH}
ENV VITE_API_BASE_URL=${FRONTEND_API_BASE}
ENV VITE_VIEWER_PORTAL_AUTH=${FRONTEND_VIEWER_PORTAL_AUTH}
ENV VITE_TOOL_ACCESS_AUTH=${FRONTEND_TOOL_ACCESS_AUTH}
ENV VITE_RESET_ON_BROWSER_LOAD=${FRONTEND_RESET_ON_BROWSER_LOAD}
RUN npm run build

FROM python:3.13-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    COPYLOT_FRONTEND_DIST=/app/frontend_dist

WORKDIR /app

# VSN normalization is delegated to the reference Bioconductor implementation.
# Debian bookworm ships R 4.2, which corresponds to Bioconductor 3.16. Install
# the heavy dependencies from Debian binaries and compile only `vsn` itself.
# The final probe makes the image build fail instead of silently hiding VSN in
# the UI when R or the package installation is incomplete.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        r-base-core \
        r-base-dev \
        r-cran-biocmanager \
        r-bioc-affy \
        r-bioc-biobase \
        r-bioc-limma \
        r-cran-ggplot2 \
    && Rscript -e 'BiocManager::install("vsn", version = "3.16", ask = FALSE, update = FALSE, dependencies = FALSE)' \
    && Rscript -e 'stopifnot(requireNamespace("vsn", quietly = TRUE)); cat(as.character(packageVersion("vsn")))' \
    && apt-get purge -y --auto-remove r-base-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/downloaded_packages

# The faces a figure can be drawn in. Journals ask for Arial, Helvetica, Times
# New Roman or Courier; the Liberation family is metric-compatible with all of
# them, which is what makes a figure drawn here the same size as one drawn on a
# machine that has the originals. Without this the font list in the UI would
# still work and every choice would silently produce DejaVu, because matplotlib
# substitutes a missing family with a warning nobody sees.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-runtime.lock /app/backend/requirements-runtime.lock
RUN pip install --upgrade pip && pip install -r /app/backend/requirements-runtime.lock

COPY backend /app/backend
RUN test -f /app/backend/app/services/session_context.py
COPY launch.py /app/launch.py
COPY launch_tool.py /app/launch_tool.py
COPY launch_viewer.py /app/launch_viewer.py
COPY viewer_config.json /app/viewer_config.json
COPY proteomicscopylot/example_data /app/proteomicscopylot/example_data
COPY proteomicscopylot/notebook_functions.py /app/proteomicscopylot/notebook_functions.py
COPY LICENSE /app/LICENSE
RUN mkdir -p /app/data /app/viewer_data /app/local
COPY data/db /app/data/db
COPY data/report /app/data/report

COPY --from=frontend-build /build/frontend/dist /app/frontend_dist

# Every face the advanced panel offers has to resolve to a real file, and the
# font cache is built now rather than during the first plot somebody asks for.
# This reads the list from the code, so adding a font without installing it
# fails the build instead of shipping a menu entry that does nothing.
RUN python -c "import sys; sys.path.insert(0, '/app/backend'); \
from app.services.plot_images import verify_fonts_installed; \
print(verify_fonts_installed())"

RUN groupadd --system --gid 10001 copylot \
    && useradd --system --uid 10001 --gid copylot --home-dir /app --shell /usr/sbin/nologin copylot \
    && chown -R copylot:copylot /app

USER copylot

EXPOSE 10000

CMD ["sh", "-c", "python /app/launch.py --host 0.0.0.0 --port ${PORT:-10000} --no-browser"]
