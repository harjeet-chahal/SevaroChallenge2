# Deployment: Docker and AWS

## Shape

```
              ┌──────────────────────── one host (EC2, or your laptop) ───────────────────────┐
browser ─:80/:443─▶ caddy ─┬─ /api/*, /docs, /openapi.json ─▶ backend :8000 (FastAPI, 1 worker)
              │            │                                    └─ volume backend-data: SQLite
              │            └─ everything else ────────────────▶ frontend :3000 (Next standalone)
              └───────────────────────────────────────────────────────────────────────────────┘
```

- **One origin.** Caddy serves the UI and the API on the same host name. The browser needs
  no CORS, and the frontend image is built with an empty `NEXT_PUBLIC_API_BASE_URL`, so it
  calls `/api` relative to wherever it is served. One image works on any domain or IP.
- **One host, on purpose.** The database is SQLite (single writer), and the analysis
  caches and the `/api/live` SSE stream are per process. The backend therefore runs as a
  single uvicorn worker on a single machine, with the database on a Docker volume. To run
  more than one replica you would first move to Postgres (see [Scaling](#scaling-beyond-one-host)).
- **HTTPS is automatic** once `SITE_ADDRESS` is a domain that points at the host: Caddy
  obtains and renews a Let's Encrypt certificate and keeps it in the `caddy-data` volume.

| File | Purpose |
| --- | --- |
| `backend/Dockerfile` | Python 3.12 slim, non-root, `/api/health` health check, data in `/app/data` |
| `frontend/Dockerfile` | Node 24 slim, Next.js standalone server (`BUILD_STANDALONE=1`), non-root |
| `docker-compose.yml` | backend + frontend + Caddy, named volumes, log rotation, health-gated start |
| `deploy/Caddyfile` | path routing, compression (never on the SSE stream), basic security headers |
| `.env.example` | compose settings (site address, ports, image names) |
| `deploy/aws/cloudformation.yml` | ECR repositories, EC2 host, Elastic IP, security group, IAM role |
| `deploy/aws/deploy.sh` | provision, build and push, roll out over SSM, status, logs, destroy |

## Run with Docker locally

```bash
docker compose up --build
```

Open http://localhost and load a sample from the dataset drawer. If port 80 is taken, copy
`.env.example` to `.env` and set `HTTP_PORT=8088` (and `HTTPS_PORT=8448`). Stop with
`docker compose down`. Add `-v` to also delete the database and certificate volumes.

The images don't depend on your local `backend/.env` or `frontend/.env.local`: both are
excluded from the build context, and so are local databases and dataset drops.

## Deploy to AWS

### What gets created

`deploy/aws/cloudformation.yml` creates one stack (default name `sevaro-pulse`):

- **ECR**: `sevaro-pulse/backend` and `sevaro-pulse/frontend` (scan on push, keep the last 10
  images, emptied when the stack is deleted).
- **EC2**: Amazon Linux 2023 on `t4g.small` (Graviton, 2 vCPU, 2 GiB, plus 2 GiB swap),
  20 GiB encrypted gp3 root volume, Docker and the Compose plugin installed at boot.
- **Elastic IP**, so the address survives stops and starts.
- **Security group**: inbound 80/tcp, 443/tcp and 443/udp from `AllowedCidr`. **No SSH.**
  Shell access and rollouts go through AWS Systems Manager.
- **IAM role** for the instance: `AmazonSSMManagedInstanceCore` and
  `AmazonEC2ContainerRegistryReadOnly`.

Rough cost in us-east-1: about $12/month for the instance, $3.60 for the public IPv4
address and $1.60 for the volume, so **about $18/month** while it exists. Delete the stack
when the demo is over.

### Prerequisites

- AWS CLI v2 with credentials (`aws configure` or `aws sso login`), Docker (with buildx,
  included in Docker Desktop) and `jq`.
- An identity that can manage CloudFormation, EC2, IAM roles and instance profiles, ECR and
  SSM Run Command. `AdministratorAccess` is the simple choice for a hackathon account.
- A default VPC in the region, or pass `VPC_ID` and `SUBNET_ID` (a public subnet).

### First deploy

```bash
deploy/aws/deploy.sh up
```

`up` runs three steps, which you can also run on their own:

1. **`infra`**: creates or updates the stack and waits until the instance has signalled that
   Docker is ready (about 3 to 5 minutes the first time).
2. **`push`**: builds both images for the instance's CPU (`linux/arm64` for t4g, native and
   fast on Apple Silicon) and pushes them to ECR. The tag is the git commit, plus
   `-dirty-<timestamp>` when the working tree has uncommitted changes, so every push is unique.
3. **`release`**: sends `docker-compose.yml`, `deploy/Caddyfile` and a generated `.env` to
   `/opt/sevaro-pulse` on the instance over SSM Run Command, logs in to ECR, pulls, starts
   the stack, waits for every health check and prunes old images.

It ends by printing the URL (`http://<elastic-ip>`). Open the coordinator view and load a
sample or upload the judging ZIP, as you would locally.

### Updating

Run `deploy/aws/deploy.sh up` again. The stack is unchanged unless you changed a setting.
The images are rebuilt and the containers are replaced. The database volume is kept, so the
loaded dataset and workflow state survive. If a release changes the database schema, the
backend rebuilds its tables on startup (see `SCHEMA_VERSION` in `backend/app/db/session.py`)
and the dataset has to be loaded again.

To roll back, release an earlier tag (`deploy/aws/deploy.sh status` shows the current one):

```bash
IMAGE_TAG=<older-tag> deploy/aws/deploy.sh release
```

### HTTPS with a domain

1. Create a DNS `A` record for your name (e.g. `pulse.example.com`) pointing at the stack's
   `PublicIp` output.
2. Once it resolves, run:

   ```bash
   SITE_ADDRESS=pulse.example.com deploy/aws/deploy.sh up
   ```

Caddy obtains the certificate when it starts and redirects HTTP to HTTPS. If DNS wasn't
ready yet, it keeps retrying in the background. The stack remembers `SITE_ADDRESS`, so later
deploys don't need it again. Without a domain of your own, `<ip-with-dashes>.sslip.io`
(e.g. `3-91-10-20.sslip.io`) resolves to the IP and usually works the same way, subject to
Let's Encrypt rate limits on that shared domain.

### Restricting access

The app has no login. Roles are simulated with `X-Demo-Role`, so anyone who can reach the
URL can load datasets, advance the clock and approve offers. Unless the demo has to be
public, limit it to known addresses:

```bash
ALLOWED_CIDR=203.0.113.7/32 deploy/aws/deploy.sh infra
```

Like `SITE_ADDRESS` and `INSTANCE_TYPE`, the stack remembers this value until you set it again.

### Operating

```bash
deploy/aws/deploy.sh status                  # stack outputs, container health, deployed tag
deploy/aws/deploy.sh logs                    # last 200 lines from every service
SERVICE=backend TAIL=500 deploy/aws/deploy.sh logs
```

For a shell on the host, install the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
(`brew install --cask session-manager-plugin`) and run
`aws ssm start-session --target <InstanceId>`. Then:

```bash
cd /opt/sevaro-pulse
sudo docker compose ps
sudo docker compose logs -f backend
sudo docker compose restart backend
```

- **Reset all data:** load a sample or upload a dataset from the UI, which replaces the
  dataset and workflow state. To wipe everything, run
  `sudo docker compose down && sudo docker volume rm sevaro-pulse_backend-data && sudo docker compose up -d`.
- **Backups:** the database is a single file in the `sevaro-pulse_backend-data` volume on the
  root EBS volume. An EBS snapshot of the instance's volume is the simplest backup.
- **Reboots:** Docker starts on boot and every service uses `restart: unless-stopped`.

### Tearing down

```bash
deploy/aws/deploy.sh destroy
```

Deletes the stack: the instance and its database, the Elastic IP, the security group, the
IAM role and both ECR repositories with their images. It asks you to type the stack name first.

## Scaling beyond one host

The current design deliberately runs everything on one machine, which keeps it simple and
correct with SQLite. A multi-replica deployment (for example ECS Fargate behind an ALB)
would need:

1. **Postgres (RDS) instead of SQLite.** Set `DATABASE_URL`, add a driver such as
   `psycopg[binary]`, and replace the rebuild-on-schema-change in `init_db` with migrations.
2. **Shared or versioned caches.** `AnalysisCache` is per process. It is keyed by data
   version, so stale entries are unlikely, but each replica computes its own.
3. **ALB path routing** in place of Caddy (`/api/*`, `/docs`, `/openapi.json` to the backend
   target group). The ALB's default 60-second idle timeout already covers the SSE streams,
   which end after 20 seconds and reconnect.

The images are ready for that already. They are stateless apart from `/app/data`, take
their configuration from environment variables and expose HTTP health checks.
