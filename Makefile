.PHONY: install run test reset migration migrate

install:
	pip install -r requirements.txt

run:
	python -m uvicorn app.main:app --reload

test:
	python -m pytest -q

reset:
	python -m app.seed

# After editing app/models.py:  make migration m="add shelf_life to bins"   then   make migrate
migration:
	python -m alembic revision --autogenerate -m "$(m)"

migrate:
	python -m alembic upgrade head
