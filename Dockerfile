FROM python:3.12-slim

ARG INSTALL_FREECAD=0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && if [ "$INSTALL_FREECAD" = "1" ]; then \
        apt-get install -y --no-install-recommends freecad xvfb; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "freecad_plm.wsgi:application", "--bind", "0.0.0.0:8000"]
