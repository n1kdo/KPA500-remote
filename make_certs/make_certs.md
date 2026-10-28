# Making SSL Certificates with your own Private Certificate Authority (CA)

This guide will walk you through the process of creating your own SSL certificates using a private
Certificate Authority (CA). This is useful for testing and development purposes, as well as for 
securing your own internal services.

## Limitations ##

Note that using this approach will require you to install the private CA's certificate on all 
machines that will be accessing the services secured by the SSL certificates. This can be a 
challenging task, especially if you have a large number of machines or if you are using a 
heterogeneous environment with different operating systems and configurations.

There are other ways to create SSL certificates, such as using a public CA or using a third-party 
service. However, these options may be more expensive or less flexible than creating your own 
private CA.  For instance, it is possible to use _Let's Encrypt_ to create free SSL certificates, 
but those have a short expiration period and may not be suitable for all use cases.

## Background ##

The Pico-W running Micropython has a _hostname_ that is set up through the configuration dialog.
The _hostname_ is sent in a DHCP request, it is possible your router may be able to configure 
it's own DNS configuration to resolve the hostname to the IP address of the Pico-W.  

In addition to that, the Pico-W's micropython supports _Multicast DNS_ (mDNS) which can be used 
to resolve the hostname to the IP address of the Pico-W without setting up DNS on your router or
even a fixed IP address for the device.  In this case, the Pico-W will automatically advertise 
its hostname and IP address on the local network, making it easier to access the device without 
having to configure DNS or a fixed IP address.  You can access the device using the IP address
(if you know it, the IP address is blinked in Morse code on the LED of the device) or by using
`<hostname>.local` -- replace <hostname> with the configured hostname of the device.

The hostname is critically important in creating a SSL certificate for the device.  If you have
your home router configured to assign and resolve a hostname for the device (e.g. 
`kpa500.n1kdo.com`) you may want to use that hostname when creating the SSL certificate, or
use the mDNS hostname `<hostname>.local` *and* the router's assigned DNS name in the certificate.



## Creating the Private CA ##

Run `create-ca.sh` (or `create-ca.ps1` on Windows).  It will prompt for your amateur radio
callsign; the callsign becomes part of
the CA's subject name (`<callsign>-root-ca`) and the base name of the generated files:

```
$ ./create-ca.sh
Enter your amateur radio callsign: N1KDO
```

**Note:** The Windows PowerShell scripts (`create-ca.ps1` and `create-cert.ps1`) are untested;
use them at your own risk.

The script produces two files:

* `N1KDO-root-ca.key` -- the CA's private key.  **Keep this file safe**; it is required to sign
  (and renew) certificates, and if it is lost the certificates already issued by this CA cannot be
  renewed.
* `N1KDO-root-ca.crt` -- the CA certificate (self-signed, valid for about 10 years).

Before connecting, install the CA certificate (`<callsign>-root-ca.crt`) on every machine that
will connect to a service secured with a certificate signed by this CA -- see *Installing the CA
Certificate* below.  Until it is installed, browsers will warn that the connection is not
trusted.

## Installing the CA Certificate ##

The goal is to get `<callsign>-root-ca.crt` (PEM) into the certificate store that your browser
actually consults.  That depends on both the browser and the operating system.

### Windows ###

Add the CA to the Windows certificate store (an elevated/administrator prompt is required).
From an elevated command prompt:

```
certutil -addstore Root <callsign>-root-ca.crt
```

Or through the GUI: run `certmgr.msc` as administrator, expand **Trusted Root Certification
Authorities** then **Certificates**, right-click in the right pane and choose **All Tasks** >
**Import...**, select the `.crt` file, and finish the wizard (it will be detected as PEM).

### Linux ###

The mechanism depends on the distribution; both expect a PEM file:

* Debian/Ubuntu: copy it into `/usr/local/share/ca-certificates/` with a `.crt` extension, then
  run `update-ca-certificates`:

  ```
  sudo cp <callsign>-root-ca.crt /usr/local/share/ca-certificates/root-ca.crt
  sudo update-ca-certificates
  ```

* RHEL/Fedora/CentOS: drop it into the anchor directory, then refresh the trust store:

  ```
  sudo cp <callsign>-root-ca.crt /etc/pki/ca-trust/source/anchors/
  sudo update-ca-trust
  ```

### Browsers ###

* **Chrome, Edge, Brave, Vivaldi** -- use the OS-native store on both Windows and Linux; there is
  no per-browser step.  Installing the CA as described above is enough.
* **Firefox** -- keeps its *own* certificate store on every platform, independent of the OS
  store.  Import the CA via **Settings** > **Privacy & Security** > **Certificates** >
  **View Certificates**, then the **Authorities** tab > **Import...**; select the `.crt` file
  and check *Trust this CA to issue certificates*.

## Creating the SSL Certificate ##

Run `create-cert.sh` (or `create-cert.ps1` on Windows).  It prompts for three things:

1. Your amateur radio callsign -- the same one used when creating the private CA, so the script
   can find `<callsign>-root-ca.crt` and `<callsign>-root-ca.key`.
2. The hostname (subject name) of the certificate.  For the Pico-W this should be
   `<hostname>.local`, matching the device's configured hostname; the script also uses this value
   as the base name of the files it generates.
3. Zero or more subject alternative names, one per line; press Enter on an empty line when you
   are done.  If you enter at least one, the certificate will carry a Subject Alternative Name
   extension listing the subject name *and* every name you entered.  Modern browsers validate
   the hostname against the SANs (not the subject name), so include every name you expect to use
   to reach the device -- for example both `<hostname>.local` and the router-assigned DNS name.

The script produces two files, named after the hostname you entered:

* `<hostname>.key.der` -- the server's private key.
* `<hostname>.crt.der` -- the certificate signed by your private CA (valid for about 10 years).

(The PEM intermediates are deleted once the DER files exist.)

Copy the two DER files to the Pico-W so that they are named exactly as the application expects:

* `data/<hostname>.local.crt.der`
* `data/<hostname>.local.key.der`

(If you entered `<hostname>.local` as the subject name, the generated file names already match.
You can upload them with the Easy-Loader tool or any SFTP/SCP client.)

* Important Note *

The CA private key (`<callsign>-root-ca.key`) is the most sensitive file in this process.  Do not
commit it to version control, post it anywhere, or copy it to untrusted machines -- anyone who
possesses it can issue certificates that your clients will trust.  All `*.key`, `*.crt`, and
`*.der` files are covered by the `.gitignore` in this directory for exactly this reason.

