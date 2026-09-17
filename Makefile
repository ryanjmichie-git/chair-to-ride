.PHONY: setup models synth baseline solve timeline test gate demo check-models

ENV_FILE := $(wildcard .env)
UV_RUN := uv run $(if $(ENV_FILE),--env-file $(ENV_FILE),)

setup:
	uv sync --python 3.12

models:
	uv run datamodel-codegen --input specs/schemas --input-file-type jsonschema --output src/c2r/models --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 --use-title-as-name --allow-population-by-field-name --collapse-root-models --all-exports-scope children --disable-timestamp --formatters ruff-check ruff-format

synth:
	$(UV_RUN) python -m c2r.synth --seed 42 --out data/synthetic/42

baseline:
	$(UV_RUN) python -m c2r.metrics data/synthetic/42

solve:
	$(UV_RUN) python -m c2r.solver data/synthetic/42 --out runs/cp1

timeline:
	$(UV_RUN) python -m c2r.viz.timeline runs/cp1

test:
	$(UV_RUN) pytest -q

gate:
	$(UV_RUN) python evals/run_evals.py --gate

demo:
	$(MAKE) solve
	$(MAKE) timeline

check-models:
	$(UV_RUN) python scripts/check_models.py
