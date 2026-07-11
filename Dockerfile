FROM python:3.12-slim

ARG INSTALL_FREECAD=1
ARG PLM_UID=1000
ARG PLM_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FREECADCMD_COMMAND=freecadcmd
ENV PROCESS_EXPORT_JOBS_INLINE=0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && if [ "$INSTALL_FREECAD" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            freecad; \
    fi \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "$PLM_GID" plm \
    && useradd --uid "$PLM_UID" --gid "$PLM_GID" --create-home --shell /usr/sbin/nologin plm

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "freecad_plm.wsgi:application", "--bind", "0.0.0.0:8000"]
