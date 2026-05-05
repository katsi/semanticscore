FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer-cached until requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY knowledge/         ./knowledge/
COPY source-ontology.ttl .
COPY namespaces.jsonld   .
COPY frontend/           ./frontend/

# Generate static HTML pages at build time.
# Any change to assertions/ or frontend/ triggers a rebuild of this layer.
RUN cd frontend && python3 generate_pages.py

WORKDIR /app/frontend
EXPOSE 5000

CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "180", "wsgi:app"]
