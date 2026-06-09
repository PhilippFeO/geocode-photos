.PHONY: all run flask flask-fetch file streamlit clean clean-logs

run: clean clean-logs flask-fetch

streamlit:
	@streamlit run src/streamlit_set_GPSIFD.py -- ./jpgs/*.jpg

flask:
	@python3 src/flask_set_GPSIFD.py ./jpgs/without.jpg

flask-fetch: 
	@python3 flask_fetch_set_GPSIFD.py ./jpgs/*.jpg

file:
	@python3 src/file_set_GPSIFD.py ./jpgs/without.jpg

clean:
	@if [ -f jpgs/without.jpg.bak ]; then cp jpgs/without.jpg.bak jpgs/without.jpg; else exit 0; fi

clean-logs:
	@cat /dev/null > nemo_action.log.json
