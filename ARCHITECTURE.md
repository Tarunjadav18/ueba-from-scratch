# Architecture and build map

The target is the full project described in `UEBA_Project_Guide_Amaan_Saify.pdf`: an explainable, multi-source UEBA system with batch and incremental operation, a secured analyst console, and a live collector. This repository is a new implementation, not a copy of the classmate's source. Keep authorship and data provenance explicit when publishing it.

## Target components

| Area | Planned implementation |
|---|---|
| Data sources | Auth, system access, network/proxy, resource and detailed web events; CSV/JSON/ZIP mapping; Linux auth/syslog and exported Windows event logs |
| Workspaces | Isolated logs, models, inbox/failed folders, status lifecycle, file locking |
| Features | Causal user-day, device-day, web and analyst-activity features |
| Profiles | Personal and department peer baselines with robust median/MAD/P95 scale |
| Detection | Statistical deviations, Isolation Forest/LOF/autoencoder ensemble, MITRE ATT&CK rules |
| Risk | Corroborated risk fusion, criticality, accumulated risk, explanations |
| Learning safety | Adaptive history with suspicious-day quarantine and analyst verdict feedback |
| Continuous operation | Saved models, incremental scoring, collector, authenticated ingest API, endpoint agent, replay |
| Analyst workflow | Alerts, entity investigation, user activity story, cases, assignments, notes, suppressions, verdicts |
| Operations | Notifications, health/heartbeat, log explorer/export, performance page |
| Security | Roles, PBKDF2 password hashes, scoped API tokens, session controls, audit trail, local-only defaults |
| Delivery | Reproducible synthetic sample, documentation, local setup, public GitHub repository, and a live temporary Render Free deployment |

## Implementation status

1. **Analytics core — implemented**: normalized events → daily features → personal baseline → explanations and risk.
2. **Full detector — implemented as a prototype**: peer profiles, web/activity/device signals, rules and ML ensemble.
3. **Ingestion and workspaces — implemented as a prototype**: CSV/JSON/JSONL/ZIP adapters, validation, Linux auth parsing, isolated workspaces, inbox and failed-file handling. Windows support is limited to export normalization; this is not a live Windows collector.
4. **Analyst workflow — implemented as a prototype**: dashboard pages, cases, feedback, suppressions, log explorer and notification integrations.
5. **Continuous service — implemented locally, needs hardening**: authentication, scoped tokens, audit, local API, collector, optional agent, replay, incremental model state. API defaults to loopback; deployment needs a deliberate secure network design.
6. **Release and deployment — classroom demo live**: the public repository and Render Free service are deployed, and the container build and console health check succeeded. Threshold, component-ablation, and optional five-seed robustness experiments are available for the synthetic sample. The free service has no durable storage; account and workspace data can disappear on sleep, restart, or redeploy. Durable storage, deployment hardening, a security/privacy review, and production validation remain future work.

The PDF report and companion guide contain different counts and results, so implementation and claims are based on code we build and measurements we actually run. Current local synthetic evaluation is not a reproduction of the source report's experiment.
