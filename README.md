# JUnit Report Summary

Turn local JUnit XML test reports into one JSON or Markdown summary. Counts come from actual testcases, so nested suite counters cannot inflate the result. Python 3.10 or newer; standard library only. No installation, network, test execution or report modification.

[Português brasileiro](README.pt-BR.md) · [MIT](LICENSE)

## Try the synthetic report

```sh
python -m junit_report_summary examples/backend.xml
python -m junit_report_summary examples/backend.xml --format markdown
python -m junit_report_summary examples/backend.xml --fail-on-problems
# Exit 1: this demonstration intentionally contains one failed testcase.
```

The example contains three tests: one passed, one failed and one skipped, with exactly `0.6` seconds of summed testcase time. Failure messages and stack traces are omitted. For multiple reports, provide explicit paths in the desired order:

```sh
python -m junit_report_summary reports/unit.xml reports/integration.xml --format markdown
```

The CLI performs no glob expansion or recursive discovery. Your shell may expand globs before the program runs. It accepts regular files, including symlinks to regular files, and rejects directories and special files. JSON is the default. Invalid inputs produce a generic stderr message, exit `2`, and **no partial stdout**. Default exit status is `0` even when tests failed. Add `--fail-on-problems` for exit `1` when a testcase contains a failure or error; skipped tests alone do not cause failure. `--help` exits `0`.

## Use the library

```python
from pathlib import Path
from junit_report_summary import parse_report, combine_reports, format_markdown

first = parse_report(Path("examples/backend.xml").read_bytes(), source="backend")
combined = combine_reports([first])
assert combined["summary"] == {
    "tests": 3, "passed": 1, "failures": 1, "errors": 0,
    "skipped": 1, "duration_seconds": "0.6",
}
print(format_markdown(combined))
```

`parse_report(data: bytes, source="report.xml")` returns `{source, summary, cases}`. `combine_reports(reports)` takes a list or tuple of those parsed dictionaries and returns `{sources, summary, cases}`. It recalculates totals and copies records, preserving caller/report order and duplicate cases. Both raise `ReportError`, a `ValueError` subclass, for invalid supported input. The combination API consumes this library's records; it is not a general-purpose arbitrary-object sandbox.

Each case has `name`, `class_name`, `suite` (an ordered list of enclosing suite names), `status`, `duration_seconds` and `source`. Missing class/suite names are empty strings. A testcase name must be nonempty. `status` is one of `passed`, `failure`, `error` or `skipped`. If a producer emits multiple outcome markers, precedence is **error, failure, skipped, passed**; the case still counts once.

Durations are exact decimal strings, never binary floats. Missing testcase time is zero. Suite `tests`, `failures`, `errors`, `skipped` and `time` attributes are advisory and ignored. Total duration is the sum of testcase durations: it is **not wall-clock elapsed time**, especially for parallel tests. There is no automatic case deduplication, retry interpretation or merging of parametrized names.

## Compare observed outcomes across runs

Use `--history` to treat each explicit file argument as a separate run, in the order supplied. The run ID is the input argument path exactly, including any relative-path spelling. The ordinary CLI still combines reports as before when `--history` is absent.

```sh
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml --format markdown
python -m junit_report_summary --history examples/history/run-1.xml examples/history/run-2.xml examples/history/run-3.xml --fail-on-problems
# Exit 1: a failure or error was observed in these synthetic runs.
```

These three reports contain 13 observations across five distinct test identities. Their history summary is `{"tests": 5, "mixed": 1, "problem_only": 1, "pass_only": 2, "skipped_only": 1}`. `test_optional` is missing from run 2; `test_new` is missing from run 1. A missing observation is neither a failure nor a skipped outcome.

```python
from pathlib import Path
from junit_report_summary import (
    analyze_history, format_history_markdown, parse_report,
)

runs = [
    {
        "id": f"run-{number}",
        "report": parse_report(
            Path(f"examples/history/run-{number}.xml").read_bytes(),
            source=f"local-report-{number}.xml",
        ),
    }
    for number in (1, 2, 3)
]
history = analyze_history(runs)
assert history["summary"] == {
    "tests": 5, "mixed": 1, "problem_only": 1,
    "pass_only": 2, "skipped_only": 1,
}
assert history["tests"][0]["identity"] == {
    "suite": ["service", "auth"], "class_name": "Auth",
    "name": "test_login[user]",
}
assert history["tests"][0]["counts"] == {
    "passed": 2, "failure": 1, "error": 0, "skipped": 0,
}
assert history["tests"][3]["missing_runs"] == ["run-2"]
assert history["tests"][4]["missing_runs"] == ["run-1"]
print(format_history_markdown(history))
```

