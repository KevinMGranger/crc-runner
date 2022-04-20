install:
	cp crc.service ~/.config/systemd/user/crc.service
	systemctl --user daemon-reload

sys-install:
	sudo sh -c "cp crc-system.service /etc/systemd/system/crc.service && cp __main__.py /usr/local/bin/python-crc-systemd && systemctl daemon-reload"
