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

Tests use synthetic XML and temporary files, including malformed documents, exact sums, multiple outcomes, namespaces, nested suites, limits, CLI exit statuses and input preservation. CI runs Python 3.10, 3.12 and 3.14 with read-only repository permissions and no dependency installation.
