"""Synthetic observed-history regressions, separate from legacy report tests."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import junit_report_summary as j


def parsed(xml, source="report.xml"):
    return j.parse_report(xml.encode("utf-8"), source=source)


def run(run_id, xml, source="report.xml"):
    return {"id": run_id, "report": parsed(xml, source)}


class History(unittest.TestCase):
    def test_classifications_counts_observation_order_and_absences(self):
        first = '''<testsuite name="suite">
          <testcase classname="C" name="mixed[x]"/>
          <testcase name="problem"><error/></testcase>
          <testcase name="passing"/>
          <testcase name="skipping"><skipped/></testcase>
        </testsuite>'''
        second = '''<testsuite name="suite">
          <testcase name="skipping"><skipped/></testcase>
          <testcase name="problem"><failure/></testcase>
          <testcase classname="C" name="mixed[x]"><failure/></testcase>
          <testcase name="passing"><skipped/></testcase>
          <testcase name="new"/>
        </testsuite>'''
        third = '''<testsuite name="suite">
          <testcase name="problem"><skipped/></testcase>
          <testcase classname="C" name="mixed[x]"><error/></testcase>
        </testsuite>'''
        result = j.analyze_history([
            run("later-label", first), run("earlier-label", second),
            run("empty", "<testsuite/>"), run("third", third),
        ])
        self.assertEqual(result["runs"], ["later-label", "earlier-label", "empty", "third"])
        self.assertEqual(result["summary"], {"tests": 5, "mixed": 1, "problem_only": 1,
                                             "pass_only": 2, "skipped_only": 1})
        self.assertEqual([item["identity"]["name"] for item in result["tests"]],
                         ["mixed[x]", "problem", "passing", "skipping", "new"])
        mixed, problem, passing, skipping, new = result["tests"]
        self.assertEqual(mixed, {
            "identity": {"suite": ["suite"], "class_name": "C", "name": "mixed[x]"},
            "classification": "mixed", "counts": {"passed": 1, "failure": 1, "error": 1, "skipped": 0},
            "observations": [{"run": "later-label", "status": "passed"},
                             {"run": "earlier-label", "status": "failure"},
                             {"run": "third", "status": "error"}],
            "missing_runs": ["empty"],
        })
        self.assertEqual(problem["classification"], "problem_only")
        self.assertEqual(problem["counts"], {"passed": 0, "failure": 1, "error": 1, "skipped": 1})
        self.assertEqual(passing["classification"], "pass_only")
        self.assertEqual(passing["counts"], {"passed": 1, "failure": 0, "error": 0, "skipped": 1})
        self.assertEqual(skipping["classification"], "skipped_only")
        self.assertEqual(skipping["missing_runs"], ["empty", "third"])
        self.assertEqual(new["missing_runs"], ["later-label", "empty", "third"])

    def test_exact_identity_has_no_separator_collisions_or_parameter_merging(self):
        xml = '''<testsuites>
          <testsuite name="a / b"><testcase classname="C" name="test[1]"/></testsuite>
          <testsuite name="a"><testsuite name="b"><testcase classname="C" name="test[1]"/></testsuite></testsuite>
          <testsuite name="a / b"><testcase classname="C" name="test[2]"/>
            <testcase classname="D" name="test[1]"/><testcase classname="C" name="Test[1]"/>
          </testsuite>
          <testsuite><testcase name="test[1]"/></testsuite>
        </testsuites>'''
        history = j.analyze_history([run("one", xml), run("two", xml)])
        self.assertEqual(history["summary"]["tests"], 6)
        self.assertEqual(history["tests"][0]["identity"]["suite"], ["a / b"])
        self.assertEqual(history["tests"][1]["identity"]["suite"], ["a", "b"])
        self.assertTrue(all(item["counts"]["passed"] == 2 for item in history["tests"]))

    def test_source_renaming_is_not_a_new_identity(self):
        first = run("one", '<testsuite><testcase name="same"/></testsuite>', "old-path")
        second = run("two", '<testsuite><testcase name="same"><failure/></testcase></testsuite>', "renamed-path")
        history = j.analyze_history([first, second])
        self.assertEqual(history["summary"]["tests"], 1)
        self.assertEqual(history["tests"][0]["classification"], "mixed")
        self.assertNotIn("old-path", json.dumps(history))
        self.assertNotIn("renamed-path", json.dumps(history))

    def test_duplicate_identity_within_run_is_ambiguous(self):
        xml = '<testsuite><testcase name="same"/><testcase name="same"><failure/></testcase></testsuite>'
        report = parsed(xml)
        # Different per-record source labels still cannot disambiguate retries.
        report["cases"][1]["source"] = "another-label"
        with self.assertRaises(j.ReportError):
            j.analyze_history([{"id": "one", "report": report}])
        self.assertEqual(j.combine_reports([report])["summary"]["tests"], 2)

    def test_result_and_input_mutations_do_not_alias(self):
        runs = [run("one", '<testsuite name="s"><testcase name="x"/></testsuite>'),
                run("two", "<testsuite/>")]
        saved = copy.deepcopy(runs)
        result = j.analyze_history(runs)
        self.assertEqual(runs, saved)
        result["runs"].append("extra")
        result["tests"][0]["identity"]["suite"].append("changed")
        result["tests"][0]["observations"][0]["status"] = "error"
        result["tests"][0]["missing_runs"].clear()
        self.assertEqual(runs, saved)
        independent = j.analyze_history(runs)
        runs[0]["report"]["cases"][0]["suite"].append("mutated-input")
        runs[0]["id"] = "changed-input"
        self.assertEqual(independent["runs"], ["one", "two"])
        self.assertEqual(independent["tests"][0]["identity"]["suite"], ["s"])

    def test_advisory_summaries_are_never_used(self):
        a = run("one", '<testsuite tests="999"><testcase name="x"/></testsuite>')
        a["report"]["summary"] = {"tests": "untrusted", "failures": 999}
        b = run("two", '<testsuite><testcase name="x"><failure/></testcase></testsuite>')
        del b["report"]["summary"]
        result = j.analyze_history([a, b])
        self.assertEqual(result["summary"], {"tests": 1, "mixed": 1, "problem_only": 0,
                                             "pass_only": 0, "skipped_only": 0})

    def test_history_excludes_diagnostics_durations_and_extra_fields(self):
        record = run("one", '''<testsuite name="s" time="777">
          <testcase name="x" time="123.45"><error message="SECRET_MESSAGE">SECRET_TRACE</error>
            <system-out>SECRET_STDOUT</system-out><system-err>SECRET_STDERR</system-err>
            <properties><property name="SECRET_PROPERTY"/></properties>
          </testcase></testsuite>''', "PRIVATE_SOURCE")
        record["report"]["cases"][0]["diagnostics"] = ["SECRET_EXTRA"]
        record["report"]["diagnostics"] = ["SECRET_REPORT_EXTRA"]
        history = j.analyze_history([record])
        self.assertEqual(set(history), {"runs", "summary", "tests"})
        test = history["tests"][0]
        self.assertEqual(set(test), {"identity", "classification", "counts", "observations", "missing_runs"})
        self.assertEqual(set(test["identity"]), {"suite", "class_name", "name"})
        self.assertEqual(set(test["observations"][0]), {"run", "status"})
        for text in (json.dumps(history), j.format_history_markdown(history)):
            for absent in ("SECRET", "PRIVATE_SOURCE", "123.45", "duration_seconds", "777"):
                self.assertNotIn(absent, text)

    def test_empty_reports_tuple_and_run_count_boundaries(self):
        empty = parsed("<testsuite/>")
        expected = {"tests": 0, "mixed": 0, "problem_only": 0, "pass_only": 0, "skipped_only": 0}
        for count in (1, 100):
            with self.subTest(count=count):
                runs = tuple({"id": str(i), "report": empty} for i in range(count))
                history = j.analyze_history(runs)
                self.assertEqual(history, {"runs": [str(i) for i in range(count)], "summary": expected, "tests": []})
        for runs in ([], (), None, {}, "one", [{"id": str(i), "report": empty} for i in range(101)]):
            with self.subTest(runs_type=type(runs)), self.assertRaises(j.ReportError):
                j.analyze_history(runs)

    def test_exact_run_shape_and_unique_valid_ids(self):
        report = parsed("<testsuite/>")
        invalid = [None, [], {}, {"id": "one"}, {"report": report},
                   {"id": "one", "report": report, "extra": "ignored?"}]
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(j.ReportError):
                j.analyze_history([record])
        ids = [None, 1, [], "", "x" * 129] + ["a" + chr(i) + "b" for i in (*range(32), 127)]
        for run_id in ids:
            with self.subTest(run_id=run_id), self.assertRaises(j.ReportError):
                j.analyze_history([{"id": run_id, "report": report}])
        with self.assertRaises(j.ReportError):
            j.analyze_history([{"id": "same", "report": report}, {"id": "same", "report": report}])
        valid = "é" * 128
        self.assertEqual(j.analyze_history([{"id": valid, "report": report}])["runs"], [valid])

    def test_original_record_and_duration_validation_is_reused(self):
        valid = run("one", '<testsuite><testcase name="x" time="0.2"/></testsuite>')
        for key, value in (("name", ""), ("class_name", None), ("source", 123),
                           ("suite", "s"), ("suite", [None]), ("status", "missing"),
                           ("status", []), ("duration_seconds", "NaN"),
                           ("duration_seconds", "-1"), ("duration_seconds", "1e999999")):
            with self.subTest(key=key, value=value):
                record = copy.deepcopy(valid)
                record["report"]["cases"][0][key] = value
                with self.assertRaises(j.ReportError):
                    j.analyze_history([record])
        for report in (None, {}, {"source": None, "cases": []}, {"source": "x", "cases": ()},
                       {"source": "x", "cases": [{}]}):
            with self.subTest(report=report), self.assertRaises(j.ReportError):
                j.analyze_history([{"id": "one", "report": report}])

    def test_observation_limit_counts_all_runs_even_for_one_identity(self):
        runs = [run(str(i), '<testsuite><testcase name="same"/></testsuite>') for i in range(3)]
        with patch.object(j, "MAX_CASES", 2):
            self.assertEqual(j.analyze_history(runs[:2])["tests"][0]["counts"]["passed"], 2)
            with self.assertRaises(j.ReportError):
                j.analyze_history(runs)

    def test_markdown_escapes_every_identifier_and_missing_run(self):
        dangerous_run = '<r>|[open](https://example.test) user@example.test `x`'
        xml = '''<testsuite name="&lt;s&gt;|[s](http://example.test)">
          <testcase classname="&lt;c&gt;|`c`" name="&lt;t&gt;|[t](http://example.test)&#10;`t`"/>
        </testsuite>'''
        history = j.analyze_history([run("first", xml), run(dangerous_run, "<testsuite/>")])
        output = j.format_history_markdown(history)
        self.assertEqual(output, j.format_history_markdown(copy.deepcopy(history)))
        self.assertIn(r'&lt;r&gt;\|\[open\]\(https\://example\.test\)', output)
        self.assertIn(r'user\@example\.test \`x\`', output)
        self.assertIn(r'&lt;s&gt;\|\[s\]\(http\://example\.test\)', output)
        self.assertIn(r'&lt;c&gt;\|\`c\`', output)
        self.assertIn(r'&lt;t&gt;\|\[t\]\(http\://example\.test\) \`t\`', output)
        self.assertIn("Missing runs", output)
        self.assertIn(r'pass\_only', output)
        self.assertIn("| 1 | 0 | 0 | 0 |", output)
        for raw in ("<r>", "<s>", "<c>", "<t>", "[open](", "http://", "https://", "user@example.test"):
            self.assertNotIn(raw, output)


class HistoryCLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "junit_report_summary", *args],
                              capture_output=True, text=True, timeout=10)

    def assert_invalid(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Unable to summarize JUnit report inputs.\n")

    def test_separate_runs_exact_path_ids_ascii_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "café.xml", Path(directory) / "second.xml"
            first = '<testsuite name="s"><testcase name="café"/></testsuite>'.encode()
            second = '<testsuite name="s"><testcase name="café"><failure>PRIVATE_TRACE</failure></testcase></testsuite>'.encode()
            a.write_bytes(first)
            b.write_bytes(second)
            paths = [str(a.parent) + "/./" + a.name, str(b)]
            result = self.run_cli("--history", *paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            history = json.loads(result.stdout)
            self.assertEqual(history["runs"], paths)
            self.assertEqual(history["summary"]["mixed"], 1)
            self.assertTrue(result.stdout.isascii())
            self.assertNotIn("PRIVATE_TRACE", result.stdout)
            self.assertEqual(a.read_bytes(), first)
            self.assertEqual(b.read_bytes(), second)
            self.assertEqual(self.run_cli("--history", *paths, "--fail-on-problems").returncode, 1)

    def test_markdown_uses_history_formatter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.xml"
            path.write_text('<testsuite><testcase name="x"><error/></testcase></testsuite>')
            result = self.run_cli(str(path), "--history", "--format", "markdown", "--fail-on-problems")
            expected = j.analyze_history([{"id": str(path), "report": j.parse_report(path.read_bytes(), str(path))}])
            self.assertEqual(result.stdout, j.format_history_markdown(expected))
            self.assertEqual(result.returncode, 1)

    def test_skips_and_missing_tests_do_not_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "skips.xml", Path(directory) / "empty.xml"
            a.write_text('<testsuite><testcase name="skip"><skipped/></testcase></testsuite>')
            b.write_text("<testsuite/>")
            result = self.run_cli("--history", str(a), str(b), "--fail-on-problems")
            self.assertEqual(result.returncode, 0, result.stderr)
            test = json.loads(result.stdout)["tests"][0]
            self.assertEqual(test["classification"], "skipped_only")
            self.assertEqual(test["missing_runs"], [str(b)])
            a.write_text('<testsuite><testcase name="pass"/></testsuite>')
            self.assertEqual(self.run_cli("--history", str(a), str(b), "--fail-on-problems").returncode, 0)

    def test_duplicate_paths_reject_while_default_still_retains_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.xml"
            path.write_text('<testsuite><testcase name="x"/></testsuite>')
            self.assert_invalid(self.run_cli("--history", str(path), str(path)))
            old = self.run_cli(str(path), str(path))
            self.assertEqual(old.returncode, 0, old.stderr)
            self.assertEqual(json.loads(old.stdout)["summary"]["tests"], 2)

    def test_duplicate_identities_reject_without_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "valid.xml", Path(directory) / "duplicate.xml"
            a.write_text('<testsuite><testcase name="valid"/></testsuite>')
            b.write_text('<testsuite><testcase name="x"/><testcase name="x"><failure/></testcase></testsuite>')
            self.assert_invalid(self.run_cli("--history", str(a), str(b)))

    def test_later_invalid_xml_or_missing_file_has_no_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "valid.xml", Path(directory) / "invalid.xml"
            a.write_text('<testsuite><testcase name="valid"/></testsuite>')
            for xml in ("<invalid>", '<!DOCTYPE testsuite SYSTEM "file:///not-read"><testsuite/>'):
                b.write_text(xml)
                self.assert_invalid(self.run_cli("--history", str(a), str(b)))
            self.assert_invalid(self.run_cli("--history", str(a), str(Path(directory) / "missing")))

    def test_run_id_control_characters_and_length_are_rejected_generically(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("line\nbreak.xml", "x" * 129 + ".xml"):
                path = Path(directory) / name
                path.write_text("<testsuite/>")
                self.assert_invalid(self.run_cli("--history", str(path)))

    def test_one_hundred_runs_allowed_but_one_hundred_one_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index in range(101):
                path = Path(directory) / f"{index}.xml"
                path.write_text("<testsuite/>")
                paths.append(str(path))
            result = self.run_cli("--history", *paths[:100])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["runs"], paths[:100])
            self.assert_invalid(self.run_cli("--history", *paths))

    def test_help_remains_successful(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--history", result.stdout)


if __name__ == "__main__":
    unittest.main()
