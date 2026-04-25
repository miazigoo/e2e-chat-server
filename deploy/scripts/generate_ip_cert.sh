#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <server-ip>" >&2
    exit 1
fi

SERVER_IP="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CERTS_DIR="${DEPLOY_DIR}/certs"
OPENSSL_CONFIG="${CERTS_DIR}/openssl-ip.cnf"

mkdir -p "${CERTS_DIR}"

cat > "${OPENSSL_CONFIG}" <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[req_distinguished_name]
CN = Secure Chat Local Root CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer

[server_req]
distinguished_name = server_distinguished_name
req_extensions = server_ext
prompt = no

[server_distinguished_name]
CN = ${SERVER_IP}

[server_ext]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
IP.1 = ${SERVER_IP}
EOF

openssl genrsa -out "${CERTS_DIR}/ca.key" 4096
openssl req -x509 -new -nodes \
    -key "${CERTS_DIR}/ca.key" \
    -sha256 \
    -days 3650 \
    -out "${CERTS_DIR}/ca.crt" \
    -config "${OPENSSL_CONFIG}" \
    -extensions v3_ca

openssl genrsa -out "${CERTS_DIR}/server.key" 4096
openssl req -new \
    -key "${CERTS_DIR}/server.key" \
    -out "${CERTS_DIR}/server.csr" \
    -config "${OPENSSL_CONFIG}" \
    -reqexts server_ext \
    -section server_req

openssl x509 -req \
    -in "${CERTS_DIR}/server.csr" \
    -CA "${CERTS_DIR}/ca.crt" \
    -CAkey "${CERTS_DIR}/ca.key" \
    -CAcreateserial \
    -out "${CERTS_DIR}/server.crt" \
    -days 825 \
    -sha256 \
    -extfile "${OPENSSL_CONFIG}" \
    -extensions server_ext

rm -f "${CERTS_DIR}/server.csr" "${CERTS_DIR}/ca.srl"

cat <<EOF
Generated certificates in ${CERTS_DIR}

Server certificate:
  ${CERTS_DIR}/server.crt
Server key:
  ${CERTS_DIR}/server.key
Root CA certificate to trust in Android:
  ${CERTS_DIR}/ca.crt
EOF
