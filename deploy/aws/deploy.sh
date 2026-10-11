#!/usr/bin/env bash
# Deploy Sevaro Pulse to one EC2 host on AWS. Full guide: docs/deployment.md
#
#   deploy/aws/deploy.sh up        infra + push + release (first deploy, and every deploy after)
#   deploy/aws/deploy.sh infra     create/update the CloudFormation stack (ECR, EC2, IP, IAM)
#   deploy/aws/deploy.sh push      build images for the instance's CPU and push them to ECR
#   deploy/aws/deploy.sh release   roll the host to an image tag (default: newest in ECR)
#   deploy/aws/deploy.sh status    stack outputs and container health
#   deploy/aws/deploy.sh logs      recent container logs (TAIL=200, SERVICE=backend)
#   deploy/aws/deploy.sh destroy   delete everything, including the database
#
# Environment (all optional):
#   AWS_REGION / AWS_PROFILE   which account and region (falls back to `aws configure`)
#   STACK_NAME=sevaro-pulse    lowercase; also the ECR repository prefix
#   IMAGE_TAG                  defaults to the git commit (+ -dirty-<time> if uncommitted)
# Stack settings, applied by `infra`/`up` when set and remembered by the stack otherwise:
#   SITE_ADDRESS               :80 (HTTP on the IP) or a domain whose A record points at the
#                              stack's IP, which turns on automatic HTTPS
#   ALLOWED_CIDR               who may reach ports 80/443 (default 0.0.0.0/0)
#   INSTANCE_TYPE              default t4g.small; see deploy/aws/cloudformation.yml
#   VPC_ID / SUBNET_ID         a specific VPC and public subnet instead of the default VPC

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$ROOT/deploy/aws/cloudformation.yml"
STACK_NAME="${STACK_NAME:-sevaro-pulse}"
REMOTE_DIR=/opt/sevaro-pulse

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require() {
  command -v aws >/dev/null || die "the AWS CLI v2 is required (brew install awscli)"
  AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region || true)}}"
  [ -n "$AWS_REGION" ] || die "set AWS_REGION (or run: aws configure)"
  export AWS_REGION
  aws sts get-caller-identity --query Account --output text >/dev/null \
    || die "AWS credentials are not configured (run: aws configure, or aws sso login)"
}

output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null \
    || die "stack $STACK_NAME not found in $AWS_REGION (run: $0 infra)"
}

default_tag() {
  local tag
  tag="$(git -C "$ROOT" rev-parse --short HEAD)"
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then tag="$tag-dirty-$(date +%Y%m%d%H%M%S)"; fi
  echo "$tag"
}

latest_pushed_tag() {
  aws ecr describe-images --repository-name "$STACK_NAME/backend" \
    --query 'sort_by(imageDetails[?imageTags], &imagePushedAt)[-1].imageTags[0]' --output text
}

ecr_login() {
  aws ecr get-login-password | docker login --username AWS --password-stdin "${1%%/*}" >/dev/null
}

# Run a shell script on the instance through SSM Run Command and print its output.
remote() {
  local instance comment="$1" script="$2" id status
  instance="$(output InstanceId)"
  for _ in $(seq 1 30); do
    status="$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$instance" \
      --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)"
    [ "$status" = "Online" ] && break
    echo "waiting for the SSM agent on $instance ($status)..."
    sleep 10
  done
  [ "$status" = "Online" ] || die "SSM agent on $instance is not online"

  id="$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
    --comment "$comment" --timeout-seconds 900 \
    --parameters "$(jq -n --arg s "$script" '{commands: [$s], executionTimeout: ["900"]}')" \
    --query Command.CommandId --output text)"
  aws ssm wait command-executed --command-id "$id" --instance-id "$instance" 2>/dev/null || true
  invocation() {
    aws ssm get-command-invocation --command-id "$id" --instance-id "$instance" \
      --query "$1" --output text
  }
  invocation StandardOutputContent
  invocation StandardErrorContent >&2
  status="$(invocation Status)"
  [ "$status" = "Success" ] || die "remote command '$comment' finished with status $status"
}

