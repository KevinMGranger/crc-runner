reload-user:
	systemctl --user daemon-reload

reload-sys:
	systemctl daemon-reload

install-user-services user_unit_dir="$HOME/.config/systemd/user":
	cp systemd/crc-user.service "{{user_unit_dir}}/crc.service"
	cp systemd/crc-log.service "{{user_unit_dir}}/crc-log.service"

install-system-service system_unit_dir="/usr/lib/systemd/system/":
	cp systemd/crc-system.service "{{system_unit_dir}}/crc.service"

ustart:
	systemctl --user start crc.service

ustat:
	systemctl --user status crc.service

ustop:
	systemctl --user stop crc.service

sysstart:
	sudo systemctl start crc

sysstat:
	systemctl status crc

format:
	black crc_runner
	isort crc_runner

user-local:
  #!/usr/bin/env bash
  set -x
  mkdir -p ~/.config/systemd/user/crc.service.d/
  cat > ~/.config/systemd/user/crc.service.d/local-file-dropin.conf <<EOF
  [Service]
  ExecStart=
  Environment=PYTHONPATH=%h/.local/lib/python3.10/
  ExecStart=/usr/bin/python3 -m crc_runner start
  EOF

no-user-local:
	rm ~/.config/systemd/user/crc.service.d/local-file-dropin.conf

make-system-dropin:
	mkdir -p /etc/systemd/system/crc.service.d/

system-local: make-system-dropin
	cp systemd/local-file-dropin.conf /etc/systemd/system/crc.service.d/	

no-system-local:
	rm /etc/systemd/system/crc.service.d/local-file-dropin.conf

set-system-user user: make-system-dropin
	#!/usr/bin/env bash
	set -x
	cat > /etc/systemd/system/crc.service.d/user.conf <<EOF
	[Service]
	User={{user}}
	EOF