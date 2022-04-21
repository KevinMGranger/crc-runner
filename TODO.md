- forward logs from user service to system service?
- document everything
- should system runner and user runner work more similarly for monitoring? Am I doing cancellation and disconnection correctly?
    - well they _are_ different. one wants to keep putting crc status out there but the other does polling when trying to stop.

- user level monitor not running?
- handle stop correctly:
    - if busctl exits immediately after calling then systemd will decide to send a kill because it's not done yet
    - handle signals that happen before full start (if not started yet it send KillSignal)

