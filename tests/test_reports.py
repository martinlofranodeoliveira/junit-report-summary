import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import junit_report_summary as j


class Reports(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(j.parse_report(b"<testsuite/>")["summary"], dict(tests=0, passed=0, failures=0, errors=0, skipped=0, duration_seconds="0"))

    def test_actual_counts_ignore_declared(self):
        r = j.parse_report(b'<testsuite tests="500" failures="20" time="500"><testcase name="ok" time="0.10"/><testcase name="fail" time="0.20"><failure>ignored</failure></testcase></testsuite>')
        self.assertEqual(r["summary"]["tests"], 2)
        self.assertEqual(r["summary"]["duration_seconds"], "0.3")
        self.assertEqual(r["summary"]["failures"], 1)
        self.assertNotIn("ignored", json.dumps(r))

    def test_nested_and_namespace(self):
        r = j.parse_report(b'<x:testsuites xmlns:x="urn:j"><x:testsuite name="a"><x:testsuite name="b"><x:testcase name="n" classname="c"/></x:testsuite></x:testsuite></x:testsuites>')
        self.assertEqual(r["cases"][0]["suite"], ["a", "b"])
        self.assertEqual(r["cases"][0]["class_name"], "c")

    def test_extension_opaque(self):
        r = j.parse_report(b'<testsuite><extra><testsuite><testcase name="fake"/></testsuite></extra><testcase name="real"><system-out>&lt;testcase/&gt;</system-out></testcase></testsuite>')
        self.assertEqual([c["name"] for c in r["cases"]], ["real"])

    def test_outcome_precedence(self):
        cases = b'<testcase name="e"><skipped/><failure/><error/></testcase><testcase name="f"><failure/><skipped/></testcase><testcase name="s"><skipped/></testcase><testcase name="p"/>'
        r = j.parse_report(b"<testsuite>" + cases + b"</testsuite>")
        self.assertEqual([c["status"] for c in r["cases"]], ["error", "failure", "skipped", "passed"])

    def test_duplicate_cases_retained_and_results_detached(self):
        a = j.parse_report(b'<testsuite name="a"><testcase name="same"/></testsuite>', "first")
        r = j.combine_reports([a, a])
        self.assertEqual(r["sources"], ["first", "first"])
        self.assertEqual(r["summary"]["tests"], 2)
        r["cases"][0]["suite"].append("new")
        self.assertEqual(a["cases"][0]["suite"], ["a"])
        self.assertEqual(r["cases"][1]["suite"], ["a"])

    def test_decimal_not_float(self):
        r = j.parse_report(b'<testsuite><testcase name="a" time="1e-3"/><testcase name="b" time=".0020"/></testsuite>')
        self.assertEqual(r["summary"]["duration_seconds"], "0.003")

    def test_decimal_caller_context_cannot_change_result(self):
        import decimal
        for trapping in (True, False):
            with decimal.localcontext() as caller:
                caller.prec = 2
                caller.Emax = 2
                caller.traps[decimal.Overflow] = trapping
                r = j.parse_report(b'<testsuite><testcase name="x" time="1000"/><testcase name="y" time="0.01"/></testsuite>')
                self.assertEqual(r["summary"]["duration_seconds"], "1000.01")

    def test_reject_bad_duration(self):
        for text in ("NaN", "Infinity", "-1", "-0", "+1", " 1", "1 ", "", "1e999999", "1e-999999", "0x12"):
            with self.subTest(text=text), self.assertRaises(j.ReportError):
                j.parse_report(f'<testsuite><testcase name="x" time="{text}"/></testsuite>'.encode())

    def test_exact_long_sum(self):
        text = "9" * 120
        r = j.parse_report(f'<testsuite><testcase name="a" time="{text}"/><testcase name="b" time="1"/></testsuite>'.encode())
        self.assertEqual(r["summary"]["duration_seconds"], "1" + "0" * 120)

    def test_xml_utf8_bom_and_declaration(self):
        r = j.parse_report(b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><testsuite><testcase name="caf\xc3\xa9"/></testsuite>')
        self.assertEqual(r["cases"][0]["name"], "café")

    def test_declaration_looking_diagnostic_text_is_ignored(self):
        for payload in (b'<!-- <?xml version="1.0" encoding="UTF-16"?> -->', b'<system-out><![CDATA[<?xml version="1.0" encoding="UTF-16"?>]]></system-out>'):
            r = j.parse_report(b'<testsuite><testcase name="ok"/>' + payload + b'</testsuite>')
            self.assertEqual(r["summary"]["passed"], 1)

    def test_reject_unsafe_or_invalid_xml(self):
        inputs = [b'<testsuite>\xff</testsuite>', b'<testsuite>', b'<other/>', b'<!DOCTYPE testsuite SYSTEM "file:///etc/passwd"><testsuite/>', b'<testsuite><!-- <!ENTITY --> </testsuite>', b'<?xml version="1.0" encoding="UTF-16"?><testsuite/>', b'<testsuite><testcase/></testsuite>', b'<testsuite><testcase name=""/></testsuite>']
        for data in inputs:
            with self.subTest(data=data), self.assertRaises(j.ReportError):
                j.parse_report(data)

    def test_depth_limit(self):
        for n in (32, 33):
            data = b'<testsuites>' * n + b'</testsuites>' * n
            if n == 32:
                self.assertEqual(j.parse_report(data)["cases"], [])
            else:
                self.assertRaises(j.ReportError, j.parse_report, data)

    def test_resource_limits_exact(self):
        data = b'<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'
        with patch.object(j, "MAX_CASES", 1):
            self.assertRaises(j.ReportError, j.parse_report, data)
        with patch.object(j, "MAX_ELEMENTS", 2):
            self.assertRaises(j.ReportError, j.parse_report, data)
        with patch.object(j, "MAX_BYTES", len(data) - 1):
            self.assertRaises(j.ReportError, j.parse_report, data)
        with patch.object(j, "MAX_BYTES", len(data)):
            self.assertEqual(j.parse_report(data)["summary"]["tests"], 2)

    def test_input_types_and_combination_validation(self):
        for data in ("<testsuite/>", None, 3):
            self.assertRaises(j.ReportError, j.parse_report, data)
        for reports in (None, [{}], [{"source": "x", "cases": [{"name": "x"}]}]):
            self.assertRaises(j.ReportError, j.combine_reports, reports)

    def test_markdown_escapes_inline_content(self):
        r = j.parse_report(b'<testsuite><testcase name="&lt;b&gt;|[x](http://invalid)&#10;`x`"/></testsuite>')
        text = j.format_markdown(r)
        self.assertIn("&lt;b&gt;", text)
        self.assertIn("\\|", text)
        self.assertIn("\\[x\\]\\(http\\://invalid\\)", text)
        self.assertNotIn("<b>", text)
        self.assertNotIn("[x](http://invalid)", text)

    def test_markdown_does_not_emit_bare_autolink_targets(self):
        r = j.parse_report(b'<testsuite><testcase name="https://example.test/path user@example.test www.example.test"/></testsuite>')
        text = j.format_markdown(r)
        self.assertIn(r'https\://example\.test/path', text)
        self.assertIn(r'user\@example\.test', text)
        self.assertNotIn('www.example.test', text)


class CLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "junit_report_summary", *args], capture_output=True, text=True)

    def test_help(self):
        self.assertEqual(self.run_cli("--help").returncode, 0)

    def test_problem_exit_and_json_merge(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.xml", Path(d) / "b.xml"
            content = b'<testsuite><testcase name="failed"><failure>hidden</failure></testcase></testsuite>'
            a.write_bytes(content)
            b.write_bytes(b'<testsuite><testcase name="ok"/></testsuite>')
            q = self.run_cli(str(a), str(b))
            self.assertEqual(q.returncode, 0, q.stderr)
            self.assertEqual(json.loads(q.stdout)["summary"]["tests"], 2)
            self.assertEqual(self.run_cli(str(a), "--fail-on-problems").returncode, 1)
            self.assertEqual(a.read_bytes(), content)
            self.assertNotIn("hidden", q.stdout)

    def test_skips_do_not_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "skip.xml"
            p.write_text('<testsuite><testcase name="skip"><skipped/></testcase></testsuite>')
            self.assertEqual(self.run_cli(str(p), "--fail-on-problems").returncode, 0)

    def test_invalid_input_has_no_partial_output(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.xml", Path(d) / "b.xml"
            a.write_text('<testsuite/>')
            b.write_text('<invalid>')
            for paths in ((str(a), str(b)), (str(a), "missing-file"), (d,)):
                q = self.run_cli(*paths)
                self.assertEqual(q.returncode, 2)
                self.assertEqual(q.stdout, "")
                self.assertNotIn("Traceback", q.stderr)

    @unittest.skipUnless(hasattr(__import__("os"), "mkfifo"), "requires POSIX FIFOs")
    def test_fifo_rejected_without_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fifo"
            os.mkfifo(p)
            q = subprocess.run([sys.executable, "-m", "junit_report_summary", str(p)], capture_output=True, timeout=3)
            self.assertEqual(q.returncode, 2)
            self.assertEqual(q.stdout, b"")


if __name__ == "__main__":
    unittest.main()
