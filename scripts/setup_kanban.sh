#!/usr/bin/env bash
###############################################################################
# One-time bootstrap: creates the Smartemis kanban as a GitHub Project (v2)
# with 5 swimlane labels and 30 issues organized by phase.
#
# Prereqs:
#   - gh CLI installed and authenticated
#   - `gh auth refresh -s project,read:project`
#   - run from inside the repo (so `gh issue create` knows which repo)
#
# Idempotency: labels use --force; issues are created fresh each run, so don't
# re-run blindly — you'll get duplicates. If you need to start over, delete the
# project + issues from the GitHub UI first.
###############################################################################
set -euo pipefail

OWNER="madrexler1"
PROJECT_TITLE="Smartemis to live data"

echo "=== 1. Creating swimlane labels ==="
declare -A LABEL_COLOR=(
  [polish]=a2eeef
  [i18n]=fbca04
  [prod-infra]=0e8a16
  [legal]=d4c5f9
  [cutover]=b60205
)
for label in "${!LABEL_COLOR[@]}"; do
  gh label create "$label" --color "${LABEL_COLOR[$label]}" --force \
    --description "Smartemis kanban swimlane: $label" >/dev/null
done

echo "=== 2. Creating project ==="
# gh has gojq built in via --jq, so we don't need a separate jq install.
PROJECT_URL=$(gh project create --owner "$OWNER" --title "$PROJECT_TITLE" --format json --jq .url)
PROJECT_NUMBER=$(basename "$PROJECT_URL")
echo "Project: $PROJECT_URL"

echo "=== 3. Creating issues + adding to project ==="
add_card() {
  local label="$1" title="$2" body="$3"
  local url
  url=$(gh issue create --title "$title" --body "$body" --label "$label" | tail -1)
  gh project item-add "$PROJECT_NUMBER" --owner "$OWNER" --url "$url" >/dev/null
  echo "  + [$label] $title"
}

# ----- POLISH -----
add_card polish "Add Smartemis logo to PDF cover page" \
  "Drop logo PNG at smartemis/ui/static/logo.png and embed it in pdf.py cover. Replace the wordmark."
add_card polish "Tighten LLM system prompt from reviewed drafts" \
  "After 3-5 colleagues red-line drafts, mine the comments for repeating instructions. Append to system prompt."
add_card polish "In-UI report editing for colleagues" \
  "Switch the report <pre> to a <textarea>; persist edits via PATCH /api/reports/{id}. Mark edited reports clearly."
add_card polish "Save reviewer-edited reports as new versions" \
  "Each save creates a new Report row with parent_id pointing at the AI draft, version field bumped."
add_card polish "Regenerate-with-feedback button" \
  "Pulls the report's free-text feedback into the next generation prompt as steering context."
add_card polish "Side-by-side diff view: AI draft vs edit" \
  "Two columns, word-level diff highlighting (e.g. diff-match-patch) so reviewers see what they changed."

# ----- i18n -----
add_card i18n "Language toggle (EN / FR / DE) in UI" \
  "Top-right dropdown. Sticky preference per browser. Triggers /api/reports/{id}?lang=fr re-fetch."
add_card i18n "Bedrock translation pass for report body" \
  "Same Sonnet 4.6 call, separate prompt: translate EN draft to FR/DE preserving structure. Cache the system prompt."
add_card i18n "Translate static UI strings" \
  "Pull form labels, headers, status messages into a translations.json. UI reads via lang param."
add_card i18n "Translate PDF labels and headings" \
  "smartemis/export/pdf.py: section titles, tile labels, footer. Per-language style dict."
add_card i18n "Verify GOT vocabulary translates faithfully" \
  "Spot-check terms: Faktor, GOT-Nummer, Notdienst, Behandlung. Lock with a glossary block in the system prompt."

# ----- PROD-INFRA -----
add_card prod-infra "infra/prod Terraform: VPC + private subnets + NAT" \
  "New module — no default VPC. Two AZs, private subnets, single NAT in the cheaper AZ to start."
add_card prod-infra "RDS Postgres in private subnet with KMS CMK" \
  "db.t3.small or t4g.micro to start. KMS customer-managed key. Multi-AZ off in prod-lite, on for full prod."
add_card prod-infra "VPC endpoints: Bedrock, Secrets Manager, S3, SSM" \
  "PrivateLink endpoints so traffic stays in-region. Tighten EC2 egress security group accordingly."
add_card prod-infra "CloudTrail org trail to dedicated logging bucket" \
  "Object Lock + bucket policy denying delete. Includes Bedrock data events."
add_card prod-infra "SQLite → Postgres code migration with Alembic" \
  "Alembic init, baseline migration matching current schema. Test on infra/draft before prod."
add_card prod-infra "Implement QlikSource.read_raw against live Qlik app" \
  "Replace the stub. Match the German column schema exactly so _normalize() handles it transparently."
add_card prod-infra "Per-client pseudo-salt from Secrets Manager" \
  "Secret per Smartemis client. Rotate quarterly. Different salts → different pseudonyms (no cross-client leakage)."
add_card prod-infra "Application-level audit log (report views)" \
  "New table: audit_log(reviewer, report_id, clinic_site, action, timestamp). Required for GDPR Art. 32 access tracking."
add_card prod-infra "AWS Backup plan: RDS + EBS, 30-day retention, EU-only" \
  "Backup vault with KMS CMK. Cross-region copy disabled (data residency)."
add_card prod-infra "CloudWatch alarms: instance/RDS CPU, API 5xx, Bedrock 4xx" \
  "SNS topic → email. P0 = service down. P1 = error rate spike."

# ----- LEGAL (non-code, parallel track) -----
add_card legal "Sign DPA with Smartemis" \
  "Controller/processor relationship clarified in writing. Defines which party is responsible for what under GDPR."
add_card legal "File DPIA (Art. 35)" \
  "Large-scale profiling of clinic financials triggers Art. 35. Document risks + mitigations + sign-off."
add_card legal "Add ROPA entry (Art. 30)" \
  "Record of Processing Activities listing this app, data categories, retention, sub-processors."
add_card legal "Sub-processor disclosure to Smartemis" \
  "Notify Smartemis of AWS + Anthropic-via-Bedrock as sub-processors. Get acknowledgement."
add_card legal "DSAR handling procedure" \
  "Process for responding to data subject access / erasure requests. Wire to PIIVault.purge_original()."
add_card legal "Incident response runbook" \
  "Detection → containment → notification (incl. 72h GDPR window) → post-mortem template."

# ----- CUTOVER -----
add_card cutover "Pilot with 1-2 friendly clinics on real data" \
  "Pre-conditions: prod-infra Done, legal track Done, pseudonymizer reviewed against real data shape."
add_card cutover "Drift check: LLM drafts vs consultant-written equivalents" \
  "Have a consultant write reports for 5 clinics manually; compare to LLM output. Tune prompt where they disagree."
add_card cutover "Phased rollout + decommission draft env" \
  "10% → 50% → 100% of clinics. Once stable, terraform destroy on infra/draft (or repurpose as sandbox)."

echo ""
echo "==================================================================="
echo "Done. Project board: $PROJECT_URL"
echo "==================================================================="
echo ""
echo "Next: open the URL, drag the Status field options if you want richer"
echo "columns (Backlog / Up Next / In Progress / Review / Done). Or use"
echo "filters by label to focus on one swimlane at a time."
