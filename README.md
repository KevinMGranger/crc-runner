Run crc as a user, but with ingress as the system.

Runs crc itself as a user-level service, polling it to see if it's healthy.

Coordinates this with a system-level service, so that haproxy can be started once it's ready.

# Developing

Use systemd overrides to change the pythonpath if you want to use local versions instead of the packaged version.

We could include those in the justfile if we want.

# notes on package building

- "systemd" on pypi is not the same as the package! That's why it was a problem.
- I guess it had something to do with extracting dependencies form the wheel or dist-info or something, but that requires further investigation.