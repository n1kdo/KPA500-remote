#!/bin/bash
#
# -v / --verbose prints the certificate details at the end
#
verbose=false
case "${1:-}" in
  -v|--verbose) verbose=true ;;
esac
#
# prompt for the operator's amateur radio callsign; it becomes part of the CN
# and also the base name of the generated key/cert files
#
read -rp "Enter your amateur radio callsign: " callsign
# force lowercase so the CA file names are predictable
callsign="${callsign,,}"
cn="${callsign}-root-ca"
#
# refuse to overwrite an existing CA of the same name; a new key pair would
# invalidate every certificate already signed by the old CA
#
if [ -e "$cn.key" ] || [ -e "$cn.crt" ]; then
  echo "Refusing to overwrite existing CA '$cn' ($cn.key / $cn.crt already exist)." >&2
  exit 1
fi
#
# generate private key for this CA (deliberately not passphrase-encrypted)
#
openssl genrsa -out $cn.key 4096
#
# create config file for signing
#
cat > create_ca.ext <<EOF
[ req ]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[ req_distinguished_name ]
CN = ${cn}

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:true
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
EOF
#
# create certificate, 3653 days = ~10 years
openssl req -verbose -x509 -new -nodes -key $cn.key -sha256 -days 3653 -out $cn.crt -config create_ca.ext
#
# clean up the config file
#
rm create_ca.ext
#
# tell me about the cert, if asked for
#
if $verbose; then
  openssl x509 -noout -text -in $cn.crt
fi
#
# list the files this run created
#
echo "Created: $cn.key $cn.crt"

