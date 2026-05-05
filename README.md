# Semantic Score

A linked-data knowledge graph of classical music performances, artists, and concert programmes, served at [knowledge.semanticscore.net](https://knowledge.semanticscore.net).

---

## Architecture

```
source-ontology.ttl      Custom Music Ontology (CMO)
knowledge/assertions/    RDF instance data (source of truth)
knowledge/ontology/      Supporting ontologies (UI ontology etc.)
knowledge/shapes/        SHACL shapes driving faceted search and UI
knowledge/rules/         SPARQL CONSTRUCT inference rules
frontend/                Flask server + static page generator
nginx/                   Reverse proxy config
```

On every push to `main`, a GitHub Action rebuilds the Docker image (which regenerates all HTML pages) and restarts the server.

---

## Prerequisites

- Python 3.12+
- Docker and Docker Compose

---

## Local setup

```bash
git clone https://github.com/YOUR_USERNAME/semantic-score.git
cd semantic-score

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

make build    # generate frontend/output/
make serve    # start dev server at http://localhost:8080
```

---

## Deployment

The server runs Docker Compose with three services: `app` (gunicorn/Flask), `nginx`, and `certbot` (SSL auto-renewal).

### Server setup (one time)

```bash
# On the server
git clone https://github.com/YOUR_USERNAME/semantic-score.git /srv/semanticscore
cd /srv/semanticscore

docker compose up -d

# Get SSL certificate
make ssl-init EMAIL=you@email.com

# Edit nginx/default.conf: comment out STEP 1, uncomment STEP 2
docker compose restart nginx
```

### GitHub Actions secrets

Add these in Settings → Secrets → Actions:

| Secret | Value |
|---|---|
| `SERVER_HOST` | Server IP address |
| `SERVER_USER` | SSH username |
| `SERVER_SSH_KEY` | Private SSH key for the server |

After setup, every push to `main` that touches `knowledge/` or `frontend/` deploys automatically.

---

## License

Code: [MIT](LICENSE)  
Data (`knowledge/`): [CC BY 4.0](LICENSE-data.md) — Katariina Kari
