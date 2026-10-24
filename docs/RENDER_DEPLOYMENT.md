# Temporary Render deployment

The current `render.yaml` uses Render's free web-service plan. It runs the Streamlit console, collector, and loopback-only ingest API in one container. The SQLite database, uploaded events, cases, and model files are stored under `/var/data` on the container's ephemeral filesystem.

## Free-plan limits

Render spins down a free web service after 15 minutes without inbound traffic. Local filesystem changes are lost whenever the service redeploys, restarts, or spins down; free services cannot attach persistent disks. Your administrator account, cases, feedback, workspaces, uploaded events, and saved models may disappear. Use synthetic demo data only and expect to recreate the account after a reset. See Render's [free-plan limits](https://render.com/docs/free).

This option is for a short classroom demonstration, not persistent or production monitoring. The 512 MB free instance has much less memory than a developer laptop; if the process restarts because of memory pressure, its local files are lost too.

## Before creating the service

1. Review the source and attribution wording in `README.md`.
2. Push this project to a GitHub repository you control. Do not include `.venv/`, `data/`, logs, real telemetry, tokens, or passwords.
3. In Render, create a Blueprint from that repository and verify the service uses the `free` plan with no disk before confirming.
4. Create an administrator after deployment. Do not reuse a sensitive password or share it in chat.
5. Use only synthetic data. Expect logins and all saved data to reset after spin-down, restart, or deploy.

## Current limitations

- The dashboard is publicly reachable through Render and protected by the app's login screen. The ingest API is bound to loopback and is not exposed as a public endpoint.
- This is a prototype. It has not had a security audit, formal privacy review, load test, or external deployment validation.
- Render may restart or spin down the free instance, and its local files are ephemeral. Do not upload data you need to preserve.
- Use synthetic data for the public demo. Do not upload real employee logs to a public classroom deployment.
