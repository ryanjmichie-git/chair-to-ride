.PHONY: setup models synth baseline test gate demo

setup:
	uv sync --python 3.12

models:
	uv run datamodel-codegen --input specs/schemas --input-file-type jsonschema --output src/c2r/models --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 --use-title-as-name --allow-population-by-field-name --collapse-root-models --all-exports-scope children --disable-timestamp --formatters ruff-check ruff-format

synth:
	uv run python -m c2r.synth --seed 42 --out data/synthetic/42

baseline:
	uv run python -m c2r.metrics data/synthetic/42

test:
	uv run pytest -q

gate:
	uv run python evals/run_evals.py --gate

demo:
	$(MAKE) baseline
