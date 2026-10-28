#!/bin/bash
#
# -v / --verbose prints the certificate details at the end
#
verbose=false
case "${1:-}" in
  -v|--verbose) verbose=true ;;
esac
#
# prompt for the operator's amateur radio callsign; it names the CA that signs this cert
read -rp "Enter your amateur radio callsign: " callsign
# force lowercase so the CA file names are predictable
callsign="${callsign,,}"
ca_name="${callsign}-root-ca"
#
# prompt for the subject name (hostname) of the certificate
#
read -rp "Enter hostname (subject name) for the certificate: " host
# force lowercase; DNS names are case-insensitive and this keeps the cert predictable
host="${host,,}"
#
# prompt for zero or more subject alternative names; a blank line ends input
#
san_entries=""
while :; do
  read -rp "Subject alternative name (blank to finish): " san
  [ -z "$san" ] && break
  # same lowercase treatment as the subject name
  san="${san,,}"
  san_entries="${san_entries:+$san_entries, }DNS:$san"
done
#
# generate private key for host.
# EC P-256, not RSA: the Pico W's mbedTLS cannot perform an RSA private key
# operation during the TLS handshake (the temporary bignum buffers exceed the
# MicroPython heap -- MBEDTLS_ERR_MPI_ALLOC_FAILED).  An ECDHE-ECDSA
# handshake needs only a few hundred bytes.
openssl ecparam -name prime256v1 -genkey -noout -out $host.key.pem
#
# convert key to DER
#
openssl ec -in $host.key.pem -outform DER -out $host.key.der
#
# create config file for signing
#
cat > create_cert.ext <<EOF
[ req ]
days = 3652
default_md = sha256
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[ req_distinguished_name ]
CN = ${host}

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = CA:false
keyUsage = digitalSignature
EOF
#
# if any subject alternative names were given, include the subject name plus all of them
#
if [ -n "$san_entries" ]; then
  echo "subjectAltName = DNS:${host}, ${san_entries}" >> create_cert.ext
fi
#
# create signing request for host
#
openssl req -verbose -new -key $host.key.pem -out $host.csr -config create_cert.ext
#
# use private CA to sign this cert.
#
openssl x509 -req -in $host.csr -CA $ca_name.crt -CAkey $ca_name.key -days 3652 -sha256 -extfile create_cert.ext -extensions v3_ca -out $host.crt.pem
#
# make that certificate into a DER file
#
openssl x509 -inform PEM -in $host.crt.pem -outform DER -out $host.crt.der -extfile create_cert.ext
#
# remove the certificate signing request (.csr) file now
#
rm $host.csr
# and the openssl config file
#
rm create_cert.ext
# and the PEM copies of the key and certificate (only the DER files are needed)
#
rm $host.key.pem $host.crt.pem
#
# tell me about the new cert, if asked for
#
if $verbose; then
  openssl x509 -noout -text -inform DER -in $host.crt.der
fi
#
# list the files this run created
#
echo "Created: $host.key.der $host.crt.der"

