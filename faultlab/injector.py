"""Build isolated, faulty copies of MiniIssueTracker and evaluate repairs with hidden tests.

The agent only ever sees the workspace produced by `build_workspace`: the faulty source, the public test
suite and one reproduction test. Hidden checks, the reference solution and the expected outcome stay here.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .catalog import CATEGORIES, CATEGORY_BY_NAME, default_case, variation

ROOT = Path(__file__).resolve().parents[1]
PRISTINE = ROOT / "miniissuetracker"
CHECKS = Path(__file__).resolve().parent / "checks"
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.db", "*.pyc", "attachments", ".git")
GIT_ENV = {"GIT_AUTHOR_NAME": "faultlab", "GIT_AUTHOR_EMAIL": "faultlab@localhost",
           "GIT_COMMITTER_NAME": "faultlab", "GIT_COMMITTER_EMAIL": "faultlab@localhost",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


class FaultApplicationError(RuntimeError):
    pass


def apply_fault(repo_dir, fault):
    for rel, old, new in fault.edits:
        path = Path(repo_dir) / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise FaultApplicationError(f"{fault.id}: expected 1 match in {rel}, found {count}")
        path.write_text(text.replace(old, new))


def _module_source(module):
    return (CHECKS / f"{module}.py").read_text()


def render_visible_test(category, fault, case):
    """Ship one check function plus the helpers/imports it needs, bound to this episode's case."""
    source = _module_source(category.module)
    tree = ast.parse(source)
    parts = ["import pytest"]
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            segment = ast.get_source_segment(source, node)
            if segment != "import pytest":
                parts.append(segment)
    parts.append("")
    parts.append(f"CASE = {case!r}")
    parts.append("")
    parts.append("\n@pytest.fixture\ndef case():\n    return dict(CASE)\n")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (node.name.startswith("_") or node.name == fault.visible_test):
            parts.append("\n" + ast.get_source_segment(source, node) + "\n")
    header = f'"""Reproduction test for the reported issue ({category.description.lower()})."""\n'
    return header + "\n".join(parts).rstrip() + "\n"


def visible_test_path(category):
    return f"tests/test_issue_{category.module}.py"


STYLES = ("bug_report", "support_ticket", "qa_note", "ci_failure")


