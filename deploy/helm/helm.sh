#!/usr/bin/env bash
# Sevaro Pulse on Kubernetes with Helm. Future scope: nothing runs this yet; see
# deploy/helm/README.md. The current production path is deploy/aws/deploy.sh.
#
#   deploy/helm/helm.sh lint        helm lint the chart with default and example values
#   deploy/helm/helm.sh template    render manifests to stdout (pipe to kubectl apply --dry-run=server -f -)
#   deploy/helm/helm.sh diff        what an upgrade would change (needs the helm-diff plugin)
#   deploy/helm/helm.sh install     install or upgrade the release and wait for it to be ready
#   deploy/helm/helm.sh status      release status, pods, ingress, PVC
#   deploy/helm/helm.sh test        run `helm test` (backend /api/health + UI smoke check)
#   deploy/helm/helm.sh logs        recent logs (COMPONENT=backend|frontend, TAIL=200)
#   deploy/helm/helm.sh rollback    roll back to the previous revision (REVISION=n for a specific one)
#   deploy/helm/helm.sh uninstall   remove the release (the SQLite PVC is kept unless PURGE=1)
#
# Extra arguments are passed to helm, e.g.
#   deploy/helm/helm.sh install -f deploy/helm/sevaro-pulse/values-nginx.example.yaml
#
# Environment (all optional):
#   RELEASE=sevaro-pulse      Helm release name
#   NAMESPACE=sevaro-pulse    Kubernetes namespace (created on install)
#   KUBE_CONTEXT              kubectl/helm context; defaults to the current one
#   IMAGE_PREFIX              registry prefix, e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/sevaro-pulse
#   IMAGE_TAG                 image tag for both images; defaults to the git commit
#   TIMEOUT=10m               how long install waits for pods to become ready

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="$ROOT/deploy/helm/sevaro-pulse"
RELEASE="${RELEASE:-sevaro-pulse}"
NAMESPACE="${NAMESPACE:-sevaro-pulse}"
TIMEOUT="${TIMEOUT:-10m}"

log() { printf '\n==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_helm() {
  command -v helm >/dev/null || die "helm 3.8+ is required (brew install helm)"
}

require_cluster() {
  require_helm
  command -v kubectl >/dev/null || die "kubectl is required (brew install kubectl)"
  kubectl "${KCTX[@]+"${KCTX[@]}"}" version --request-timeout=10s >/dev/null 2>&1 \
    || die "cannot reach the cluster in context '${KUBE_CONTEXT:-$(kubectl config current-context 2>/dev/null || echo none)}'"
}

KCTX=()
HCTX=()
if [ -n "${KUBE_CONTEXT:-}" ]; then
  KCTX=(--context "$KUBE_CONTEXT")
  HCTX=(--kube-context "$KUBE_CONTEXT")
fi

default_tag() {
  local tag
  tag="$(git -C "$ROOT" rev-parse --short HEAD)"
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then tag="$tag-dirty-$(date +%Y%m%d%H%M%S)"; fi
  echo "$tag"
}

# --set flags for images, only when IMAGE_PREFIX / IMAGE_TAG are given (values files win otherwise).
image_args() {
  local args=()
  if [ -n "${IMAGE_PREFIX:-}" ]; then
    args+=(--set "backend.image.repository=$IMAGE_PREFIX/backend"
           --set "frontend.image.repository=$IMAGE_PREFIX/frontend")
  fi
  if [ -n "${IMAGE_TAG:-}" ]; then
    args+=(--set-string "backend.image.tag=$IMAGE_TAG" --set-string "frontend.image.tag=$IMAGE_TAG")
  fi
  printf '%s\n' "${args[@]+"${args[@]}"}"
}

read_image_args() {
  IMAGE_ARGS=()
  while IFS= read -r line; do [ -n "$line" ] && IMAGE_ARGS+=("$line"); done < <(image_args)
}

