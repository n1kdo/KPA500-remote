#
# Windows twin of create-ca.sh, using only stock Windows/PowerShell built-ins
# (New-SelfSignedCertificate + Export-Certificate).
#
# -verbose prints the certificate details at the end.
#
# Must be run from an elevated (Administrator) prompt: it writes to
# Cert:\LocalMachine.
#
param([switch]$verbose)

# the CA is installed in machine-wide stores, so require elevation up front
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Error "This script must run from an elevated (Administrator) prompt."
    exit 1
}

# prompt for the operator's amateur radio callsign; it becomes part of the CN
# and also the base name of the generated key/cert files
$callsign = Read-Host "Enter your amateur radio callsign"
# force lowercase so the CA file names are predictable
$callsign = $callsign.ToLower()
$cn = "$callsign-root-ca"

# Define absolute output paths so System32 context doesn't break file writing
$certCerPath = Join-Path $PSScriptRoot "$cn.cer"
$certCrtPath = Join-Path $PSScriptRoot "$cn.crt"
$certKeyPath = Join-Path $PSScriptRoot "$cn.key"

# refuse to overwrite an existing CA of the same name; a new key pair would
# invalidate every certificate already signed by the old CA
if ((Test-Path $certKeyPath) -or (Test-Path $certCrtPath)) {
    Write-Error "Refusing to overwrite existing CA '$cn' ($cn.key / $cn.crt already exist)."
    exit 1
}

# create the self-signed EC P-256 Root CA. -KeyUsage CertSign,CRLSign makes
# Windows issue it as a CA (basicConstraints CA:TRUE). ~10-year validity,
# matching create-ca.sh.
$rootCA = New-SelfSignedCertificate -Type Custom `
    -Subject "CN=$cn" `
    -KeyAlgorithm ECDSA_P256 `
    -KeyExportPolicy Exportable `
    -KeyUsage CertSign, CRLSign `
    -CertStoreLocation "Cert:\LocalMachine\My" `
    -NotAfter (Get-Date).AddDays(3653)

# copy the Root CA to the Trusted Root Store so Windows accepts its issues
$rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "LocalMachine")
$rootStore.Open("ReadWrite")
$rootStore.Add($rootCA)
$rootStore.Close()

# deliverable: the CA certificate as PEM (what browsers/trust stores import).
# Export-Certificate writes DER; re-encode it as a PEM block. Use absolute paths.
Export-Certificate -Cert $rootCA -Type CERT -FilePath $certCerPath | Out-Null
$der = [System.IO.File]::ReadAllBytes($certCerPath)
Remove-Item $certCerPath
$b64 = [Convert]::ToBase64String($der, 'InsertLineBreaks')
[System.IO.File]::WriteAllText($certCrtPath, "-----BEGIN CERTIFICATE-----`n${b64}`n-----END CERTIFICATE-----`n")

# deliverable: the CA private key as unencrypted PKCS#8 DER.
# Safely capture the live ECDsaCng object directly from the certificate
$ecdsaKey = [System.Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($rootCA)

# Export the raw PKCS8 private key blob using the underlying .Key handle properties
$pkcs8Bytes = $ecdsaKey.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob)
[System.IO.File]::WriteAllBytes($certKeyPath, $pkcs8Bytes)

# tell me about the cert, if asked for
if ($verbose) {
    Write-Host "Subject:    $($rootCA.Subject)"
    Write-Host "Issuer:     $($rootCA.Issuer)"
    Write-Host "Expires:    $($rootCA.NotAfter)"
    Write-Host "Thumbprint: $($rootCA.Thumbprint)"
}

# list the files this run created
Write-Host "Created: $cn.key $cn.crt"
