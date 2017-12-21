.PHONY: install
install:
	cp sdrclient.service /lib/systemd/system/
	chmod 644 /lib/systemd/system/sdrclient.service
	systemctl daemon-reload
	systemctl enable sdrclient.service
	systemctl start sdrclient.service

