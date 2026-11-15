.PHONY: help install test run build docker clean

PYTHON ?= python3
PORT ?= 8000

help:
	@printf '%s\n' \
		'Tarla Dostu — kullanılabilir hedefler' \
		'' \
		'  make install   Bağımlılıkları kur' \
		'  make test      Testleri çalıştır' \
		'  make run       Geliştirme sunucusunu başlat (http://127.0.0.1:8000/app/)' \
		'  make build     Doğrula, test et ve dist/ paketi üret' \
		'  make docker    Docker imajı oluştur' \
		'  make clean     Önbellek ve dist/ temizle'

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest -q

run:
	$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT) --reload

build:
	PYTHON=$(PYTHON) ./scripts/build.sh

docker:
	docker build -t tarla-dostu:local .

clean:
	rm -rf dist build .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
