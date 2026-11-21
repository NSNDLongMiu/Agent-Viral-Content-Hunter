"""Run all T0 experiments and regenerate the Markdown report from evidence."""

from collections import Counter
from datetime import UTC, datetime

import e1_ai_cli
import e2_sources
import e3_telegram
import e4_queue_recovery
import e5_resources
from common import ROOT, Result, redact, write_text


EXPERIMENTS = [
    ("E1", "AI CLI structured output", e1_ai_cli.run),
    ("E2", "Public-source feasibility", e2_sources.run),
    ("E3", "Telegram Bot API", e3_telegram.run),
    ("E4", "Windows queue crash recovery", e4_queue_recovery.run),
    ("E5", "Host and local AI survey", e5_resources.run),
]


def cell(value):
    return value.replace("|", r"\|").replace("\n", " ")


def row(*cells):
    return "| " + " | ".join(cell(value) for value in cells) + " |"


def aggregate(code, results):
    counts = Counter(result.verdict for result in results)
    if code in {"E1", "E2"} and counts["PASS"]:
        verdict = "PASS"
    elif counts["FAIL"]:
        verdict = "FAIL"
    elif counts["BLOCKED"]:
        verdict = "BLOCKED"
    else:
        verdict = "PASS"
    return verdict, ", ".join(f"{counts[key]} {key}" for key in ("PASS", "FAIL", "BLOCKED") if counts[key])


def report(groups):
    lines = ["# T0 Feasibility Spike", "", f"Completed {datetime.now(UTC).isoformat(timespec='seconds')}.",
             "Reproduce from the repository root with `python spikes/run_all.py` (standard library only).", "",
             "| Experiment | Verdict | Checks |", "| --- | --- | --- |"]
    for code, label, results in groups:
        lines.append(row(f"{code} {label}", *aggregate(code, results)))
    lines += ["", "E1 and E2 summarize whether at least one integration passed. Individual verdicts govern which integrations can be used.",
              "", "## Evidence by check", "", "| Check | Verdict | Evidence | Limitations | Recommendation |",
              "| --- | --- | --- | --- | --- |"]
    for _, _, results in groups:
        for item in results:
            lines.append(row(item.experiment, item.verdict, item.evidence, item.limits, item.recommendation))

    ai = groups[0][2]
    sources = groups[1][2]
    connector_order = ("Hacker News", "Wikimedia", "Google Trends", "YouTube", "Weibo")
    verified = {result.experiment[3:] for result in sources if result.verdict == "PASS"}
    connectors = [name for name in connector_order if name in verified]
    adapters = [result.experiment[3:] for result in ai if result.verdict == "PASS"]
    lines += ["", "## Build order", ""]
    if connectors:
        lines.append(f"- Start with {', '.join(connectors)}, in that order.")
    else:
        lines.append("- Validate Hacker News and Wikimedia first from a Windows session with normal network access. "
                     "Their public API documentation makes them the first discovery candidates. "
                     "Google Trends RSS and YouTube channel monitoring are the next probes.")
    if adapters:
        lines.append(f"- Start with the verified subscription CLI adapters for {', '.join(adapters)}.")
    else:
        lines.append("- Begin with rule-based normalization, deduplication and scoring. "
                     "Retest Claude Code first if its subscription login and included-only billing are available. "
                     "Keep AI review pending where the product requires it.")

    lines += ["", "## Reproduction notes", "",
              "- The scripts preserve TLS verification. Source requests use no proxy, cookies or automatic retries. "
              "An empty sample lists the attempted URLs, transport outcomes and relevant policy. "
              "HTTP status is absent when the local request did not complete an HTTP exchange.",
              "- E1 sends a model prompt only after the installed CLI reports subscription auth and the account owner has "
              "verified that the account can use only included subscription allowance. After verifying that paid usage credits "
              "and automatic purchases are unavailable or disabled, name the verified provider(s) in "
              "`T0_SPIKE_INCLUDED_USAGE_ONLY` as `claude`, `codex` or `claude,codex` for that run. "
              "The scripts do not change account settings. A [local child-process timeout check](out/e1_timeout.json) "
              "exercises the Python launcher deadline. Vendor behavior when a model request times out is unverified unless observed in the run.",
              f"- E3 setup. {e3_telegram.SETUP}",
              "- E4 treats three retries as one initial attempt plus at most three retry attempts. "
              "The interrupted job is deliberately attempted again after its lease expires. A unique SQLite effect "
              "in the same transaction as completion is the duplicate check. A failed `taskkill` invocation is recorded independently "
              "when Windows process handles provide the hard termination.",
              ""]
    return "\n".join(lines)


def main():
    groups = []
    for code, label, run in EXPERIMENTS:
        try:
            results = run()
        except Exception as exc:
            results = [Result(f"{code} {label}", "FAIL", f"Unexpected runner error ({type(exc).__name__}).",
                              "This experiment did not finish.", "Inspect the standalone experiment before integration.")]
        verdict, counts = aggregate(code, results)
        print(f"{code} {verdict} ({counts})", flush=True)
        groups.append((code, label, results))
    write_text(ROOT / "REPORT.md", redact(report(groups)))
    print("Wrote spikes/REPORT.md")


if __name__ == "__main__":
    main()
