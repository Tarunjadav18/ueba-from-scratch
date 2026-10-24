# Lesson 1: how one event becomes an alert

This is the main path through the program. Follow it in order; each stage changes the data into a form the next stage can use.

## 1. Events are observations

An event is one thing a system observed at a time: a successful login, a file access, or a network transfer. `ueba/ingest.py` standardizes timestamps, users, devices, and event names. That lets the rest of the program process mixed sources through one common schema.

## 2. Features summarize behavior

Models cannot use a pile of unrelated text rows directly. `ueba/features.py` groups observations into user-day and device-day records, then calculates counts, totals, and context: failed logins, off-hours use, file activity, bytes sent, web activity, and more. This is why a score represents a particular entity on a particular day.

## 3. A profile estimates normal behavior

`ueba/profiles.py` compares today's values with that entity's earlier history and with peers. Robust statistics reduce the effect of occasional extreme days. Only prior dates are used, so tomorrow's data cannot change yesterday's score.

## 4. Detectors supply different kinds of evidence

`ueba/ml.py` combines unsupervised anomaly models. `ueba/detectors.py` applies readable behavior rules and attaches ATT&CK references. Each detector contributes evidence and reasons; one odd value by itself is not treated as certainty.

## 5. Risk turns evidence into a queue

`ueba/risk.py` combines detector signals, entity criticality, and recent accumulated risk into a bounded score. The pipeline marks alerts and sustained alerts. This is a triage aid: an alert means an analyst should investigate the surrounding events, not that a person is guilty.

## Follow the code

Start with `run_pipeline.py`, which loads or generates events and calls `ueba.pipeline.run()`. Then trace the stages above. `dashboard/app.py` renders the console; `ueba/service.py` watches workspace inboxes and runs updated data through the same pipeline.

## What to keep in mind

The demonstration data is synthetic and planted with known scenarios. Its metrics measure performance on that generated sample only. The performance page includes threshold comparisons and signal ablations; the ablations reuse held-out scores rather than retraining. Real organizations have different logging quality, behaviors, and false-positive patterns; validate any detector on authorized data before relying on it.
