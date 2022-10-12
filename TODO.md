- parse stdout for known failure modes and handle them (e.g. Bundle 'crc_libvirt_4.11.3_amd64' was requested, but the existing VM is using 'crc_libvirt_4.11.1_amd64'. Please delete your existing cluster and start again)
- determine when creating a new cluster, then watchdog / time out
  - detect when already running and do `start()` idempotently? We don't need preemptive starting anymore since there's no dbus

- embed git version or something

- document everything

- should system runner and user runner work more similarly for monitoring? Am I doing cancellation and disconnection correctly?
    - well they _are_ different. one wants to keep putting crc status out there but the other does polling when trying to stop.
    - could also connect to the runner directly and wait for a signal!
        - will that work though? It'll get sent immediately? cuz one close exits it'll get signaled.

- handle start correctly:
    - if already running via crc status, should just say "yeah it's up"! and skip start step
        - should separate start and wait tasks for this, back into separate functions

- clean up logging format for systemd (seems like the info duplication is in the log tailer, right?)