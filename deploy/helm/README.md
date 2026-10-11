# Kubernetes (Helm): future scope

> **Status: not deployed.** This chart is groundwork for running Sevaro Pulse on a
> Kubernetes cluster later. The supported deployment today is one EC2 host with Docker
> Compose (`deploy/aws/deploy.sh`, see [docs/deployment.md](../../docs/deployment.md)).

## Shape

```
                 ┌──────────────────────────── namespace sevaro-pulse ────────────────────────────┐
browser ─▶ Ingress ─┬─ /api, /docs, /redoc, /openapi.json ─▶ Service backend :8000 ─▶ 1 pod (FastAPI)
                 │  │                                                          └─ PVC: SQLite /app/data
                 │  └─ everything else ─────────────────────▶ Service frontend :3000 ─▶ 2+ pods (Next.js)
                 └────────────────────────────────────────────────────────────────────────────────┘
```

It is the Compose stack translated one to one. The Ingress takes Caddy's place and keeps
the UI and the API on one origin, so the same images work unchanged: no CORS, and no
per-environment `NEXT_PUBLIC_API_BASE_URL`.

| Compose / Caddy | Chart |
| --- | --- |
| `backend` service, `backend-data` volume | `backend` Deployment (1 replica, `Recreate`), PVC at `/app/data` |
| `frontend` service | `frontend` Deployment (2 replicas, rolling), optional HPA, PDB |
| `deploy/Caddyfile` path routing | `Ingress` with prefix paths to each Service |
| Caddy automatic HTTPS | cert-manager (`values-nginx.example.yaml`) or ACM on an ALB (`values-eks.example.yaml`) |
| Docker `HEALTHCHECK` | startup, readiness and liveness probes (`/api/health`, `/`) |
| `.env` settings | `backend.config.*` values |

## Files

| File | Purpose |
| --- | --- |
| `sevaro-pulse/Chart.yaml` | chart metadata (`version` for the chart, `appVersion` = default image tag) |
| `sevaro-pulse/values.yaml` | every setting, with comments |
| `sevaro-pulse/values-nginx.example.yaml` | ingress-nginx, cert-manager TLS, HPA, NetworkPolicy |
| `sevaro-pulse/values-eks.example.yaml` | EKS: ECR images, ALB with an ACM certificate, gp3 EBS, arm64 nodes |
| `sevaro-pulse/templates/` | Deployments, Services, PVC, Ingress, HPA, PDB, NetworkPolicy, ServiceAccount, `helm test` pod |
| `helm.sh` | lint, template, diff, install/upgrade, status, test, logs, rollback, uninstall |

## Design decisions

- **One backend pod, on purpose.** SQLite has a single writer, and the analysis caches and
  the `/api/live` SSE stream are per process, the same reasons the Compose setup runs one
  uvicorn worker. The chart refuses `backend.replicaCount > 1` unless
  `backend.database.external.enabled` is set. Upgrades use `Recreate`, so the API is
  briefly down during a rollout. The frontend is stateless and scales freely.
- **The database survives `helm uninstall`.** The PVC carries `helm.sh/resource-policy: keep`.
  `PURGE=1 deploy/helm/helm.sh uninstall` deletes it.
- **Hardened pods.** Non-root (uid 10001 backend, 1000 frontend), read-only root filesystem
  with `emptyDir` for `/tmp` and `.next/cache`, all capabilities dropped, `RuntimeDefault`
  seccomp, no service account token.
- **SSE works without tuning.** `/api/live` already sends `X-Accel-Buffering: no`, and its
  streams end after 20 seconds and reconnect, so default proxy timeouts are enough.
- **`NEXT_PUBLIC_*` settings are build-time.** They are inlined into the browser bundle, so
  they are image build arguments, not chart values.

## Usage (when a cluster exists)

Prerequisites: `helm` 3.8+, `kubectl`, a cluster with an Ingress controller and a default
StorageClass, and the two images pushed to a registry the cluster can pull from (the ECR
repositories from `deploy/aws/cloudformation.yml` work; `deploy/aws/deploy.sh push` builds
and pushes them).

```bash
deploy/helm/helm.sh lint
```

```bash
deploy/helm/helm.sh template -f deploy/helm/sevaro-pulse/values-nginx.example.yaml
```

```bash
IMAGE_PREFIX=123456789012.dkr.ecr.us-east-1.amazonaws.com/sevaro-pulse deploy/helm/helm.sh install -f my-values.yaml
```

`install` runs `helm upgrade --install --atomic --wait`, so a failed rollout rolls itself
back. `IMAGE_TAG` defaults to the current git commit, matching `deploy/aws/deploy.sh`. Then:

```bash
deploy/helm/helm.sh test
```

```bash
COMPONENT=backend deploy/helm/helm.sh logs
```

Settings for `helm.sh`: `RELEASE`, `NAMESPACE` (both default `sevaro-pulse`),
`KUBE_CONTEXT`, `IMAGE_PREFIX`, `IMAGE_TAG`, `TIMEOUT`. Arguments after the command go to
helm, so `-f`, `--set` and `--dry-run` all work.

## Before running more than one backend pod

1. Move to Postgres: add a driver such as `psycopg[binary]` to `backend/requirements.txt`,
   replace the rebuild-on-schema-change in `init_db` with migrations, then set
   `backend.database.external.enabled=true` with `existingSecret` holding `DATABASE_URL`.
2. Decide on shared caches. `AnalysisCache` is per process; each replica would compute its own.
3. Raise `backend.replicaCount`. The Deployment then switches to a rolling update, and
   the PVC is no longer created.
