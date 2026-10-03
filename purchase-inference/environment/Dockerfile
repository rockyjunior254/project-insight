FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --timeout 300 --retries 10 -r /app/requirements.txt

COPY src/ /app/src/
COPY data/ /app/data/

RUN mkdir -p /app/output /app/logs

ENV PYTHONPATH=/app/src
