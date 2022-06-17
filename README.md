Run crc as a user, but with ingress as the system.

Runs crc itself as a user-level service,
polling it to see if it's healthy.

Coordinates this with a system-level service,
so that haproxy can be started once it's ready.
