# The official Python image, from Amazon's public mirror of Docker Hub: builds on AWS share their
# addresses with other customers, and Docker Hub limits anonymous pulls per address.
FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations migrations
COPY app app
COPY web web
# Reset demo data imports the sales-history generator from here when DEMO_HISTORY_ON_RESET=on.
COPY scripts scripts
# Run as a non-root user.
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
