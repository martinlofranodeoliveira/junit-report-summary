"""Bounded, offline summaries of JUnit XML reports. Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
from decimal import Context, Decimal, InvalidOperation, localcontext
import io
import json
import os
import re
import stat
import sys
import xml.etree.ElementTree as ET

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 32
MAX_ELEMENTS = 300_000
MAX_CASES = 100_000
_FIELDS = ("tests", "passed", "failures", "errors", "skipped")
_TIME = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_ENCODING = re.compile(r"\A<\?xml\s+[^?]*?\bencoding\s*=\s*(['\"])(.*?)\1", re.I)


class ReportError(ValueError):
    """The report is invalid or exceeds a documented resource limit."""


def _bad() -> None:
    raise ReportError("Invalid JUnit report.")


def _duration(value: str) -> Decimal:
    # Keep normalized output and exact summation bounded even for exponent input.
    if len(value) > 512 or not _TIME.fullmatch(value):
        _bad()
    try:
        number = Decimal(value)
    except InvalidOperation:
        _bad()
    if not number.is_finite() or number < 0 or abs(number.as_tuple().exponent) > 128:
        _bad()
    if number and number.adjusted() > 127:
        _bad()
    return number


def _decimal_text(number: Decimal) -> str:
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _summary(cases: list[dict]) -> dict:
    counts = dict.fromkeys(_FIELDS, 0)
    names = {"passed": "passed", "failure": "failures", "error": "errors", "skipped": "skipped"}
    with localcontext(Context(prec=300, Emin=-999999, Emax=999999)) as context:
        # 128 significant integer/fraction digits plus case-count carry.
        context.prec = 300
        seconds = Decimal(0)
        for case in cases:
            counts["tests"] += 1
            counts[names[case["status"]]] += 1
            seconds += _duration(case["duration_seconds"])
    counts["duration_seconds"] = _decimal_text(seconds)
    return counts


def parse_report(data: bytes, source: str = "report.xml") -> dict:
    """Parse UTF-8 XML bytes; counters come from cases, never suite attributes.

    Unknown extension subtrees are opaque. Only recognized grouping children
    of recognized grouping nodes can contribute suites or testcases.
    """
    if not isinstance(data, bytes) or len(data) > MAX_BYTES or not isinstance(source, str):
        _bad()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _bad()
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        _bad()
    declaration = _ENCODING.match(text)
    if declaration and declaration.group(2).lower() != "utf-8":
        _bad()
    depth = elements = 0
    try:
        parser = ET.iterparse(io.StringIO(text), events=("start", "end"))
        for event, _element in parser:
            if event == "start":
                depth += 1
                elements += 1
                if depth > MAX_DEPTH or elements > MAX_ELEMENTS:
                    _bad()
            else:
                depth -= 1
        root = parser.root
    except (ET.ParseError, ValueError) as exc:
        raise ReportError("Invalid JUnit report.") from exc
    if _local(root.tag) not in {"testsuite", "testsuites"}:
        _bad()
    cases: list[dict] = []

    def walk(group: ET.Element, parents: tuple[str, ...]) -> None:
        kind = _local(group.tag)
        suites = parents + (group.get("name", ""),) if kind == "testsuite" else parents
        for child in group:
            child_kind = _local(child.tag)
            if child_kind in {"testsuite", "testsuites"}:
                walk(child, suites)
            elif kind == "testsuite" and child_kind == "testcase":
                name = child.get("name")
                if not name or len(cases) >= MAX_CASES:
                    _bad()
                markers = {_local(item.tag) for item in child}
                outcome = next((x for x in ("error", "failure", "skipped") if x in markers), "passed")
                cases.append({
                    "name": name, "class_name": child.get("classname", ""),
                    "suite": list(suites), "status": outcome,
                    "duration_seconds": _decimal_text(_duration(child.get("time", "0"))),
                    "source": source,
                })

    walk(root, ())
    return {"source": source, "summary": _summary(cases), "cases": cases}


def combine_reports(reports: list[dict]) -> dict:
    """Combine parse_report results in caller order, retaining duplicate cases.

    This function accepts this module's parsed report dictionaries, not arbitrary
    external JSON. It copies case records so the result owns its mutable lists.
    """
    if not isinstance(reports, (list, tuple)):
        _bad()
    sources: list[str] = []
    cases: list[dict] = []
    try:
        for report in reports:
            source = report["source"]
            if not isinstance(source, str) or not isinstance(report["cases"], list):
                _bad()
            sources.append(source)
            for case in report["cases"]:
                if len(cases) >= MAX_CASES:
                    _bad()
                if not all(isinstance(case[k], str) for k in ("name", "class_name", "source", "duration_seconds")):
                    _bad()
                if not case["name"] or case["status"] not in {"passed", "failure", "error", "skipped"}:
                    _bad()
                if not isinstance(case["suite"], list) or not all(isinstance(s, str) for s in case["suite"]):
                    _bad()
                cases.append({k: list(case[k]) if k == "suite" else case[k] for k in ("name", "class_name", "suite", "status", "duration_seconds", "source")})
        return {"sources": sources, "summary": _summary(cases), "cases": cases}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ReportError("Invalid JUnit report.") from exc


def _markdown_cell(value: str) -> str:
    # Neutralize HTML, table delimiters, inline syntax and hard line breaks.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()!|#~:.@])", r"\\\1", value)


def format_markdown(report: dict) -> str:
    """Render a compact, escaped Markdown summary and ordered case table."""
    summary = report["summary"]
    lines = ["# JUnit report summary", "", ", ".join(f"{key}: {summary[key]}" for key in _FIELDS)
             + f"; duration: {summary['duration_seconds']} s", "",
             "| Source | Suite | Class | Test | Outcome | Seconds |",
             "| --- | --- | --- | --- | --- | ---: |"]
    for case in report["cases"]:
        cells = (case["source"], " / ".join(case["suite"]), case["class_name"], case["name"], case["status"], case["duration_seconds"])
        lines.append("| " + " | ".join(_markdown_cell(x) for x in cells) + " |")
    return "\n".join(lines) + "\n"


def _read(path: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            _bad()
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            data = file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            _bad()
        return data
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize explicit local UTF-8 JUnit XML files offline.")
    parser.add_argument("files", nargs="+", metavar="FILE")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--fail-on-problems", action="store_true", help="exit 1 if cases contain failures or errors")
    args = parser.parse_args(argv)
    try:
        parsed = []
        total_cases = 0
        for path in args.files:
            item = parse_report(_read(path), source=path)
            total_cases += len(item["cases"])
            if total_cases > MAX_CASES:
                _bad()
            parsed.append(item)
        report = combine_reports(parsed)
        output = format_markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    except (ReportError, OSError):
        print("Unable to summarize JUnit report inputs.", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(output)
    except (BrokenPipeError, UnicodeError):
        return 2
    return 1 if args.fail_on_problems and (report["summary"]["failures"] or report["summary"]["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
