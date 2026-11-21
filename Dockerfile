FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations migrations
COPY app app
COPY web web
# Reset demo data imports the sales-history generator from here when DEMO_HISTORY_ON_RESET=on.
COPY scripts scripts
# Run as a non-root user; /data holds the SQLite file when started through docker compose.
RUN useradd --create-home app && mkdir /data && chown app /data
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
