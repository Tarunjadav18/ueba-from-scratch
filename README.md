# UEBA Lab

A from-scratch learning implementation of the report's User and Entity Behaviour Analytics project. It includes batch and incremental scoring, synthetic data, analyst workflows, and a local console. The implementation is being built as a teachable recreation; it is not Amaan's original source code and does not reproduce the report's results by assertion.

## What is implemented

- Synthetic organization with planted insider-risk and account-compromise scenarios.
- CSV, JSON, JSONL and ZIP ingestion, column aliases, event normalization, and Linux authentication log parsing.
- Causal user-day, web, device-day, and activity-story features.
- Personal and peer baselines, robust statistics, an Isolation Forest/LOF/reconstruction ensemble, and explainable ATT&CK-mapped rules.
- Fused risk, criticality weighting, accumulated risk, and sustained alerts.
- Isolated workspaces, inbox collection, replay, persisted models, incremental scoring, and an authenticated scoped ingest API bound to localhost.
- Password-protected analyst console with roles, audit trail, alerts, cases, verdict feedback, suppressions, admin, activity, host, source, log, and performance views.
- Optional webhook/SMTP notifications and optional endpoint resource/network agent.

This is an educational prototype. Use synthetic or authorized, de-identified exports only; do not monitor employees or deploy it as a production security control without a proper privacy, security, and validation review.

## Run on your Mac

The local run has been exercised with macOS Python 3.9.6; Python 3.11 or newer is recommended for a fresh installation. From Terminal:

```sh
cd /path/to/ueba-from-scratch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_pipeline.py
```

The batch run prints the evaluation summary and writes reports to `data/reports/demo`. To start the console, collector, and local ingest API together:

```sh
python launch.py
```

Open <http://localhost:8501>. On first visit, create your own administrator username and password in the browser. Codex will not set that password for you. Press Ctrl+C in the Terminal running `launch.py` to stop the local services.

To replay synthetic activity through the collector, open a second Terminal in the project folder, activate `.venv`, then run:

```sh
python -m ueba.replay --workspace live-demo --labels
```

For endpoint resource and network counters, install the optional agent dependency with `python -m pip install -r requirements-agent.txt`, then run `python -m ueba.agent --help` to see its options.

## Deploy on Render

The repository includes a Dockerfile and `render.yaml` Blueprint. Review the paid compute and persistent disk in [the Render deployment notes](docs/RENDER_DEPLOYMENT.md) before creating a service. Persistent storage is required to retain accounts, cases, models, and workspace data between restarts.

## Learn the flow

Start with [Lesson 1](docs/LESSON_01.md), then follow the complete [learning path](docs/LEARNING_PATH.md): `ueba/generator.py` → `ueba/ingest.py` → `ueba/features.py` → `ueba/profiles.py`/`ueba/ml.py` → `ueba/detectors.py` → `ueba/risk.py` → `ueba/pipeline.py`. The console code is under `dashboard/`; the current feature map and remaining release work are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Attribution

The original in-house project implementation and work were by Amaan Saify; the project report/documentation was prepared by Tarun S Jadav. This repository is an independent from-scratch learning recreation developed with AI assistance from the report and companion guide. It does not include Amaan's original source code or the source PDFs. Do not commit real logs, credentials, local databases, models, or generated workspaces.
