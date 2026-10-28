# create-ca.ps1 -- Windows PowerShell equivalent of create-ca.sh
# requires openssl in PATH
param([switch]$Verbose)  # -v / -Verbose / --verbose prints the certificate details at the end
#
# prompt for the operator's amateur radio callsign; it becomes part of the CN
# and also the base name of the generated key/cert files
#
$callsign = Read-Host -Prompt "Enter your amateur radio callsign:"
# force lowercase so the CA file names are predictable
$callsign = $callsign.ToLower()
$cn = "${callsign}-root-ca"
# refuse to overwrite an existing CA of the same name; a new key pair would
# invalidate every certificate already signed by the old CA
if ((Test-Path "$cn.key") -or (Test-Path "$cn.crt")) {
    Write-Error "Refusing to overwrite existing CA '$cn' ('$cn.key' / '$cn.crt' already exist)."
    exit 1
}
#
# generate private key for this CA (deliberately not passphrase-encrypted)
#
openssl genrsa -out "$cn.key" 4096
#
# create config file for signing
#
$extText = @"
[ req ]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[ req_distinguished_name ]
CN = $cn

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:true
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
"@
[System.IO.File]::WriteAllText("create_ca.ext", $extText)
#
# create certificate, 3653 days = ~10 years
openssl req -verbose -x509 -new -nodes -key "$cn.key" -sha256 -days 3653 -out "$cn.crt" -config create_ca.ext
#
# clean up the config file
#
Remove-Item create_ca.ext
#
# tell me about the cert, if asked for
if ($Verbose) {
    openssl x509 -noout -text -in "$cn.crt"
}
# list the files this run created
Write-Host "Created: $cn.key $cn.crt"
