"""Repository tools. All paths are confined to the episode workspace."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MAX_OUTPUT = 2400
READ_MAX_LINES = 80
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "attachments"}


class ToolError(Exception):
    pass


def _clip(text, limit=MAX_OUTPUT):
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    return head + f"\n... [{len(text) - limit + 200} more characters truncated]"


class RepoTools:
    def __init__(self, workspace, test_timeout=90):
        self.root = Path(workspace).resolve()
        self.test_timeout = test_timeout
        self.last_test_output = ""
        self.last_test_target = None
        self.last_test_passed = None

    # -- helpers ----------------------------------------------------------
    def _resolve(self, path):
        path = (path or ".").strip() or "."
        full = (self.root / path).resolve()
        if full != self.root and self.root not in full.parents:
            raise ToolError(f"path {path!r} is outside the repository")
        return full

    def _rel(self, full):
        return str(full.relative_to(self.root)) if full != self.root else "."

    # -- tools ------------------------------------------------------------
    def list_files(self, path="."):
        base = self._resolve(path)
        if not base.exists():
            raise ToolError(f"{path} does not exist")
        if base.is_file():
            return self._rel(base)
        files = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith((".pyc", ".db")):
                    continue
                files.append(self._rel(Path(dirpath) / name))
        return "\n".join(files) or "(empty)"

    def read_file(self, path, start_line=1, end_line=None):
        full = self._resolve(path)
        if not full.is_file():
            raise ToolError(f"{path} is not a file")
        lines = full.read_text().splitlines()
        start = max(int(start_line or 1), 1)
        end = int(end_line or start + READ_MAX_LINES - 1)
        end = min(end, start + READ_MAX_LINES - 1, len(lines))
        if start > len(lines):
            raise ToolError(f"{path} has only {len(lines)} lines")
        body = "\n".join(f"{i:4d} | {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n({len(lines)} lines total)" if end < len(lines) or start > 1 else ""
        return _clip(f"{self._rel(full)} lines {start}-{end}:\n{body}{more}", 6000)

    def search_code(self, pattern, path="."):
        base = self._resolve(path)
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        targets = [base] if base.is_file() else sorted(base.rglob("*.py"))
        hits = []
        for file in targets:
            if any(part in SKIP_DIRS for part in file.parts):
                continue
            for i, line in enumerate(file.read_text().splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{self._rel(file)}:{i}: {line.strip()}")
                    if len(hits) >= 40:
                        return "\n".join(hits) + "\n... (more matches truncated)"
        if hits:
            return "\n".join(hits)
        if base != self.root:
            elsewhere = self.search_code(pattern, ".")
            if not elsewhere.startswith("no matches"):
                return f"no matches in {self._rel(base)}; matches elsewhere in the repository:\n{elsewhere}"
        return f"no matches for {pattern!r} anywhere in the repository; try a shorter or different pattern"

    def run_tests(self, target=""):
        args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "--no-header", "-rf"]
        target = (target or "").strip()
        if target:
            file_part = target.split("::", 1)[0]
            if not (self.root / file_part).exists():
                raise ToolError(f"test target {file_part} does not exist")
            args.append(target)
        try:
            proc = subprocess.run(args, cwd=self.root, capture_output=True, text=True, timeout=self.test_timeout)
            output = proc.stdout + proc.stderr
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            output, passed = f"pytest timed out after {self.test_timeout}s", False
        self.last_test_output = output
        self.last_test_target = target
        self.last_test_passed = passed
        return self._summarize(output, passed)

    @staticmethod
    def _summarize(output, passed):
        lines = output.strip().splitlines()
        summary = lines[-1] if lines else "(no output)"
        if passed:
            return f"PASSED: {summary}"
        fails = [l for l in lines if l.startswith(("FAILED", "ERROR"))]
        detail = []
        capture = False
        for line in lines:
            if line.startswith("_____") and "test" in line:
                capture = True
            if line.startswith(("=====", "FAILED", "ERROR")) and "short test summary" in line:
                capture = False
            if capture:
                detail.append(line)
        text = "FAILED: " + summary + "\n" + "\n".join(fails[:15]) + "\n\nDetails:\n" + "\n".join(detail)
        return _clip(text)

    def get_test_results(self, test=""):
        if not self.last_test_output:
            raise ToolError("no tests have been run yet")
        out = self.last_test_output
        if test:
            name = test.split("::")[-1]
            blocks = re.split(r"\n(?=_{3,} )", out)
            chosen = [b for b in blocks if name in b.splitlines()[0]] if blocks else []
            if chosen:
                out = "\n".join(chosen)
        return _clip(out, 4000)

    def apply_patch(self, path, start_line, end_line, new_text):
        """Replace lines start_line..end_line (inclusive, 1-based, as shown by read_file) with new_text."""
        full = self._resolve(path)
        rel = self._rel(full)
        if rel.startswith("tests/") or rel == "tests":
            raise ToolError("editing tests is not allowed; fix the application code under tracker/")
        if not full.is_file():
            raise ToolError(f"{path} is not a file")
        text = full.read_text()
        lines = text.splitlines()
        try:
            start, end = int(start_line), int(end_line)
        except (TypeError, ValueError) as exc:
            raise ToolError("start_line and end_line must be integers") from exc
        if start < 1 or end < start or end > len(lines):
            raise ToolError(f"invalid line range {start}-{end}; {rel} has {len(lines)} lines")
        if end - start + 1 > 40:
            raise ToolError("replace at most 40 lines at a time")
        new_lines = (new_text or "").rstrip("\n").splitlines()
        # keep the original indentation if the model dropped it on the first line
        orig_indent = re.match(r"\s*", lines[start - 1]).group(0)
        if new_lines and orig_indent and not new_lines[0].startswith((" ", "\t")):
            given = re.match(r"\s*", new_lines[0]).group(0)
            new_lines = [orig_indent + l[len(given):] if l.startswith(given) else l for l in new_lines]
        old_block = lines[start - 1:end]
        lines[start - 1:end] = new_lines
        full.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
        lo, hi = max(1, start - 2), min(len(lines), start + len(new_lines) + 1)
        view = "\n".join(f"{i:4d} | {lines[i - 1]}" for i in range(lo, hi + 1))
        compiled = ""
        if full.suffix == ".py":
            try:
                compile("\n".join(lines), rel, "exec")
            except SyntaxError as exc:
                compiled = f"\nWARNING: the file now has a syntax error at line {exc.lineno}: {exc.msg}"
        removed = "\n".join(f"  - {l}" for l in old_block[:12])
        return (f"patched {rel}: replaced lines {start}-{end} with {len(new_lines)} line(s).\n"
                f"Removed lines:\n{removed}\nUpdated region now reads:\n{view}{compiled}")

    def git_diff(self):
        proc = subprocess.run(["git", "diff", "--no-color"], cwd=self.root, capture_output=True, text=True, timeout=30)
        return _clip(proc.stdout.strip() or "(no changes)")

    def diff_full(self):
        proc = subprocess.run(["git", "diff", "--no-color"], cwd=self.root, capture_output=True, text=True, timeout=30)
        return proc.stdout

    def execute(self, tool, args):
        """Run a tool; returns (ok, text, seconds)."""
        t0 = time.perf_counter()
        try:
            if tool == "list_files":
                out = self.list_files(args.get("path", "."))
            elif tool == "read_file":
                out = self.read_file(args.get("path", ""), args.get("start_line", 1), args.get("end_line"))
            elif tool == "search_code":
                out = self.search_code(args.get("pattern", ""), args.get("path", "."))
            elif tool == "run_tests":
                out = self.run_tests(args.get("target", ""))
            elif tool == "get_test_results":
                out = self.get_test_results(args.get("test", ""))
            elif tool == "apply_patch":
                out = self.apply_patch(args.get("path", ""), args.get("start_line"), args.get("end_line"),
                                       args.get("new_text", ""))
            elif tool == "git_diff":
                out = self.git_diff()
            else:
                raise ToolError(f"unknown tool {tool}")
            return True, out, time.perf_counter() - t0
        except ToolError as exc:
            return False, f"ERROR: {exc}", time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001 - tool crashes are reported to the model
            return False, f"ERROR: {type(exc).__name__}: {exc}", time.perf_counter() - t0
