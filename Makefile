install:
	cp crc.service ~/.config/systemd/user/crc.service
	systemctl --user daemon-reload

sysinstall:
	sudo sh -c "cp crc-system.service /etc/systemd/system/crc.service && cp __main__.py /usr/local/bin/python-crc-systemd && systemctl daemon-reload"

urun:
	systemctl --user start crc.service

ustat:
	systemctl --user status crc.service

sysrun:
	sudo systemctl start crc

sysstat:
	systemctl status crc

format:
	black __main__.py crc_systemd
	isort __main__.py crc_systemd


