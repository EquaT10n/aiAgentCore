# AI Agent Core Monorepo

This repository provides a minimal production-ready Python mono-repo skeleton.

## Local development

- Lint: `ruff check .`
- Format: `ruff format .`
- Tests: `pytest -q`

## Infra (AWS CDK v2)

The CDK app is intentionally minimal and does not deploy any resources.

- Install dependencies: `python -m pip install -r infra/requirements.txt`
- Synthesize: `cd infra` then `cdk synth`

## Next steps

- Extend the CDK stack in `infra/app.py`.
- Add application logic in `agent/` and tests in `tests/`.
