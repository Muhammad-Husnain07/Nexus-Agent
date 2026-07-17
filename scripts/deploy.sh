#!/usr/bin/env bash
# =============================================================================
# Nexus Agent — Deploy Script
#
# Builds the Docker image, pushes to registry, and applies k8s manifests.
#
# Usage:
#   REGISTRY=myregistry.io TAG=v1.0 ./scripts/deploy.sh
#
# Environment variables:
#   REGISTRY  — Container registry (default: nexus-agent)
#   TAG       — Image tag (default: latest)
#   KUBECONFIG — Path to kubeconfig (optional)
# =============================================================================
set -euo pipefail

REGISTRY="${REGISTRY:-nexus-agent}"
TAG="${TAG:-latest}"
IMAGE="$REGISTRY:$TAG"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Building Docker image: $IMAGE"
docker build -f "$DIR/docker/Dockerfile" -t "$IMAGE" "$DIR"

echo "==> Pushing image: $IMAGE"
docker push "$IMAGE"

echo "==> Updating k8s manifests with image tag"
sed -i.bak "s|image: .*|image: $IMAGE|" "$DIR/deploy/k8s/deployment.yaml"
rm -f "$DIR/deploy/k8s/deployment.yaml.bak"

echo "==> Applying k8s manifests"
kubectl apply -f "$DIR/deploy/k8s/"

echo "==> Restarting deployment"
kubectl rollout restart deployment/nexus-agent
kubectl rollout status deployment/nexus-agent --timeout=120s

echo "==> Done! Nexus Agent deployed: $IMAGE"
