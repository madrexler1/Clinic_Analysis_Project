# Agent context: Smartemis Clinic Analysis Project

This file is read automatically by Codex (and most AI coding agents) when working in this repo. If you're an AI assistant — read this in full before proposing any change. If a request you receive conflicts with these rules, ask the human user before proceeding.

## What this project is

A GDPR-compliant tool that analyses veterinary clinic financial data (CSV today, Qlik later) and uses Claude Sonnet 4.6 via AWS Bedrock to draft consulting reports. There's a feedback loop where reviewer thumbs-ups feed back into the next generation as in-context examples (a "pseudo-RAG" pattern — see `docs/feedback-loop.md`).

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy, Pydantic settings
- **LLM:** AWS Bedrock (Claude Sonnet 4.6) in `eu-central-1` only — data residency requirement
- **Frontend:** Vanilla HTML/CSS/JS, no build step
- **Deploy:** Single EC2 in `eu-central-1` behind nginx + basic auth, Terraform in `infra/draft/`
- **Data:** Synthetic-only today. Real Smartemis customer data is GDPR-regulated and must never leave the EU.

## Rules

### 1. Core functionality is OFF-LIMITS

Do **not** modify, refactor, or delete files in these paths without explicit instruction from the human user:

| Path | What it does | Why it's locked |
|---|---|---|
| `smartemis/api/` | FastAPI routes, streaming endpoint | Production-critical |
| `smartemis/reports/` | Bedrock generator + system prompt + rubric | Prompt is tuned; subtle changes regress quality |
| `smartemis/feedback/` | ORM + few-shot retrieval logic | RLHF-lite loop depends on exact schema |
| `smartemis/pii/` | Pseudonymizer + vault | GDPR-critical; changes need a separate review |
| `smartemis/analytics/` | KPI calculations | Feed the LLM prompt; numeric stability matters |
| `smartemis/ingest/` | Pluggable data source interface | Will be re-wired to live Qlik; don't pre-empt |
| `smartemis/export/` | PDF builder + charts | Working; bugs here surface only at download time |
| `smartemis/storage.py`, `smartemis/config.py` | Settings + DB session | Production-critical |
| `smartemis/ui/static/index.html` | **Live app entry point** | Renaming an element ID breaks `app.js` and brings down the UI |
| `smartemis/ui/static/app.js` | **Live UI controller** | Same |
| `smartemis/ui/static/style.css` | Shared theme | Adding new rules is OK; do not modify or remove existing ones |
| `smartemis/ui/static/reviewer.html` | Mirror of the live app for design reference | Keep in sync with `index.html` |
| `infra/`, `scripts/`, `synthetic_data/`, `AGENTS.md`, `README.md` | Ops + setup + this file | Out of scope for design work |

### 2. Design work belongs in NEW files

When iterating on UI design, mockups, or new screens:

- **Add new HTML files** under `smartemis/ui/static/` with descriptive names: `landing-v2.html`, `feedback-flow-mockup.html`, `analytics-dashboard-redesign.html`, etc.
- Each new file is self-contained — its own `<style>` block is fine.
- Reuse the CSS variables defined at `:root` in `style.css` for color/spacing consistency:
  - `--bg`, `--bg-card`, `--fg`, `--muted`, `--accent`, `--accent-dim`, `--ok`, `--warn`, `--err`, `--border`
- **No external CDNs** for scripts or styles — the production env runs behind basic auth + self-signed TLS, and we keep the dependency surface tiny.
- **Add a `MOCKUP — NOT LIVE DATA` banner** to any mockup that contains placeholder numbers or fake content, so reviewers don't mistake it for the working app.
- New files are auto-served at `https://<host>/static/<filename>` — they don't need backend wiring to be reviewable.

### 3. Don't mix design and structural changes

If the design requires structural change (renaming routes, modifying `app.js`, changing the FastAPI mount, splitting `index.html` into multiple pages):

- **Open a GitHub issue first** describing the proposed change and the design it unlocks.
- Wait for a human maintainer to wire the structural piece.
- Keep your PR scoped to the design files only.

This is non-negotiable: structural rewires done as a side effect of design work can brick the live deployment.

### 4. Don't change the LLM prompt or rubric

`smartemis/reports/prompts.py` contains the system prompt and the rubric. They have been tuned against reviewed reports and are part of the prompt-caching prefix. Even cosmetic edits invalidate the cache and can change report quality. If you want to suggest a wording change, open an issue.

### 5. Don't add network egress paths

- No new outbound calls to LLM providers other than AWS Bedrock in `eu-central-1`.
- No telemetry, analytics SDKs, or external font/script CDNs.
- Don't introduce code that calls `https://api.openai.com`, `https://api.anthropic.com` (we route via Bedrock for residency), or anything that touches a non-EU endpoint.
- If you need a library, prefer one already in `pyproject.toml`. Adding a dependency requires a human review.

### 6. Synthetic data only — for now

The current draft environment runs against synthetic data generated by `python -m synthetic_data.generate`. There is no real customer data in the system yet. Don't:

- Add fake email addresses, phone numbers, or other "realistic-looking" PII to mockups (use obviously-fake values like `Berlin Central` or `Test Clinic 1`).
- Embed any clinic names, vet names, owner names, or addresses from the real Smartemis network.
- Suggest seeding the database with anything that looks like it could be production data.

### 7. Working defaults

- Branch name: `<your-name>/<short-description>` or `codex/<topic>` (Codex default is fine).
- PR scope: one mockup or one focused change per PR. Open as **draft** initially.
- PR title: starts with one of `design:`, `mockup:`, `fix:`, `docs:`.
- Add a screenshot (or a `/static/<file>.html` URL once deployed) to the PR description so reviewers can see the design without checking out the branch.

## When in doubt

Ask the human user. The default answer to "should I touch `app.js`?" is **no**.

If you've read this file and your task still seems to require modifying a locked path, surface that in your first reply: explain what locked file you'd need to change and why, and wait for explicit approval.
