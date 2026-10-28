# create-cert.ps1 -- Windows PowerShell equivalent of create-cert.sh
# requires openssl in PATH and the private CA created by create-ca.ps1
param([switch]$Verbose)  # -v / -Verbose / --verbose prints the certificate details at the end
#
# prompt for the operator's amateur radio callsign; it names the CA that signs this cert
$callsign = Read-Host -Prompt "Enter your amateur radio callsign:"
# force lowercase so the CA file names are predictable
$callsign = $callsign.ToLower()
$caName = "${callsign}-root-ca"
#
# prompt for the subject name (hostname) of the certificate
# ($host is a PowerShell automatic variable, so use $hostname instead)
#
$hostname = Read-Host -Prompt "Enter hostname (subject name) for the certificate:"
# force lowercase; DNS names are case-insensitive and this keeps the cert predictable
$hostname = $hostname.ToLower()
#
# prompt for zero or more subject alternative names; a blank line ends input
#
$sanEntries = ""
while ($true) {
    $san = Read-Host -Prompt "Subject alternative name (blank to finish):"
    if (-not $san) { break }
    # same lowercase treatment as the subject name
    $san = $san.ToLower()
    if ($sanEntries) { $sanEntries += ", " }
    $sanEntries += "DNS:$san"
}
#
# generate private key for host.
# EC P-256, not RSA: the Pico W's mbedTLS cannot perform an RSA private key
# operation during the TLS handshake (the temporary bignum buffers exceed the
# MicroPython heap -- MBEDTLS_ERR_MPI_ALLOC_FAILED).  An ECDHE-ECDSA
# handshake needs only a few hundred bytes.
openssl ecparam -name prime256v1 -genkey -noout -out "$hostname.key.pem"
#
# convert key to DER
#
openssl ec -in "$hostname.key.pem" -outform DER -out "$hostname.key.der"
#
# create config file for signing
#
$extText = @"
[ req ]
days = 3652
default_md = sha256
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[ req_distinguished_name ]
CN = $hostname

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = CA:false
keyUsage = digitalSignature
"@
[System.IO.File]::WriteAllText("create_cert.ext", $extText)
#
# if any subject alternative names were given, include the subject name plus all of them
#
if ($sanEntries) {
    [System.IO.File]::AppendAllText("create_cert.ext", "subjectAltName = DNS:$hostname, $sanEntries`n")
}
#
# create signing request for host
openssl req -verbose -new -key "$hostname.key.pem" -out "$hostname.csr" -config create_cert.ext
#
# use private CA to sign this cert.
openssl x509 -req -in "$hostname.csr" -CA "$caName.crt" -CAkey "$caName.key" -days 3652 -sha256 -extfile create_cert.ext -extensions v3_ca -out "$hostname.crt.pem"
#
# make that certificate into a DER file
openssl x509 -inform PEM -in "$hostname.crt.pem" -outform DER -out "$hostname.crt.der" -extfile create_cert.ext
#
# remove the certificate signing request (.csr) file now
Remove-Item "$hostname.csr"
# and the openssl config file
Remove-Item create_cert.ext
# and the PEM copies of the key and certificate (only the DER files are needed)
Remove-Item "$hostname.key.pem", "$hostname.crt.pem"
#
# tell me about the new cert, if asked for
if ($Verbose) {
    openssl x509 -noout -text -inform DER -in "$hostname.crt.der"
}
# list the files this run created
Write-Host "Created: $hostname.key.der $hostname.crt.der"
