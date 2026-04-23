# Smartemis Agent

Clinic-level financial analysis + Claude Sonnet 4.6 consulting report drafting for the Smartemis network (FR/DE veterinary clinics), with an RLHF-lite feedback loop.

**Data residency:** All personal data processing must run in **AWS `eu-central-1` (Frankfurt)** via **AWS Bedrock**. The code on this branch is scaffold only; it can run locally against **synthetic** data, but real Smartemis FR/DE customer data must never leave the EU or touch a US developer's machine.

---

## Status

- **Phase 1 (this branch):** local scaffold, synthetic data, end-to-end pipeline, FastAPI + HTML reviewer UI. ✅
- **Phase 2 (next):** Terraform IaC for `eu-central-1` — VPC, EC2, RDS, KMS, VPC endpoints, SSM access, CloudTrail. *(Not started.)*
- **Phase 3:** i18n FR/DE translation pass. *(Not started.)*
- **Phase 4:** Qlik ingestion source, rubric-mining learn loop. *(Stubbed.)*

---

## Architecture

```
[CSV or Qlik] → ingest/    (pluggable source)
              → pii/       (vault + pseudonymize: vet_name, invoice#, treatment#, PLZ→prefix, DOB→YYYY-MM)
              → analytics/ (clinic KPIs, peer benchmarks)
              → reports/   (AWS Bedrock Claude Sonnet 4.6, streaming, prompt-cached system+rubric+few-shots)
              → feedback/  (thumbs + text + rubric scores)
              → api/       (FastAPI, served with static HTML/JS UI)
```

The LLM prompt receives **only** aggregated KPIs + pseudonymized IDs. The raw dataset and `pii_vault` never leave the EC2 instance. Feedback (thumbs + text) promotes high-rated past reports into the few-shot example library for future generations, shifting output toward reviewer preferences without fine-tuning.

---

## Local development

Prerequisites: Python 3.11+, AWS credentials with Bedrock access in `eu-central-1` (for the LLM; see note below).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -e ".[dev]"
cp .env.example .env            # edit SMARTEMIS_PSEUDO_SALT and AWS region

# 1. Generate synthetic data (mirrors real Smartemis schema)
python -m synthetic_data.generate --invoices 2000 --clinics 12

# 2. Run the app
uvicorn smartemis.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 — pick a clinic (`DE1001`, `DE1002`, ...), click Generate, review, thumbs up/down + comment.

> **Bedrock access.** For local dev you need an IAM user or SSO profile with `bedrock:InvokeModelWithResponseStream` on the EU Sonnet 4.6 cross-region profile. In production the EC2 instance role provides this — no local creds needed. If Bedrock isn't available, the ingestion + analytics + UI all still work; only report generation will fail.

---

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Env, region, model |
| GET | `/api/clinics` | List clinic sites |
| GET | `/api/clinics/{site}/kpis` | Inspect the LLM payload for one clinic |
| POST | `/api/reports` | Generate a report (body: `clinic_site`, `few_shot_n`, `score_after_generate`) |
| GET | `/api/reports` | Recent reports with net feedback |
| GET | `/api/reports/{id}` | One report + rubric scores |
| POST | `/api/reports/{id}/feedback` | Body: `reviewer`, `thumbs` (`up`/`down`/`none`), `comment` |

---

## GDPR controls in code

| Requirement | Where it lives |
|---|---|
| Residency | `SMARTEMIS_BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6-v1:0`, `AWS_REGION=eu-central-1`. Bedrock keeps data in-region. |
| Pseudonymization (Art. 32) | `smartemis/pii/pseudonymize.py` — HMAC-SHA256 with server-side salt; vault in `smartemis/pii/vault.py` |
| Data minimization | KPI payload sent to LLM contains no raw rows, no names, no full PLZs, no pet DOBs |
| Free-text PII scrubbing | `pseudonymize._scrub_freetext` — emails, IBANs, phones redacted |
| Right to erasure (Art. 17) | `PIIVault.purge_original(kind, original)` |
| Audit trail | Application writes report + feedback rows with timestamps + reviewer names; CloudTrail will cover infra access once deployed |
| Secrets | Pulled from `.env` locally; must come from AWS Secrets Manager in prod |

**Outside this codebase — required before processing real data:**
- [ ] DPA signed with Smartemis (controller ↔ processor relationship).
- [ ] DPIA filed (Art. 35 — large-scale profiling of financial data makes this likely mandatory).
- [ ] ROPA (Art. 30) covering this processing activity.
- [ ] AWS DPA acknowledged in the AWS account.
- [ ] Sub-processor disclosure to Smartemis (AWS + Anthropic-via-Bedrock).
- [ ] Rotate `SMARTEMIS_PSEUDO_SALT` per-client, stored in Secrets Manager.

---

## Terraform deployment (Phase 2 — to build next)

Planned `infra/` layout (not yet implemented):

```
infra/
├── main.tf                    VPC (eu-central-1, private subnets only)
├── ec2.tf                     EC2 app server, instance role with Bedrock + Secrets Manager
├── rds.tf                     Postgres (KMS CMK, no public IP)
├── kms.tf                     Customer-managed key
├── ssm.tf                     Session Manager for us-based dev access
├── endpoints.tf               VPC endpoints: S3, Secrets Manager, Bedrock, CloudWatch
├── cloudtrail.tf              Org trail → separate logging bucket, object lock
├── iam.tf                     Least-priv roles
└── variables.tf
```

US-based dev access pattern: `aws ssm start-session --target <instance-id>` + port-forward localhost:8000. No SSH, no public ingress, everything audited.

---

## Repo layout

```
smartemis/
├── config.py              Pydantic settings
├── storage.py             SQLAlchemy engine, shared Base
├── ingest/                Pluggable source (CSV today, Qlik stub)
├── pii/                   PII vault + pseudonymizer
├── analytics/             Clinic KPIs + peer benchmarks
├── reports/               Bedrock Claude generator + system/rubric prompts
├── feedback/              Reports + feedback ORM, FeedbackStore, few-shot selection
├── api/                   FastAPI app + routes + pipeline wrapper
└── ui/static/             HTML + CSS + JS reviewer UI (no build step)

synthetic_data/            Synthetic CSV generator matching real schema
infra/                     Terraform (Phase 2 — todo)
tests/                     (empty — add as features solidify)
```

---

## What to build next, in order

1. **Wire real data (still synthetic scale, but run end-to-end).** Generate 10k+ invoices, run through UI, look at reports. Fix prompt quality issues before deploying.
2. **Terraform Phase 2.** Stand up `eu-central-1` infra. Deploy. SSM into it. Confirm Bedrock works in-region.
3. **FR/DE translation.** Add a translate pass in `reports/` — same Bedrock call, `{target_lang: "fr" | "de"}`.
4. **Move feedback DB to Postgres.** Change `SMARTEMIS_DB_URL` to the RDS endpoint; no code change needed.
5. **Rubric mining.** Nightly job that reads low-rated reports' comments and proposes system-prompt amendments (human-approved before they land).
6. **Qlik source.** Implement `smartemis/ingest/qlik_source.py::read_raw()` against the Smartemis Qlik app.
