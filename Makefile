.PHONY: install run test reset

install:
	pip install -r requirements.txt

run:
	python -m uvicorn app.main:app --reload

test:
	python -m pytest -q

reset:
	python -m app.seed