def issue_report(category, fault, case, v):
    style = STYLES[(v // len(category.faults)) % len(STYLES)]
    test_file = visible_test_path(category)
    test_id = f"{test_file}::{fault.visible_test}"
    if style == "bug_report":
        return (f"## Bug: {fault.title}\n\n"
                f"Expected: {fault.expected}.\nActual: {fault.actual}.\n\n"
                f"A failing reproduction test was added: `{test_id}`.\n"
                f"Please fix the application code (not the tests).")
    if style == "support_ticket":
        return (f"Customer ticket: \"{fault.title}.\" Our API contract says {fault.expected}, "
                f"but in production {fault.actual}.\n\nEngineering added `{test_file}` which reproduces it "
                f"(`{fault.visible_test}`). Find the root cause in the tracker package and fix it.")
    if style == "qa_note":
        return (f"QA regression found in area: {category.description}.\n"
                f"- Symptom: {fault.title}\n- Expected: {fault.expected}\n- Observed: {fault.actual}\n"
                f"- Repro: python -m pytest {test_id}\n"
                f"Fix the implementation so the repro and the existing suite pass.")
    return (f"CI is red on main. Failing test: {test_id}\n"
            f"Summary: {fault.title}. Expected behaviour: {fault.expected}.\n"
            f"Do not edit tests; patch the source under tracker/.")


def episode_spec(category_name, v):
    category, fault, case = variation(category_name, v)
    return {
        "bug_category": category.name,
        "bug_variation": v,
        "fault_id": fault.id,
        "check_module": category.module,
        "visible_test": f"{visible_test_path(category)}::{fault.visible_test}",
        "issue": issue_report(category, fault, case, v),
        "case": case,
    }


def _git(repo_dir, *args):
    env = dict(os.environ, **GIT_ENV)
    subprocess.run(["git", *args], cwd=repo_dir, env=env, check=True, capture_output=True)


def build_workspace(category_name, v, dest):
    """Create an isolated faulty repository at `dest` (must not exist). Returns the episode spec."""
    category, fault, case = variation(category_name, v)
    dest = Path(dest)
    shutil.copytree(PRISTINE, dest, ignore=IGNORE)
    apply_fault(dest, fault)
    (dest / visible_test_path(category)).write_text(render_visible_test(category, fault, case))
    (dest / "ISSUE.md").write_text(issue_report(category, fault, case, v) + "\n")
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "Snapshot with reported issue")
    return episode_spec(category_name, v)


HIDDEN_CONFTEST = '''import json
import os

import pytest

CASES = json.load(open(os.path.join(os.path.dirname(__file__), "cases.json")))


@pytest.fixture
def case(request):
    return dict(CASES[request.module.__name__.rsplit(".", 1)[-1].replace("test_hidden_", "")])
'''


def _parse_junit(path):
    results = {}
    root = ET.parse(path).getroot()
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname')}::{tc.get('name')}"
        failed = any(child.tag in ("failure", "error") for child in tc)
        skipped = any(child.tag == "skipped" for child in tc)
        results[name] = "skipped" if skipped else ("failed" if failed else "passed")
    return results


def evaluate(workspace, category_name, v, timeout=180):
    """Score a repaired workspace. Uses only the agent's tracker/ source; tests come from pristine copies."""
    category, fault, case = variation(category_name, v)
    with tempfile.TemporaryDirectory(prefix="faultlab-eval-") as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(PRISTINE, root, ignore=IGNORE)
        shutil.rmtree(root / "tracker")
        shutil.copytree(Path(workspace) / "tracker", root / "tracker", ignore=IGNORE)
        (root / visible_test_path(category)).write_text(render_visible_test(category, fault, case))
        hidden = root / "tests" / "hidden"
        hidden.mkdir()
        cases = {}
        for cat in CATEGORIES:
            shutil.copy(CHECKS / f"{cat.module}.py", hidden / f"test_hidden_{cat.module}.py")
            cases[cat.module] = case if cat.name == category_name else default_case(cat.name)
        (hidden / "cases.json").write_text(json.dumps(cases))
        (hidden / "conftest.py").write_text(HIDDEN_CONFTEST)
        junit = Path(tmp) / "junit.xml"
        try:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   f"--junitxml={junit}", "tests"], cwd=root, capture_output=True, text=True,
                                  timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            proc = None
        results = _parse_junit(junit) if junit.exists() else {}
    visible_key = f"tests.test_issue_{category.module}::{fault.visible_test}"
    hidden_bug = {k: s for k, s in results.items() if k.startswith(f"tests.hidden.test_hidden_{category.module}::")}
    regression = {k: s for k, s in results.items() if k not in hidden_bug and k != visible_key
                  and not k.startswith("tests.test_issue_")}
    hidden_all = {**hidden_bug, **{k: s for k, s in regression.items() if k.startswith("tests.hidden.")}}
    visible_pass = results.get(visible_key) == "passed"
    bug_pass = bool(hidden_bug) and all(s == "passed" for s in hidden_bug.values())
    regression_pass = bool(regression) and all(s == "passed" for s in regression.values())
    return {
        "timed_out": timed_out,
        "collected": len(results),
        "visible_test_passed": visible_pass,
        "hidden_bug_tests_total": len(hidden_bug),
        "hidden_bug_tests_passed": sum(s == "passed" for s in hidden_bug.values()),
        "hidden_tests_total": len(hidden_all),
        "hidden_tests_passed": sum(s == "passed" for s in hidden_all.values()),
        "regression_tests_total": len(regression),
        "regression_tests_passed": sum(s == "passed" for s in regression.values()),
        "task_success": visible_pass and bug_pass,
        "regression_free": visible_pass and bug_pass and regression_pass,
        "failed_tests": sorted(k for k, s in results.items() if s == "failed")[:50],
        "pytest_returncode": None if proc is None else proc.returncode,
    }


def all_episode_keys():
    from .catalog import VARIATIONS_PER_CATEGORY
    return [(c.name, v) for c in CATEGORIES for v in range(VARIATIONS_PER_CATEGORY)]


def category(name):
    return CATEGORY_BY_NAME[name]
