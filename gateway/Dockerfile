FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && useradd --system --uid 10001 --create-home opensms \
    && mkdir -p /app/data \
    && chown -R 10001:10001 /app
COPY opensms_gateway /app/opensms_gateway
COPY run.py /app/run.py
COPY start.sh /app/start.sh
RUN chmod 755 /app/start.sh \
    && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 8080
CMD ["/app/start.sh"]
