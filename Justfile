reload-user:
	systemctl --user daemon-reload

reload-sys:
	systemctl daemon-reload

install-user-services user_unit_dir="~/.config/systemd/user":
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
	black crc_systemd
	isort crc_systemd

user-local:
	mkdir ~/.config/systemd/user/crc.service.d/
	cp systemd/local-file-dropin.conf ~/.config/systemd/user/crc.service.d/

no-user-local:
	rm ~/.config/systemd/user/crc.service.d/local-file-dropin.conf

make-system-dropin:
	mkdir /etc/systemd/system/crc.service.d/

system-local: make-system-dropin
	cp systemd/local-file-dropin.conf /etc/systemd/system/crc.service.d/	

no-system-local:
	rm /etc/systemd/system/crc.service.d/local-file-dropin.conf

set-system-user user: make-system-dropin
	#!/usr/bin/env bash
  cat > /etc/systemd/system/crc.service.d <<EOF
	[Service]
	User={{user}}
	EOF