cmd_infra() {
  log "Deploying CloudFormation stack $STACK_NAME in $AWS_REGION"
  # Unset parameters keep the stack's current value (or the template default on create), so
  # a later plain `up` never resets a narrowed ALLOWED_CIDR or a domain back to the defaults.
  local args=(--stack-name "$STACK_NAME" --template-file "$TEMPLATE"
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset)
  local params=()
  if [ -n "${SITE_ADDRESS:-}" ]; then params+=("SiteAddress=$SITE_ADDRESS"); fi
  if [ -n "${ALLOWED_CIDR:-}" ]; then params+=("AllowedCidr=$ALLOWED_CIDR"); fi
  if [ -n "${INSTANCE_TYPE:-}" ]; then params+=("InstanceType=$INSTANCE_TYPE"); fi
  if [ -n "${VPC_ID:-}" ]; then params+=("VpcId=$VPC_ID"); fi
  if [ -n "${SUBNET_ID:-}" ]; then params+=("SubnetId=$SUBNET_ID"); fi
  if [ ${#params[@]} -gt 0 ]; then args+=(--parameter-overrides "${params[@]}"); fi
  aws cloudformation deploy "${args[@]}"
  echo "Public IP: $(output PublicIp)  Site address: $(output SiteAddress)"
}

cmd_push() {
  local tag="$1" prefix platform
  command -v docker >/dev/null || die "Docker is required"
  prefix="$(output ImagePrefix)"
  case "$(output Architecture)" in
    arm64) platform=linux/arm64 ;;
    *) platform=linux/amd64 ;;
  esac
  log "Building $platform images tagged $tag and pushing to $prefix"
  ecr_login "$prefix"
  docker buildx build --platform "$platform" --provenance=false --push \
    -t "$prefix/backend:$tag" "$ROOT/backend"
  docker buildx build --platform "$platform" --provenance=false --push \
    --build-arg "NEXT_PUBLIC_STATUS_POLL_MS=${NEXT_PUBLIC_STATUS_POLL_MS:-15000}" \
    -t "$prefix/frontend:$tag" "$ROOT/frontend"
}

# The compose file, Caddyfile and server .env as a base64 tarball (small enough to travel
# inside the SSM command itself, so the host needs no S3 bucket or git checkout).
release_bundle() (
  local prefix="$1" tag="$2" site="$3" stage
  stage="$(mktemp -d)"
  trap 'rm -rf "$stage"' EXIT
  mkdir -p "$stage/deploy"
  cp "$ROOT/docker-compose.yml" "$stage/"
  cp "$ROOT/deploy/Caddyfile" "$stage/deploy/"
  cat >"$stage/.env" <<EOF
IMAGE_PREFIX=$prefix
IMAGE_TAG=$tag
SITE_ADDRESS=$site
APP_ENV=production
CORS_ORIGINS=${CORS_ORIGINS:-}
SIMULATION_REFERENCE_TIME=${SIMULATION_REFERENCE_TIME:-}
EOF
  # Separate gzip: macOS tar pads its own gzip stream, which GNU tar rejects as trailing garbage.
  COPYFILE_DISABLE=1 tar --format ustar -C "$stage" -cf - docker-compose.yml deploy/Caddyfile .env \
    | gzip -9n | base64 | tr -d '\n'
)

cmd_release() {
  local tag="$1" prefix bundle
  prefix="$(output ImagePrefix)"
  [ -n "$tag" ] && [ "$tag" != "None" ] || die "no image in ECR yet (run: $0 push)"
  log "Releasing $tag to $(output InstanceId)"
  bundle="$(release_bundle "$prefix" "$tag" "$(output SiteAddress)")"

  remote "release $tag" "set -euo pipefail
mkdir -p $REMOTE_DIR && cd $REMOTE_DIR
echo '$bundle' | base64 -d | tar --no-same-owner -xzf -
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin ${prefix%%/*}
docker compose pull --quiet
docker compose up -d --no-build --remove-orphans --wait --wait-timeout 180
docker image prune -af >/dev/null
docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'"

  log "Live at $(output Url)"
}

cmd_status() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text
  remote "status" "cd $REMOTE_DIR && docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}' && grep IMAGE_TAG .env"
}

cmd_logs() {
  remote "logs" "cd $REMOTE_DIR && docker compose logs --no-color --tail ${TAIL:-200} ${SERVICE:-}"
}

cmd_destroy() {
  echo "This deletes stack $STACK_NAME in $AWS_REGION: the instance, its database, the IP and ECR images."
  read -r -p "Type the stack name to confirm: " answer
  [ "$answer" = "$STACK_NAME" ] || die "aborted"
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  echo "Deleted."
}

main() {
  local command="${1:-}"
  [ -n "$command" ] || { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 1; }
  command -v jq >/dev/null || die "jq is required (brew install jq)"
  require
  case "$command" in
    up)
      local tag="${IMAGE_TAG:-$(default_tag)}"
      cmd_infra
      cmd_push "$tag"
      cmd_release "$tag"
      ;;
    infra) cmd_infra ;;
    push) cmd_push "${IMAGE_TAG:-$(default_tag)}" ;;
    release) cmd_release "${IMAGE_TAG:-$(latest_pushed_tag)}" ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    destroy) cmd_destroy ;;
    *) die "unknown command: $command (run $0 for help)" ;;
  esac
}

main "$@"
