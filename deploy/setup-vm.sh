#!/usr/bin/env bash
# TestRadius — One-command cloud VM setup
#
# Quick start (on a fresh Ubuntu/Debian VM):
#   bash <(curl -fsSL https://raw.githubusercontent.com/hbahuguna/testradius/main/deploy/setup-vm.sh)
#
# With custom domain (enables TLS):
#   DOMAIN=testradius.example.com bash <(curl -fsSL ...)
#
# Environment variables (all optional):
#   DOMAIN=example.com       Public DNS name (enables Caddy + Let's Encrypt TLS)
#   TESTRADIUS_DIR=/opt/testradius  Where to clone the stack
#   TARGET_REPO_DIR=/opt/Test-Radius  Where to clone the target app
#   DATA_DIR=/opt/testradius-data    Persistent data (DB, Neo4j, workspaces)

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────────────
DOMAIN="${DOMAIN:-}"
TESTRADIUS_DIR="${TESTRADIUS_DIR:-$HOME/testradius}"
TARGET_REPO_DIR="${TARGET_REPO_DIR:-$HOME/Test-Radius}"
DATA_DIR="${DATA_DIR:-/opt/testradius-data}"

# Detect public IP
PUBLIC_IP=$(curl -sf https://api.ipify.org 2>/dev/null || echo "")

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[x]${NC} $*"; }

# ─── Preflight ───────────────────────────────────────────────────────────────
info "Checking prerequisites..."

if [ "$(uname)" = "Linux" ]; then
  if ! command -v docker &>/dev/null; then
    warn "Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sudo bash
    sudo usermod -aG docker "$USER"
    warn "Log out and back in, or run: newgrp docker"
  fi
  if ! docker compose version &>/dev/null; then
    warn "Installing Docker Compose plugin..."
    DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
    mkdir -p "$DOCKER_CONFIG/cli-plugins"
    ARCH=$(uname -m)
    [ "$ARCH" = "aarch64" ] && ARCH="arm64"
    curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
      -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
    chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
  fi
else
  info "Docker Desktop expected on $(uname)"
  command -v docker &>/dev/null || { err "Docker not found. Install Docker Desktop."; exit 1; }
fi

# ─── Clone repos ────────────────────────────────────────────────────────────
if [ ! -d "$TESTRADIUS_DIR" ]; then
  info "Cloning TestRadius stack..."
  git clone https://github.com/hbahuguna/testradius.git "$TESTRADIUS_DIR"
fi

if [ ! -d "$TARGET_REPO_DIR" ]; then
  info "Cloning Test-Radius target app..."
  git clone https://github.com/hbahuguna/Test-Radius.git "$TARGET_REPO_DIR"
fi

cd "$TESTRADIUS_DIR"

# ─── .env ───────────────────────────────────────────────────────────────────
info "Creating .env..."
cat > .env <<EOF
# TestRadius — Cloud VM
DATABASE_URL=postgresql+asyncpg://testsquad:testsquad_password@db:5432/testsquad
NEO4J_URL=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=testsquad_password
EXECUTOR_URL=http://executor:8001
DEMO_MODE=true
TESTRADIUS_LOCAL_PATH=/testradius

# Cloud VM paths
TESTRADIUS_SRC=${TARGET_REPO_DIR}
PUBLIC_IP=${PUBLIC_IP:-localhost}
EOF

# ─── Data dirs ──────────────────────────────────────────────────────────────
info "Setting up data directories..."
sudo mkdir -p "$DATA_DIR"/{workspaces,caddy}
sudo chown -R "$USER":"$(id -gn)" "$DATA_DIR"

# ─── Build Compose command ─────────────────────────────────────────────────
COMPOSE_CMD="docker compose --project-directory . -f deploy/docker-compose.cloud.yml --profile ml"

if [ -n "$DOMAIN" ]; then
  info "Setting up Caddy TLS for ${DOMAIN}..."

  cat > deploy/Caddyfile <<CADDY
${DOMAIN} {
    # API routes
    @api {
        path /api/* /health /features /projects/*
    }
    handle @api {
        reverse_proxy core-ml:8000
    }
    # UI dev server (all other requests)
    handle {
        reverse_proxy ui:5173
    }
}
CADDY

  cat > deploy/docker-compose.caddy.yml <<CADDY
services:
  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ${DATA_DIR}/caddy:/data
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
    networks:
      - testsquad-net
    depends_on:
      - ui
      - core-ml
CADDY

  COMPOSE_CMD="${COMPOSE_CMD} -f deploy/docker-compose.caddy.yml"
fi

# ─── Start ──────────────────────────────────────────────────────────────────
info "Building and starting TestRadius..."
$COMPOSE_CMD up -d --build

# ─── Wait for health ───────────────────────────────────────────────────────
info "Waiting for core API..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    info "Core API ready"
    break
  fi
  sleep 2
done

echo ""
echo "================================================"
info "TestRadius is running!"
echo "================================================"
echo ""
echo "  UI:       http://${PUBLIC_IP:-localhost}:5173"
echo "  API:      http://${PUBLIC_IP:-localhost}:8000"
echo "  Neo4j:    http://${PUBLIC_IP:-localhost}:7474  (neo4j/testsquad_password)"
echo ""
if [ -n "$DOMAIN" ]; then
  echo "  TLS:      https://${DOMAIN}"
fi
echo ""
echo "  Logs:     $COMPOSE_CMD logs -f"
echo "  Stop:     $COMPOSE_CMD down"
echo "  Rebuild:  $COMPOSE_CMD up -d --build"
echo ""
