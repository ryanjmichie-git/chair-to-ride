.PHONY: setup models synth baseline solve mediate mediate-fake perturb perturb-fake explain judge judge-only timeline test test-live gate full full-fake full-collect cost-report demo check-models

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

mediate:
	$(UV_RUN) python -m c2r.orchestrator data/synthetic/42 --out runs/cp2

mediate-fake:
	$(UV_RUN) python -m c2r.orchestrator data/synthetic/42 --out runs/cp2-fake --fake

perturb:
	$(UV_RUN) python -m c2r.perturb --event vehicle_down --at 13:40 --run runs/cp2 --out runs/cp3

perturb-fake:
	$(UV_RUN) python -m c2r.perturb --event vehicle_down --at 13:40 --fake --run runs/cp2-fake --out runs/cp3-fake

explain:
	$(UV_RUN) python -m c2r.explain runs/cp2
	$(UV_RUN) python -m c2r.explain runs/cp3

judge:
	$(UV_RUN) python -m c2r.judge runs/cp2
	$(UV_RUN) python -m c2r.judge runs/cp3

judge-only:
	$(UV_RUN) python evals/run_evals.py --judge-only

timeline:
	$(UV_RUN) python -m c2r.viz.timeline runs/cp1

test:
	$(UV_RUN) pytest -q

test-live:
	$(UV_RUN) pytest evals/invariants -q -p no:cacheprovider

gate:
	$(UV_RUN) python evals/run_evals.py --gate

full:
	$(UV_RUN) python evals/run_evals.py --full

full-fake:
	$(UV_RUN) python evals/run_evals.py --full --fake

full-collect:
	$(UV_RUN) python evals/run_evals.py --full-collect

cost-report:
	$(UV_RUN) python evals/cost_report.py

demo:
	$(MAKE) mediate
	$(MAKE) perturb

check-models:
	$(UV_RUN) python scripts/check_models.py
