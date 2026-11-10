#!/bin/bash
# Run as root from a reviewed, manually uploaded ops/ directory.
set -euo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $# == 1 && -f $1 ]] || { echo 'Usage: provision.sh <CI-public-key-file>' >&2; exit 2; }
key=$(cat "$1")
[[ $key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [a-zA-Z0-9@._-]+)?$ ]] || {
  echo 'Expected one Ed25519 public key' >&2; exit 2;
}
base=/srv/jardines-del-encanto
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
for binary in docker git python3 sudo curl; do command -v "$binary" >/dev/null; done
docker compose version >/dev/null
# Never install packages, restart daemons, change firewall policy or touch other apps.
install -d -m 0700 "$base" "$base/secrets" "$base/releases" "$base/backups" "$base/healthy"
install -d -m 0700 "$base/hermes"
chown 1000:1000 "$base/hermes"
if ! id jardines-deploy &>/dev/null; then
  useradd --create-home --home-dir /var/lib/jardines-deploy --shell /bin/sh jardines-deploy
fi
if id -nG jardines-deploy | grep -qw docker; then
  echo 'Refusing a deploy user with general Docker access' >&2; exit 1
fi
chown root:root /var/lib/jardines-deploy
chmod 0755 /var/lib/jardines-deploy
install -d -m 0755 -o root -g root /var/lib/jardines-deploy/.ssh
printf 'restrict,command="/usr/local/libexec/jardines-ssh" %s\n' "$key" > /var/lib/jardines-deploy/.ssh/authorized_keys
chmod 0644 /var/lib/jardines-deploy/.ssh/authorized_keys
chown root:root /var/lib/jardines-deploy/.ssh/authorized_keys
install -d -m 0755 /usr/local/libexec
install -m 0755 "$source_dir/ssh-gate.sh" /usr/local/libexec/jardines-ssh
install -m 0755 "$source_dir/deploy.py" /usr/local/libexec/jardines-deploy
printf 'jardines-deploy ALL=(root) NOPASSWD: /usr/local/libexec/jardines-deploy\n' > /etc/sudoers.d/jardines-deploy
chmod 0440 /etc/sudoers.d/jardines-deploy
visudo -cf /etc/sudoers.d/jardines-deploy
install -m 0600 "$source_dir/compose.yaml" "$base/compose.yaml"
install -m 0600 "$source_dir/hermes.compose.yaml" "$base/hermes.compose.yaml"
install -m 0600 "$source_dir/buildkitd.toml" "$base/buildkitd.toml"
if ! docker buildx inspect jardines-builder >/dev/null 2>&1; then
  docker buildx create --name jardines-builder --driver docker-container \
    --driver-opt 'image=moby/buildkit@sha256:c5f8862f52499773af85bc07695b2379ef08e8002352b0df2c4864c91d78dabe,memory=3g,memory-swap=3g,cpu-period=100000,cpu-quota=200000' \
    --buildkitd-config "$base/buildkitd.toml"
elif [[ ! -f $base/builder-provisioned ]]; then
  echo 'Refusing to adopt an existing builder with no project ownership marker' >&2; exit 1
fi
docker buildx inspect --bootstrap jardines-builder >/dev/null
docker update --pids-limit 512 buildx_buildkit_jardines-builder0 >/dev/null
touch "$base/builder-provisioned"
install -m 0755 "$source_dir/backup.sh" /usr/local/libexec/jardines-backup
install -m 0644 "$source_dir/jardines-backup.service" /etc/systemd/system/jardines-backup.service
install -m 0644 "$source_dir/jardines-backup.timer" /etc/systemd/system/jardines-backup.timer
systemctl daemon-reload
systemctl enable --now jardines-backup.timer
if [[ ! -f $base/secrets/db_password ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$base/secrets/db_password"
fi
# The parent is root-only. The mounted secret file must be readable by both app and DB UIDs.
chmod 0444 "$base/secrets/db_password"
if [[ ! -d $base/repository.git ]]; then
  git clone --bare https://github.com/asepulvedadev/jardines-del-encanto.git "$base/repository.git"
fi
echo 'Project provisioned. No existing service was restarted.'
