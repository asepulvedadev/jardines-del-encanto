#!/bin/sh
# This root-owned entrypoint is the only command accepted by the CI key.
exec /usr/bin/sudo -n /usr/local/libexec/jardines-deploy "${SSH_ORIGINAL_COMMAND:-}"
