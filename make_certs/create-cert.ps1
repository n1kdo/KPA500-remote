#
# Windows twin of create-cert.sh, using only stock Windows/PowerShell built-ins
# (New-SelfSignedCertificate + Export-Certificate). The CA must have been
# created by create-ca.ps1 on this machine: -Signer needs its private key,
# which lives in the certificate store.
#
# -verbose prints the certificate details at the end.
#
# Must be run from an elevated (Administrator) prompt: it writes to
# Cert:\LocalMachine.
#
param([switch]$verbose)

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Error "This script must run from an elevated (Administrator) prompt."
    exit 1
}

# prompt for the operator's amateur radio callsign; it names the CA that signs this cert
$callsign = Read-Host "Enter your amateur radio callsign"
# force lowercase so the CA name is predictable
$callsign = $callsign.ToLower()
$ca_name = "$callsign-root-ca"

# the CA must already exist in the store; a mistyped callsign would otherwise
# cascade into confusing failures and a false "Created:" message at the end
$rootCA = Get-ChildItem "Cert:\LocalMachine\My" | Where-Object { $_.Subject -eq "CN=$ca_name" } | Select-Object -First 1
if (-not $rootCA) {
    Write-Error "CA '$ca_name' not found in Cert:\LocalMachine\My."
    Write-Error "Run create-ca.ps1 first, or check the callsign."
    exit 1
}

# prompt for the subject name (hostname) of the certificate.
# ($host is a PowerShell automatic variable, so the local name is $hostname.)
$hostname = Read-Host "Enter hostname (subject name) for the certificate"
# force lowercase; DNS names are case-insensitive and this keeps the cert predictable
$hostname = $hostname.ToLower()

# prompt for zero or more subject alternative names; a blank line ends input
$sans = @()
while ($true) {
    $san = Read-Host "Subject alternative name (blank to finish)"
    if ($san -eq "") { break }
    # same lowercase treatment as the subject name
    $sans += $san.ToLower()
}

# issue the EC P-256 leaf certificate signed by the private CA. ~9.9-year
# validity, matching create-cert.sh. The TextExtension adds the Server Auth
# extended key usage. -DnsName (subject name plus all SANs) is only given
# when at least one SAN was entered; with no SANs the certificate carries no
# subjectAltName at all, matching create-cert.sh.
$leafArgs = @{
    Type              = 'Custom'
    Subject           = "CN=$hostname"
    Signer            = $rootCA
    KeyAlgorithm      = 'ECDSA_Cert'
    KeyLength         = 256
    KeyExportPolicy   = 'Exportable'
    KeyUsage          = 'DigitalSignature', 'KeyEncipherment'
    TextExtension     = @("2.5.29.37={text}1.3.6.1.5.5.7.3.1")
    CertStoreLocation = "Cert:\LocalMachine\My"
    NotAfter          = (Get-Date).AddDays(3652)
}
if ($sans.Count -gt 0) {
    $leafArgs['DnsName'] = @($hostname) + $sans
}
$leafCert = New-SelfSignedCertificate @leafArgs

# deliverables: the certificate as DER and the EC P-256 private key as
# unencrypted PKCS#8 DER (what MicroPython's load_cert_chain/load_key want)
Export-Certificate -Cert $leafCert -Type CERT -FilePath "$hostname.crt.der" | Out-Null
$ecKey = [System.Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($leafCert)
[System.IO.File]::WriteAllBytes("$hostname.key.der", $ecKey.ExportPkcs8PrivateKey())

# tell me about the new cert, if asked for
if ($verbose) {
    Write-Host "Subject:    $($leafCert.Subject)"
    Write-Host "Issuer:     $($leafCert.Issuer)"
    Write-Host "Expires:    $($leafCert.NotAfter)"
    Write-Host "Thumbprint: $($leafCert.Thumbprint)"
}

# list the files this run created
Write-Host "Created: $hostname.key.der $hostname.crt.der"
