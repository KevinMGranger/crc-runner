jtest foo:
	echo {{foo}}

foo bar:
	echo {{bar}}

build:
	python3 -m compileall crc_systemd

install:
	cp systemd/crc-user.service ~/.config/systemd/user/crc.service
	cp systemd/crc-log.service ~/.config/systemd/user/crc-log.service

reload-user:
	systemctl --user daemon-reload

reload-sys:
	systemctl daemon-reload

install-user-services user_unit_dir="~/.config/systemd/user":
	cp systemd/crc-user.service "{{user_unit_dir}}/crc.service"
	cp systemd/crc-log.service "{{user_unit_dir}}/crc-log.service"

install-system-service system_unit_dir="/usr/lib/systemd/system/":
	cp systemd/crc-system.service "{{system_unit_dir}}/crc.service"

sysinstall:
	sudo sh -c "cp systemd/crc-system.service /etc/systemd/system/crc.service && cp crc_systemd/__main__.py /usr/local/bin/python-crc-systemd && systemctl daemon-reload"

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

build-rpm:
	rpmbuild -ba crc-runner.spec