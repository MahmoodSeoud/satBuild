# csh init for the flatsat ground station.
#
# Loads the SI APM (so `power on/off`, `node add`, `ping` work) plus the
# satdeploy APM, and registers the PDU + OBC.
#
# Customize before first use:
#   - The `csp add` line: replace with the transport that actually reaches
#     your spacecraft bus (CAN, KISS over USB-serial, UDP/eth, etc.).
#   - The `node add` line: -p <PDU_HOSTNAME> -c <CHANNEL> <FRIENDLY_NAME>.
#     The lab will tell you which channel powers the OBC and what the
#     PDU's CSP hostname is.
#
# After this runs, the harness can issue:
#   power off obc        - cut OBC power
#   power on  obc        - restore OBC power
#   ping obc             - block until OBC responds (post-reboot wait)
#   satdeploy push <app> - normal deploy
# all in the same csh session.

csp init

# REPLACE with your real transport. Examples:
#   csp add can -c can0 -d 19           # CAN bus to spacecraft
#   csp add kiss -u /dev/ttyUSB0 -b 9600 -d 19   # ground modem via UART
#   csp add udp -d 19 192.168.1.5       # over IP for early bench bring-up
csp add can -c can0 -d 19

apm load

# REPLACE the channel (-c) with the OBC's actual PDU-P4 channel and
# replace pdu1-a with the PDU's CSP hostname or address.
node add -p pdu1-a -c 2 obc
