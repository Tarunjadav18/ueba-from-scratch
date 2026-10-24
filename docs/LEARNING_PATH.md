# Learning path

Use this sequence to understand the system as you run it. For each lesson, read the listed module first, then locate the named function and follow its input and output.

## 1. Generate known behavior

**Read:** `ueba/generator.py` (`make_demo`).

The generator creates a synthetic organization and deliberately plants labeled scenarios. Labels are kept for evaluation; they must not be used as model inputs. This gives us a repeatable way to understand where a result came from.

**Trace:** pick one row where `scenario` is non-empty and follow its timestamp, user, event type, and attributes.

## 2. Normalize different source formats

**Read:** `ueba/sources.py` and `ueba/ingest.py` (`load_events`, `normalize_events`, `parse_linux_auth`).

Aliases and parsers map source-specific column names into a common event schema. Normalization converts timestamps and numeric fields, and fills optional attributes.

**Trace:** follow a CSV row from `read_source()` to one normalized event. Observe which missing values become defaults and which malformed values are rejected.

## 3. Turn events into daily features

**Read:** `ueba/features.py` (`build_user_days`, `build_device_days`).

Raw logs can be verbose. The feature builders aggregate them into one row per user-day or device-day, with counts, volumes, novelty, and behavioral context. Novelty is computed against prior observations to keep the timeline causal.

**Trace:** choose a user-day and add up the underlying events that contribute to `auth_failures`, `bytes_out_mb`, or `usb_events`.

## 4. Estimate normal behavior and score anomalies

**Read:** `ueba/profiles.py`, `ueba/ml.py`, and the scoring stages in `ueba/pipeline.py`.

Personal profiles compare an entity with its own past; peer profiles compare it with similar entities. Robust scales limit the influence of extreme historical days. Unsupervised models add another signal. The pipeline learns only from earlier dates, then applies calibration and guardrails.

**Trace:** find one score column and identify which model or profile supplied it. Confirm labels are only used after scoring for evaluation/feedback.

## 5. Explain rules and combined risk

**Read:** `ueba/detectors.py` and `ueba/risk.py`.

Rules are readable conditions mapped to ATT&CK references. Risk fusion combines model, profile, and rule evidence and retains reasons so an analyst can inspect the signal.

**Trace:** compare one alert's rule IDs and explanation with the behavior features that triggered them. Treat a high score as a lead for investigation, not a verdict.

## 6. Evaluate carefully

**Read:** `ueba/evaluate.py`, `ueba/experiments.py`, and use the Model Performance page.

Precision, recall, F1, ROC-AUC, and PR-AUC depend on ground-truth labels. The performance page and `data/reports/demo/evaluation.json` include a threshold sweep and detector-signal ablations. An ablation removes a signal from risk fusion over the same scored days; it does not retrain the model. Run `python run_pipeline.py --robustness` to regenerate and retrain five synthetic organizations and save per-seed combined user-day/device-day results to `data/reports/demo/robustness.json`. The seeds vary organization membership, department/habit assignments, attack victims, and incident timing. The synthetic generator includes planted attacks, so these metrics describe generated samples and do not establish real-world accuracy.

**Trace:** inspect one false positive and one missed malicious user-day in `data/reports/demo/user_day_scores.csv` after a batch run.

## 7. Follow continuous ingestion

**Read:** `ueba/workspace.py`, `ueba/service.py`, `ueba/api.py`, and `ueba/replay.py`.

Each workspace isolates event files, models, failed inputs, and reports. The collector watches an inbox, normalizes new events, scores changed history incrementally, and updates the workspace. The API accepts bearer-token batches into an inbox; the replay command feeds a history and later dates through the collector.

**Trace:** replay a synthetic feed, inspect the workspace's `events.csv`, `scores.csv`, and `workspace.json`, and observe its state move from learning to monitoring.

## 8. Follow an analyst case

**Read:** `ueba/cases.py`, `ueba/feedback.py`, `ueba/auth.py`, and `dashboard/views/cases.py`.

Related alerts are grouped as cases. Analysts can add notes, assign work, set a verdict, or suppress a known pattern for a limited period. Verdict feedback is applied to scoring. Roles and audit records control and record analyst actions.

**Trace:** open an alert in the console, inspect its case, and follow how a verdict is stored and passed back to the next pipeline run.

## 9. Understand operational boundaries

**Read:** `ueba/notify.py`, `ueba/agent.py`, `launch.py`, `Dockerfile`, and `docs/RENDER_DEPLOYMENT.md`.

Notifications are optional and configured with environment variables. The endpoint agent gathers limited local counters and queues events for delivery. The current Render Blueprint uses a free web service with no persistent disk; the dashboard is public and protected by its administrator login, while the ingest API stays bound to loopback inside the container. Free-service sleep, restarts, and deploys can erase the database and saved workspace data.

**Trace:** start locally first. Use synthetic or authorized, de-identified data only. For the temporary cloud demo, expect to recreate the administrator and data after a reset. Before using a paid service or persistent storage, review its cost and the prototype's security/privacy limits.
