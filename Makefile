install:
	cp systemd/crc-user.service ~/.config/systemd/user/crc.service
	cp systemd/crc-log.service ~/.config/systemd/user/crc-log.service
	systemctl --user daemon-reload

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
