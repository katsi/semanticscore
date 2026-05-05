.PHONY: build serve \
        docker-build docker-up docker-down docker-logs docker-restart \
        ssl-init commit-assertions

# -----------------------------------------------------------------------
# Local development
# -----------------------------------------------------------------------

build:
	cd frontend && python3 generate_pages.py

serve:
	cd frontend && python3 server.py

# -----------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

docker-restart:
	docker compose restart app

# -----------------------------------------------------------------------
# First-time SSL setup (run once on the server after first deploy)
# -----------------------------------------------------------------------

ssl-init:
	@echo "Requesting certificate for knowledge.semanticscore.net …"
	docker compose run --rm certbot certonly \
		--webroot -w /var/www/certbot \
		-d knowledge.semanticscore.net \
		--email $(EMAIL) \
		--agree-tos --non-interactive
	@echo ""
	@echo "Certificate issued. Now edit nginx/default.conf:"
	@echo "  - Comment out the STEP 1 server block"
	@echo "  - Uncomment the STEP 2 blocks"
	@echo "Then run: docker compose restart nginx"

# -----------------------------------------------------------------------
# Git workflow shortcut — stages only assertion-layer files
# -----------------------------------------------------------------------

commit-assertions:
	git add knowledge/assertions/ knowledge/shapes/ knowledge/rules/ knowledge/ontology/ source-ontology.ttl
	git status
