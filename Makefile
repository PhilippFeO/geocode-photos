.PHONY: run clean clean-logs

run: clean clean-logs
	@python3 geocode.py ./jpgs/*.jpg

clean:
	@if [ -f jpgs/without.jpg.bak ]; then cp jpgs/without.jpg.bak jpgs/without.jpg; else exit 0; fi

clean-logs:
	@cat /dev/null > nemo_action.log.json
