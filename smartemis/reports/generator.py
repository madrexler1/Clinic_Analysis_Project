"""Claude Sonnet 4.6 report drafter via AWS Bedrock (eu-central-1).

Design notes:
  - Uses the `anthropic[bedrock]` AnthropicBedrock client so payloads stay in
    eu-central-1 — no cross-border data transfer.
  - Streams responses (reports are long-form; streaming prevents HTTP timeouts).
  - Prompt caching on the stable prefix: system prompt + rubric + few-shot
    examples. The volatile per-clinic KPI payload goes in `messages`, so cache
    is reused across every clinic in a network run.
  - Adaptive thinking — Sonnet 4.6 decides how much to reason per report.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from anthropic import AnthropicBedrock

from smartemis.config import Settings, get_settings
from smartemis.reports.prompts import FEW_SHOT_HEADER, RUBRIC, SYSTEM_PROMPT

if TYPE_CHECKING:
    from smartemis.analytics.kpis import ClinicKPIs


@dataclass(slots=True)
class ReportDraft:
    clinic_site: str
    text: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    few_shot_ids: list[int]


class ReportGenerator:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AnthropicBedrock | None = None,
    ):
        self.settings = settings or get_settings()
        # AnthropicBedrock reads AWS creds via the standard boto3 chain.
        # On EC2 in eu-central-1 this picks up the instance role — no keys in code.
        self.client = client or AnthropicBedrock(aws_region=self.settings.aws_region)

    def _build_system(self, few_shot_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": RUBRIC},
        ]
        if few_shot_examples:
            lines = [FEW_SHOT_HEADER]
            for ex in few_shot_examples:
                lines.append(f"\n--- Example (peer-rated +{ex['score']}) ---\n{ex['text']}")
            blocks.append({"type": "text", "text": "\n".join(lines)})

        # Single cache breakpoint at the end of the stable prefix. Sonnet 4.6
        # min cacheable prefix is 2048 tokens — system prompt + rubric clears
        # that on its own; adding examples only increases the payoff.
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
        return blocks

    def _build_user_message(
        self, kpis: "ClinicKPIs", peer_benchmarks: dict[str, Any]
    ) -> str:
        payload = {
            "clinic_kpis": kpis.as_prompt_payload(),
            "network_peer_benchmarks": peer_benchmarks,
        }
        return (
            "Draft the clinic performance report for the data below. Follow the "
            "required section structure exactly.\n\n"
            f"<kpi_payload>\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n</kpi_payload>"
        )

    def generate(
        self,
        kpis: "ClinicKPIs",
        peer_benchmarks: dict[str, Any],
        *,
        few_shot_examples: list[dict[str, Any]] | None = None,
        max_tokens: int = 8000,
    ) -> ReportDraft:
        """Stream a report from Bedrock Claude Sonnet 4.6 and return the full draft."""
        system_blocks = self._build_system(few_shot_examples or [])
        user_content = self._build_user_message(kpis, peer_benchmarks)

        text_parts: list[str] = []
        with self.client.messages.stream(
            model=self.settings.bedrock_model_id,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system_blocks,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)
            final = stream.get_final_message()

        return ReportDraft(
            clinic_site=kpis.clinic_site,
            text="".join(text_parts),
            model_id=self.settings.bedrock_model_id,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            cache_read_tokens=getattr(final.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
            few_shot_ids=[ex["id"] for ex in (few_shot_examples or []) if "id" in ex],
        )

    def score(self, report_text: str) -> dict[str, Any]:
        """Second-pass rubric scorer. Returns a dict of 1-5 scores per dimension."""
        scoring_system = (
            "You are a strict QA scorer for Smartemis consulting reports. "
            "Return ONLY valid JSON with integer 1-5 scores on each rubric dimension "
            "plus a short 'reason' field for each.\n\n" + RUBRIC
        )
        user = (
            "Score the following report against the rubric. Return JSON with keys: "
            "NUMERIC_FIDELITY, PEER_COMPARISON, ACTIONABILITY, CLARITY, PII_COMPLIANCE. "
            "Each value is an object {score: int, reason: str}.\n\n"
            f"<report>\n{report_text}\n</report>"
        )
        resp = self.client.messages.create(
            model=self.settings.bedrock_model_id,
            max_tokens=1500,
            system=scoring_system,
            messages=[{"role": "user", "content": user}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {"_parse_error": True, "raw": text}
