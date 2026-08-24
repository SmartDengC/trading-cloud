#!/bin/sh
set -eu

backup_dir="${1:?usage: scripts/verify-backup.sh BACKUP_DIRECTORY}"
test -f "${backup_dir}/postgres.dump"
test -f "${backup_dir}/SHA256SUMS"
(cd "${backup_dir}" && sha256sum -c SHA256SUMS)
docker compose exec -T postgres pg_restore --list < "${backup_dir}/postgres.dump" >/dev/null
printf '%s\n' "Backup verified: ${backup_dir}"
