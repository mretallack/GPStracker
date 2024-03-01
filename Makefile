PYTHON=python3.11

run: venv/bin/activate
	. venv/bin/activate && ${PYTHON} -u tracker.py

run_config: venv_config/bin/activate
	. venv/bin/activate && ${PYTHON} config.py


venv/bin/activate: requirements.txt
	${PYTHON} -m venv venv
	. venv/bin/activate && ${PYTHON} -m pip install -r requirements.txt


venv_config/bin/activate: requirements.txt
	${PYTHON} -m venv venv_config
	. venv_config/bin/activate && ${PYTHON} -m pip install -r requirements.txt

