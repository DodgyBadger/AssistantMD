#!/bin/sh
set -eu

key_root=/run/assistantmd-shell
public_key_path="${key_root}/assistantmd_shell_client.pub"
host_key_path="${key_root}/ssh_host_ed25519_key"
authorized_keys_path=/run/sshd/authorized_keys
runtime_host_key_path=/run/sshd/ssh_host_ed25519_key

if [ ! -s "${public_key_path}" ]; then
    echo "Missing companion client public key: ${public_key_path}" >&2
    exit 1
fi

if [ ! -s "${host_key_path}" ]; then
    echo "Missing companion SSH host key: ${host_key_path}" >&2
    exit 1
fi

mkdir -p /run/sshd

public_key=$(sed -n '1p' "${public_key_path}")
case "${public_key}" in
    ssh-ed25519\ *) ;;
    *)
        echo "Companion client key must be one SSH Ed25519 public key." >&2
        exit 1
        ;;
esac

printf '%s %s\n' \
    'restrict,command="/usr/local/bin/assistantmd-shell-entry"' \
    "${public_key}" > "${authorized_keys_path}"

cp "${host_key_path}" "${runtime_host_key_path}"
chown root:root "${authorized_keys_path}" "${runtime_host_key_path}"
chmod 0644 "${authorized_keys_path}"
chmod 0600 "${runtime_host_key_path}"

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
