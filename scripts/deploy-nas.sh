#!/usr/bin/env bash
set -euo pipefail

# deploy-nas.sh - Automated NAS deployment script for MyMarkItDown (mdbridge)
# Usage: [NAS_HOST=user@host] [NAS_DIR=...] [NAS_DOCKER=...] ./scripts/deploy-nas.sh [flags]

NAS_HOST="${NAS_HOST:-}"
NAS_DIR="${NAS_DIR:-/srv/docker/mdbridge}"
NAS_DOCKER="${NAS_DOCKER:-docker}"

SKIP_TESTS=false
DRY_RUN=false

usage() {
  cat <<EOF
Usage: [NAS_HOST=user@host] $(basename "$0") [options]

Deploy MyMarkItDown container to an OpenMediaVault NAS.

Environment Variables:
  NAS_HOST      Target SSH host (required, e.g. user@192.168.50.174)
  NAS_DIR       Target deploy directory on NAS (default: /srv/docker/mdbridge)
  NAS_DOCKER    Docker command on NAS (default: docker, e.g. "sudo docker")

Options:
  --skip-tests  Skip local pytest and ruff checks before deployment
  --dry-run     Print the deployment plan without executing commands
  -h, --help    Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tests)
      SKIP_TESTS=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown option $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$NAS_HOST" ]]; then
  echo "Error: NAS_HOST environment variable is required (e.g. NAS_HOST=user@192.168.50.174)." >&2
  usage >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Step a: Run local tests and linting unless --skip-tests
if [[ "$SKIP_TESTS" == "false" ]]; then
  echo "==> Running tests and lint checks..."
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] uv run pytest -q && uv run ruff check ."
  else
    uv run pytest -q
    uv run ruff check .
  fi
else
  echo "==> Skipping local test checks (--skip-tests specified)."
fi

# Step b: Fail fast - verify proxy-network exists on the NAS before building or copying
echo "==> Checking for proxy-network on $NAS_HOST..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] ssh \"$NAS_HOST\" \"$NAS_DOCKER network inspect proxy-network >/dev/null 2>&1\""
else
  if ! ssh "$NAS_HOST" "$NAS_DOCKER network inspect proxy-network >/dev/null 2>&1"; then
    echo "Error: Required external network 'proxy-network' does not exist on $NAS_HOST." >&2
    echo "Create it on the NAS first: $NAS_DOCKER network create proxy-network" >&2
    exit 1
  fi
fi

# Step c: Determine version tag (append -dirty if working tree is uncommitted)
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "dev")
if [[ -z "$GIT_SHA" ]]; then
  GIT_SHA="dev"
fi

IS_DIRTY=false
if git rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
    IS_DIRTY=true
    echo "Warning: Git working tree is dirty (uncommitted changes present)." >&2
  fi
fi

if [[ "$GIT_SHA" == "dev" ]]; then
  TAG="dev"
elif [[ "$IS_DIRTY" == "true" ]]; then
  TAG="${GIT_SHA}-dirty"
else
  TAG="${GIT_SHA}"
fi

# Step d: Build linux/amd64 image
BUILD_CMD="docker buildx build --platform linux/amd64 -t mdbridge:latest -t mdbridge:${TAG} --load ."
echo "==> Building linux/amd64 Docker image (tags: latest, ${TAG})..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] $BUILD_CMD"
else
  eval "$BUILD_CMD"
fi

# Step e: Save and transfer images via SSH (preserving both latest and version tag)
TRANSFER_CMD="docker save mdbridge:latest mdbridge:${TAG} | gzip | ssh \"$NAS_HOST\" \"gunzip | $NAS_DOCKER load\""
echo "==> Transferring Docker images (latest, ${TAG}) to $NAS_HOST..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] $TRANSFER_CMD"
else
  docker save mdbridge:latest "mdbridge:${TAG}" | gzip | ssh "$NAS_HOST" "gunzip | $NAS_DOCKER load"
fi

# Step f: Remote directory setup, copy compose and .env guard
echo "==> Setting up remote directory and configuration in $NAS_HOST:$NAS_DIR..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] ssh \"$NAS_HOST\" \"mkdir -p '$NAS_DIR'\""
  echo "[DRY-RUN] scp docker-compose.yml \"$NAS_HOST:$NAS_DIR/docker-compose.yml\""
  echo "[DRY-RUN] scp .env.example \"$NAS_HOST:$NAS_DIR/.env.example\""
  echo "[DRY-RUN] ssh \"$NAS_HOST\" \"if [ ! -f '$NAS_DIR/.env' ]; then cp '$NAS_DIR/.env.example' '$NAS_DIR/.env'; fi\""
else
  ssh "$NAS_HOST" "mkdir -p '$NAS_DIR'"
  scp docker-compose.yml "$NAS_HOST:$NAS_DIR/docker-compose.yml"
  scp .env.example "$NAS_HOST:$NAS_DIR/.env.example"
  ssh "$NAS_HOST" "if [ ! -f '$NAS_DIR/.env' ]; then cp '$NAS_DIR/.env.example' '$NAS_DIR/.env'; fi"
fi

# Step g: Compose up -d --force-recreate
COMPOSE_CMD="cd '$NAS_DIR' && $NAS_DOCKER compose up -d --force-recreate"
echo "==> Starting container with compose up -d --force-recreate..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] ssh \"$NAS_HOST\" \"$COMPOSE_CMD\""
else
  ssh "$NAS_HOST" "$COMPOSE_CMD"
fi

# Step h: Poll health status up to 120s
HEALTH_CMD="ssh \"$NAS_HOST\" \"$NAS_DOCKER inspect -f '{{.State.Health.Status}}' mdbridge\""
echo "==> Polling container health (up to 120s)..."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[DRY-RUN] $HEALTH_CMD"
else
  elapsed=0
  healthy=false
  while [[ $elapsed -lt 120 ]]; do
    status=$(ssh "$NAS_HOST" "$NAS_DOCKER inspect -f '{{.State.Health.Status}}' mdbridge 2>/dev/null" || echo "starting")
    if [[ "$status" == "healthy" ]]; then
      healthy=true
      break
    fi
    sleep 2
    elapsed=$(( elapsed + 2 ))
  done

  if [[ "$healthy" == "true" ]]; then
    echo "Container mdbridge is healthy!"
  else
    echo "Error: Container mdbridge failed to become healthy within 120s." >&2
    echo "Fetching container logs:" >&2
    ssh "$NAS_HOST" "$NAS_DOCKER logs --tail 50 mdbridge" >&2 || true
    exit 1
  fi
fi

echo "Deployed mdbridge:${TAG}"
