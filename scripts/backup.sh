#!/bin/sh
set -eu

backup_root="${TRADING_BACKUP_DIR:-./backups}"
retention_days="${TRADING_BACKUP_RETENTION_DAYS:-14}"
case "${backup_root}" in
  ""|"/"|"."|"..")
    printf '%s\n' "Refusing unsafe TRADING_BACKUP_DIR: ${backup_root}" >&2
    exit 2
    ;;
esac
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${backup_root}/${stamp}"

mkdir -p "${backup_dir}/minio"
docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-trading}" \
  -d "${POSTGRES_DB:-trading}" \
  --format=custom > "${backup_dir}/postgres.dump"

docker compose run --rm --no-deps \
  -v "${backup_dir}/minio:/backup" \
  --entrypoint /bin/sh minio-init -c \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --overwrite "local/$TRADING_MINIO_BUCKET" /backup'

(cd "${backup_dir}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
find "${backup_root}" -mindepth 1 -maxdepth 1 -type d -mtime "+${retention_days}" -exec rm -rf -- {} +
printf '%s\n' "Backup completed: ${backup_dir}"