`analyze_history(runs)` accepts a list or tuple of 1 through 100 dictionaries, each containing exactly `{"id": str, "report": parse_report_result}`. Run IDs must be unique, nonempty, at most 128 characters, and contain no ASCII C0 control characters (`U+0000` through `U+001F`) or DEL (`U+007F`). Empty reports are valid. Across all runs, at most `MAX_CASES` (100,000) testcase observations are accepted, including repeated identities in different runs. Parsed case records and durations are validated with the existing rules; supplied summary counters are advisory and recalculated. Mutable input records are copied and left unchanged.

A test's identity is the exact triple **`(tuple(suite), class_name, name)`**. Suite ancestry, class and the complete name all matter; parameterized names stay distinct. A report's source label is not part of identity. A duplicate identity within one run is ambiguous and raises `ReportError`: retries are never silently aggregated or deduplicated. The ordinary `combine_reports` API continues to retain duplicate cases.

The output contains exactly `runs`, `summary` and `tests`. `runs` lists the supplied IDs. `summary.tests` counts distinct identities; its other four counters count identities in each classification:

| Classification | Observed outcomes |
| --- | --- |
| `mixed` | At least one pass and at least one failure or error; skips may also occur. |
| `problem_only` | At least one failure or error and no passes; skips may also occur. |
| `pass_only` | At least one pass and no failures or errors; skips may also occur. |
| `skipped_only` | Every observed outcome is skipped. |

Each entry in `tests` contains exactly `identity` (`suite`, `class_name`, `name`), `classification`, `counts` (`passed`, `failure`, `error`, `skipped`), `observations` (entries with `run` and `status`) and `missing_runs`. Counts measure observations, while summary counters measure distinct identities. Identities appear in first-observed order; observations and missing run IDs follow the explicit run order. History contains no durations, source labels or diagnostic payloads.

History is built in memory. The number of missing-run entries can grow with distinct identities multiplied by the number of supplied runs (up to 100,000 by 100), so output can be large even within these bounds, especially with long identifiers. Results are complete rather than truncated.

The supplied ordering does not establish chronology or prove that runs used the same code or environment. `mixed` describes differing observed outcomes only; it does not infer flakiness, retry intent, a regression or its cause, or a missing-test failure.

`format_history_markdown(history)` renders deterministic, escaped tables with classifications, outcome counts and missing runs. The CLI applies the existing `--format`, ASCII JSON, exit-status and no-partial-stdout rules to history too: all inputs parse and validate before output; a failure or error in any run triggers exit `1` only with `--fail-on-problems`; skips alone do not. Duplicate file path arguments and ambiguous identities produce the generic stderr error and exit `2`. History performs no glob discovery.

## Supported XML and limits

- Root `testsuite` or `testsuites`; either may contain nested grouping nodes of those names. XML namespaces are accepted by local element name. Only a direct `testcase` child of a recognized `testsuite` contributes a result.
- Unknown extension subtrees are opaque. Failure/error descriptions, `system-out`, `system-err`, properties and attachments are not included or resolved. A `testcase`-looking element inside an extension cannot add a result.
- UTF-8 bytes, with optional UTF-8 BOM and UTF-8 XML declaration. Malformed XML, other encodings and any `<!DOCTYPE` or `<!ENTITY` marker are rejected, including markers inside comments. No XML entity declarations, file or URL resolution.
- At most 16 MiB per report, XML nesting depth 32, 300,000 XML elements and 100,000 cases. Combined output also caps cases at 100,000. Parsing builds a bounded in-memory XML tree; this is not an unlimited streaming processor.
- Times must use unsigned decimal notation with an optional decimal exponent, up to 512 characters, scale exponent from -128 through 128 and at most 128 integer digits. Negative, nonfinite, malformed and larger values are rejected. Exact sums use enough decimal precision for these bounds and the case cap.

This targets the common JUnit reporting dialect rather than claiming conformance to one universal JUnit XML specification. It does not validate a producer's suite counters or infer whether its report is complete.

Markdown identifiers are escaped to prevent their HTML, table delimiters and inline link syntax from becoming markup. JSON uses ASCII escapes for portable stdout. Report paths, testcase names and class/suite names can still reveal sensitive information: review the generated summary before publishing it. This tool removes diagnostic payloads; it is **not a general secrets scrubber**.

## Develop

```sh
python -m unittest discover -s tests -v
```

Tests use synthetic XML and temporary files, including malformed documents, exact sums, multiple outcomes, namespaces, nested suites, history classifications and identities, missing observations, limits, CLI exit statuses and input preservation. CI runs Python 3.10, 3.12 and 3.14 with read-only repository permissions and no dependency installation.
