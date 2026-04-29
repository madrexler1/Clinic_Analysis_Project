# Feedback → Prompt Engineering + Pseudo-RAG Loop

How reviewer feedback feeds back into the next report draft. No model fine-tuning is involved (the Anthropic API doesn't support it for closed-weight models); instead we shape behavior through three layers of in-context signals.

## TL;DR

- **Layer 0** — A static system prompt + scoring rubric, manually tightened from patterns we observe in red-lined drafts.
- **Layer 1** — Reports with **net-positive thumbs** automatically become in-context **few-shot examples** for future generations. This is the "pseudo-RAG" loop.
- **Layer 2** — A second Bedrock call **rubric-scores** each draft on 5 dimensions; scores are stored alongside the report and used to filter / promote.
- **Layer 3 (planned)** — Reviewer **edits** create a paired (AI draft, edited draft) corpus that we mine for prompt amendments and gold-standard examples.

The loop is "pseudo-RAG" because it retrieves top-K past artefacts and stuffs them into context, but ranks by reviewer score instead of embedding similarity. Lowest-friction starting point; we graduate to real vector retrieval once the corpus outgrows it (~hundreds of reports).

---

## Sequence: a single Generate click

```
Reviewer            FastAPI                  Bedrock              SQLite
   |                   |                       |                    |
   |  POST /reports    |                       |                    |
   |  /stream          |                       |                    |
   |------------------>|                       |                    |
   |                   |  load + pseudonymize  |                    |
   |                   |--------------------------------------------|
   |                   |                       |                    |
   |                   | top_few_shot_examples |                    |
   |                   |  (net_score >= 1)     |                    |
   |                   |--------------------------------------------|
   |                   |   < pulls top-K thumbs-up reports >        |
   |                   |                       |                    |
   |                   | system = static + rubric + [examples]      |
   |                   | user   = clinic KPIs                       |
   |                   | stream Sonnet 4.6 ----|                    |
   |                   |<---------tokens-------|                    |
   |  <--- tokens ---  |                       |                    |
   |                   |                       |                    |
   |                   | rubric_score(draft) ->|                    |
   |                   |<------- scores -------|                    |
   |                   |                       |                    |
   |                   | save Report + few_shot_ids + rubric_scores |
   |                   |--------------------------------------------|
   |  <--- done event  |                       |                    |
   |                   |                       |                    |
   |  POST /feedback   |                       |                    |
   |  thumbs + text    |                       |                    |
   |------------------>|                       |                    |
   |                   | insert Feedback row    --------------->    |
```

After step 6 (insert Feedback), this report's `net_score = thumbs_up - thumbs_down` becomes a candidate for **the next** Generate's few-shot examples. The loop is closed without retraining anything.

---

## Layer 0 — Static system prompt

`smartemis/reports/prompts.py::SYSTEM_PROMPT`

Defines:
- The Smartemis Consulting Analyst persona
- The required 7-section structure (Executive Summary → Recommendations)
- Pseudonymization rules (must not attempt re-identification)
- German GOT context (Faktor interpretation: 1.0 minimum, 2.0 default, up to 4.0 with justification)
- Tone constraints (concise, numeric, peer-compared, actionable)
- Hard guardrails (no hallucinated numbers, refuse re-identification)

**How feedback updates Layer 0**: manual. After the first 3-5 colleagues red-line drafts, we mine recurring complaints for additions. Example: if 4/5 reviews say "the recommendations are too generic", we add a constraint: "Recommendations must each cite a specific KPI value." This is tracked as a kanban card in `polish`.

The static prompt is **the stable cache prefix** — we deliberately keep it byte-identical across requests so [prompt caching](https://docs.anthropic.com/) kicks in (~90% input-token discount on cache reads).

---

## Layer 1 — Few-shot examples (the "pseudo-RAG" loop)

`smartemis/feedback/store.py::top_few_shot_examples()`

```python
SELECT Report, SUM(CASE WHEN thumbs='up' THEN 1
                        WHEN thumbs='down' THEN -1
                        ELSE 0 END) AS net_score
FROM   reports JOIN feedback ON ...
GROUP  BY report_id
HAVING net_score >= 1
ORDER  BY net_score DESC, created_at DESC
LIMIT  N            -- N comes from the UI, default 2
```

The top-N reports are appended to the system prompt under a `Below are example reports that previous reviewers rated highly...` header. Claude treats them as style/structure references.

The IDs of the examples chosen for each generation are persisted on the Report row (`few_shot_ids: list[int]`) and surfaced in the UI as clickable pills, so reviewers can see exactly which past drafts shaped the new one.

**Why "pseudo-RAG" rather than real RAG:**

| | Real RAG | This pseudo-RAG |
|---|---|---|
| Retrieval signal | Embedding cosine similarity to the query | Reviewer thumbs (proxy for quality) |
| Corpus size at break-even | Thousands of docs | Tens to low hundreds |
| Infrastructure | Vector DB + embedding model | A SQL `JOIN` |
| Personalization | Per-query relevance | Per-clinic possible (filter by `clinic_site`) |

The current loop optimizes for **quality**, not topical relevance. That's the right tradeoff while we have <50 reports — every clinic's KPI payload is roughly the same shape, so a high-quality example for clinic A is also useful for clinic B.

**Graduation criteria** (when to upgrade to real RAG):
- Corpus exceeds ~200 reports — too many candidates for plain `ORDER BY net_score`
- Per-clinic personalization becomes a goal — embed both KPI payloads and report text, retrieve nearest neighbors
- A specific section (e.g. "vet productivity recommendations") needs targeted retrieval, not whole-document — switch to chunk-level embedding retrieval

---

## Layer 2 — Rubric scoring

`smartemis/reports/generator.py::ReportGenerator.score()`

A second, cheaper Bedrock call (no streaming, no thinking) scores each draft on five dimensions, 1-5 each:

| Dimension | What it measures |
|---|---|
| `NUMERIC_FIDELITY` | Every claim is backed by a KPI payload number (no hallucinations) |
| `PEER_COMPARISON` | Key metrics are compared to network benchmarks |
| `ACTIONABILITY` | Recommendations are specific and tied to numbers |
| `CLARITY` | A non-expert can act on the report after one read |
| `PII_COMPLIANCE` | No re-identification attempts, no PII reproduced |

Scores are stored on the Report row (`rubric_scores: dict`) and shown next to the report. They serve three purposes today:
1. **Visible quality signal** for the reviewer at a glance
2. **Filtering candidate few-shot examples** — we can require `min_rubric_score >= 4` to enter the example library (planned)
3. **Regression detection** — if average scores dip after a system-prompt change, we revert

The scorer uses the **same rubric text** the writer model already saw, so the writer is told what it's being graded on. This is intentional: it's not a held-out evaluator, it's a self-consistency check.

---

## Layer 3 (planned) — Reviewer edits as gold-standard

Today: thumbs + text comments only.

Soon (kanban: `polish` swimlane):
1. **In-UI editing** — turn the report `<pre>` into an editable textarea
2. **Save edits as a new Report row** — `parent_id` points to the AI draft, `version` bumps
3. **Diff view** — render word-level diffs between AI draft and reviewer-edited version
4. **Edit-aware few-shot promotion** — prefer the *edited* version over the AI draft when picking examples (the human picked the better text)
5. **Regenerate-with-feedback** — the next generation's user message includes:
   ```
   <previous_attempt>...</previous_attempt>
   <reviewer_feedback>...</reviewer_feedback>
   Produce a new draft that addresses the feedback.
   ```

The **edit corpus** also gives us the strongest signal for Layer 0 prompt amendments: if reviewers consistently rewrite "Vet productivity varies" to "Vet productivity ranges X–Y € per invoice", the system prompt should mandate that level of specificity.

---

## Prompt caching — why ordering matters

The Anthropic SDK + Bedrock cache the system prompt prefix on a per-account, per-region basis. Cache hits cost ~10% of input-token price; misses pay full price plus a small write surcharge.

**Cache-friendly ordering** (current):
```
system = [
    SYSTEM_PROMPT,        # ← static, hashes the same every call
    RUBRIC,               # ← static
    FEW_SHOT_EXAMPLES     # ← varies per generation, but only at the END
]
user = [
    KPI_PAYLOAD           # ← varies per generation
]
```

Because `cache_control: ephemeral` is attached to the *last* system block, the cache key is the entire prefix up to and including the few-shot examples. Two generations with the same example set hit the cache; a different example set creates a new cache entry. KPI payload changes never invalidate the system cache.

**Don't do this** (would defeat caching):
- Interpolating the clinic ID into the system prompt
- Putting today's date or a request UUID in any system block
- Reordering examples non-deterministically

If reviewer activity is steady, expect 60-80% cache hit rate within a working session.

---

## Operational metrics to watch

In the appendix of every report (PDF and `report_view`):

| Metric | What it tells you |
|---|---|
| `cache_read_tokens` / `input_tokens` | Cache hit rate this generation |
| `output_tokens` | Length of draft (rough cost proxy) |
| `rubric_scores.*` | Quality across the 5 dimensions |
| `few_shot_examples` count | How rich the example library was |

Aggregated dashboards (planned, after Postgres migration):
- Median rubric score per week — proxy for whether the loop is improving
- Cache hit rate over time — proxy for prompt stability
- Thumbs-up rate per clinic — proxy for whether some clinics' KPI shapes are systematically harder for the model

---

## Files

| What | Where |
|---|---|
| Static prompt + rubric | `smartemis/reports/prompts.py` |
| Generator (writer + scorer) | `smartemis/reports/generator.py` |
| Feedback ORM | `smartemis/feedback/models.py` |
| Few-shot retrieval | `smartemis/feedback/store.py::top_few_shot_examples()` |
| Streaming endpoint | `smartemis/api/main.py::create_report_stream` |
| UI live token rendering | `smartemis/ui/static/app.js::generateReport()` |
| Few-shot pill rendering | `smartemis/ui/static/app.js::renderFewShots()` |