cmd_lint() {
  require_helm
  log "lint with default values"
  helm lint "$CHART" --strict "$@"
  for example in "$CHART"/values-*.example.yaml; do
    log "lint with $(basename "$example")"
    helm lint "$CHART" --strict -f "$example" "$@"
  done
  log "render check: SQLite with more than one backend replica must be refused"
  if helm template "$RELEASE" "$CHART" --set backend.replicaCount=2 >/dev/null 2>&1; then
    die "the chart accepted backend.replicaCount=2 with SQLite"
  fi
  echo "ok"
}

cmd_template() {
  require_helm
  read_image_args
  helm template "$RELEASE" "$CHART" --namespace "$NAMESPACE" \
    "${IMAGE_ARGS[@]+"${IMAGE_ARGS[@]}"}" "$@"
}

cmd_diff() {
  require_cluster
  helm plugin list | grep -q '^diff' \
    || die "install the helm-diff plugin: helm plugin install https://github.com/databus23/helm-diff"
  read_image_args
  helm "${HCTX[@]+"${HCTX[@]}"}" diff upgrade "$RELEASE" "$CHART" --namespace "$NAMESPACE" \
    --allow-unreleased "${IMAGE_ARGS[@]+"${IMAGE_ARGS[@]}"}" "$@"
}

cmd_install() {
  require_cluster
  IMAGE_TAG="${IMAGE_TAG:-$(default_tag)}"
  read_image_args
  log "release $RELEASE -> namespace $NAMESPACE, image tag $IMAGE_TAG"
  helm "${HCTX[@]+"${HCTX[@]}"}" upgrade --install "$RELEASE" "$CHART" \
    --namespace "$NAMESPACE" --create-namespace \
    --atomic --wait --timeout "$TIMEOUT" --history-max 10 \
    "${IMAGE_ARGS[@]+"${IMAGE_ARGS[@]}"}" "$@"
  cmd_status
}

cmd_status() {
  require_cluster
  helm "${HCTX[@]+"${HCTX[@]}"}" status "$RELEASE" --namespace "$NAMESPACE"
  log "workloads"
  kubectl "${KCTX[@]+"${KCTX[@]}"}" -n "$NAMESPACE" get deploy,pods,svc,ingress,pvc,hpa,pdb \
    -l "app.kubernetes.io/instance=$RELEASE" -o wide
}

cmd_test() {
  require_cluster
  helm "${HCTX[@]+"${HCTX[@]}"}" test "$RELEASE" --namespace "$NAMESPACE" --logs --timeout 2m
}

cmd_logs() {
  require_cluster
  local component="${COMPONENT:-backend}"
  kubectl "${KCTX[@]+"${KCTX[@]}"}" -n "$NAMESPACE" logs \
    -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=$component" \
    --tail "${TAIL:-200}" --prefix --all-containers "$@"
}

cmd_rollback() {
  require_cluster
  helm "${HCTX[@]+"${HCTX[@]}"}" rollback "$RELEASE" ${REVISION:+"$REVISION"} \
    --namespace "$NAMESPACE" --wait --timeout "$TIMEOUT"
  cmd_status
}

cmd_uninstall() {
  require_cluster
  helm "${HCTX[@]+"${HCTX[@]}"}" uninstall "$RELEASE" --namespace "$NAMESPACE" --wait
  if [ "${PURGE:-0}" = "1" ]; then
    log "PURGE=1: deleting the database PVC"
    kubectl "${KCTX[@]+"${KCTX[@]}"}" -n "$NAMESPACE" delete pvc \
      -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=backend" --ignore-not-found
  else
    echo "The SQLite PVC was kept. Delete it with PURGE=1 $0 uninstall, or kubectl delete pvc."
  fi
}

usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

command="${1:-}"
[ -n "$command" ] || { usage; exit 1; }
shift
case "$command" in
  lint|template|diff|install|status|test|logs|rollback|uninstall) "cmd_$command" "$@" ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
