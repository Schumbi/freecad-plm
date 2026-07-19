# Auf Digest gepinnt (python:3.12-slim, Debian 13 trixie), damit ein Wandern
# des Tags nicht unbemerkt die Python-/Debian-Basis aendert.
ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

FROM ${PYTHON_BASE_IMAGE} AS app-base

ARG PLM_UID=1000
ARG PLM_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PROCESS_EXPORT_JOBS_INLINE=0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "$PLM_GID" plm \
    && useradd --uid "$PLM_UID" --gid "$PLM_GID" --create-home --shell /usr/sbin/nologin plm

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "freecad_plm.wsgi:application", "--bind", "0.0.0.0:8000"]

FROM app-base AS web

FROM ${PYTHON_BASE_IMAGE} AS freecad-bundle

ARG FREECAD_VERSION=1.1.1
ARG FREECAD_APPIMAGE_SHA256=e2006138400b2fa85fa2e160e872d00767eb32964e85075830f7e198a3a876e1
ARG FREECAD_APPIMAGE_URL=https://github.com/FreeCAD/FreeCAD/releases/download/1.1.1/FreeCAD_1.1.1-Linux-x86_64-py311.AppImage

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && curl --fail --location --retry 3 \
        "$FREECAD_APPIMAGE_URL" \
        --output /tmp/FreeCAD.AppImage \
    && echo "$FREECAD_APPIMAGE_SHA256  /tmp/FreeCAD.AppImage" | sha256sum --check --strict \
    && chmod +x /tmp/FreeCAD.AppImage \
    && cd /opt \
    && /tmp/FreeCAD.AppImage --appimage-extract >/dev/null \
    && mv /opt/squashfs-root /opt/freecad \
    && test -x /opt/freecad/AppRun \
    && rm -f /tmp/FreeCAD.AppImage \
    && rm -rf /var/lib/apt/lists/* \
    && echo "FreeCAD $FREECAD_VERSION bundle ready"

FROM freecad-bundle AS worker

ARG PLM_UID=1000
ARG PLM_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FREECADCMD_COMMAND=freecadcmd
ENV PROCESS_EXPORT_JOBS_INLINE=0

WORKDIR /app

RUN groupadd --gid "$PLM_GID" plm \
    && useradd --uid "$PLM_UID" --gid "$PLM_GID" --create-home --shell /usr/sbin/nologin plm

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --noinput

COPY docker/freecadcmd-wrapper.sh /usr/local/bin/freecadcmd

RUN chmod 0755 /usr/local/bin/freecadcmd \
    && freecadcmd --version \
    && freecadcmd --version | grep -F "FreeCAD 1.1.1"
