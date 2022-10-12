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