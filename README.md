# Raspberry Pi Pico W IOT Thing for Elecraft KPA500 Amplifier

## Web Client

The KPA500-remote IOT thing provides a web client for the amplifier.

The web client is modeled on the Elecraft KPA500-Remote windows client,
more or less.  The fundamental difference is that the web client will
not automatically update unless one of the non-zero auto-refresh buttons
is selected.  Note that the on every activity, the auto-refresh is 
engaged for three one-second updates regardless of the update settings.
This is to allow the changes made from the UI to be reflected on the page.

![](WebConsole.png "View of Web Console for KPA500 Amplifier")

## Elecraft "KPA-500 Remote" server

The KPA500-remote IOT thing also provides a network server that is 
compatible with the KPA-500 remote client.

This means that you don't need a dedicated computer to serve the amplifier
to the network, the KPA500-remote IOT thing (this application) does that
already.

n1kdo 20221227