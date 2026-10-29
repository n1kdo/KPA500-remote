#
# Zero-dependency Windows twin of create-cert.sh using only stock Windows/PowerShell 5.1.
# Packs raw EC math coordinates into a strict, padded 32-byte SEC1 structure for MicroPython.
#
# Must be run from an elevated (Administrator) prompt.
#
param([switch]$verbose)

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Error "This script must run from an elevated (Administrator) prompt."
    exit 1
}

$callsign = Read-Host "Enter your amateur radio callsign"
$callsign = $callsign.ToLower()
$ca_name = "$callsign-root-ca"

$rootCA = Get-ChildItem "Cert:\LocalMachine\My" | Where-Object { $_.Subject -eq "CN=$ca_name" } | Select-Object -First 1
if (-not $rootCA) {
    Write-Error "CA '$ca_name' not found in Cert:\LocalMachine\My."
    exit 1
}

$hostname = (Read-Host "Enter hostname (subject name) for the certificate").ToLower()

$certDerPath = Join-Path $PSScriptRoot "$hostname.crt.der"
$certKeyPath = Join-Path $PSScriptRoot "$hostname.key.der"

$sans = @()
while ($true) {
    $san = Read-Host "Subject alternative name (blank to finish)"
    if ($san -eq "") { break }
    $sans += $san.ToLower()
}

$leafArgs = @{
    Type              = 'Custom'
    Subject           = "CN=$hostname"
    Signer            = $rootCA
    KeyAlgorithm      = 'ECDSA_P256'
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

# 1. Output the public certificate as standard raw DER
Export-Certificate -Cert $leafCert -Type CERT -FilePath $certDerPath | Out-Null

# 2. Extract raw cryptographic parameters via .NET properties
$ecKey = [System.Security.Cryptography.X509Certificates.ECDsaCertificateExtensions]::GetECDsaPrivateKey($leafCert)
$ecParameters = $ecKey.ExportParameters($true)

# Helper function to enforce exact 32-byte mathematical width required by mbedtls
function Pad-To32Bytes([byte[]]$bytes) {
    if ($bytes.Length -eq 32) { return ,$bytes }
    $padded = New-Object byte[] 32
    $offset = 32 - $bytes.Length
    [System.Array]::Copy($bytes, 0, $padded, $offset, $bytes.Length)
    return ,$padded
}

$dKey = Pad-To32Bytes $ecParameters.D
$qX   = Pad-To32Bytes $ecParameters.Q.X
$qY   = Pad-To32Bytes $ecParameters.Q.Y

# 3. Manually construct a textbook 121-byte SEC1 ASN.1 DER Sequence block
$sec1Bytes = New-Object System.Collections.Generic.List[byte]

# Outer SEQUENCE Header (Total Inner Payload size is exactly 119 bytes -> 0x77)
$sec1Bytes.AddRange([byte[]]@(0x30, 0x77))

# Version: 1 (3 bytes)
$sec1Bytes.AddRange([byte[]]@(0x02, 0x01, 0x01))

# Private Key: Octet String wrapper + 32 padded bytes (34 bytes)
$sec1Bytes.AddRange([byte[]]@(0x04, 0x20))
$sec1Bytes.AddRange($dKey)

# Parameters OID: secp256r1 [0] (12 bytes)
$sec1Bytes.AddRange([byte[]]@(0xa0, 0x0a, 0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07))

# Public Key: Explicit context wrapper [1] + BitString header + Uncompressed token (0x04) + X + Y (70 bytes)
$sec1Bytes.AddRange([byte[]]@(0xa1, 0x44, 0x03, 0x42, 0x00, 0x04))
$sec1Bytes.AddRange($qX)
$sec1Bytes.AddRange($qY)

# 4. Save the flawless key array directly out to the device workspace folder
[System.IO.File]::WriteAllBytes($certKeyPath, $sec1Bytes.ToArray())

if ($verbose) {
    Write-Host "Subject:    $($leafCert.Subject)"
    Write-Host "Issuer:     $($leafCert.Issuer)"
    Write-Host "Expires:    $($leafCert.NotAfter)"
    Write-Host "Thumbprint: $($leafCert.Thumbprint)"
}

Write-Host "Created: $hostname.key.der $hostname.crt.der"
