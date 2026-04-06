#!/usr/bin/env python3
"""Eval runner for the handoff skill.

Creates temp repos, runs claude -p with eval prompts, grades outputs
with two-tier deterministic + LLM grading.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SKILL_DIR = PROJECT_ROOT / ".claude" / "skills" / "handoff"
EVALS_FILE = SCRIPT_DIR / "evals.json"


def check_prerequisites():
    """Verify claude CLI is available."""
    result = subprocess.run(
        ["claude", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERROR: claude CLI not found. Install it first.", file=sys.stderr)
        sys.exit(1)


def scaffold_repo(tmpdir: Path, scaffolding: list[dict]):
    """Initialize a git repo with scaffold files."""
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "eval@test"],
        cwd=tmpdir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "eval"],
        cwd=tmpdir, capture_output=True, check=True,
    )

    for item in scaffolding:
        filepath = tmpdir / item["path"]
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(item["content"])

    subprocess.run(
        ["git", "add", "."], cwd=tmpdir, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "scaffold"],
        cwd=tmpdir, capture_output=True, check=True,
    )


def install_skill(tmpdir: Path):
    """Symlink the handoff skill into the temp repo."""
    skill_dest = tmpdir / ".claude" / "skills" / "handoff"
    skill_dest.parent.mkdir(parents=True, exist_ok=True)
    skill_dest.symlink_to(SKILL_DIR)


def build_prompt(prompt: str) -> str:
    """Build the full eval prompt with inlined skill instructions.

    claude -p doesn't invoke slash commands or load skills from
    .claude/skills/, so we inline the SKILL.md body directly. We also
    adapt the framing for non-interactive mode:

    - The skill references "conversation context" but in claude -p the
      prompt IS the entire context. We make this explicit.
    - Step 2 (subagent dry-run) may not work in claude -p if the Agent
      tool is unavailable. We tell Claude to skip it rather than fail.
    - Step 1 (self-review) still works:Claude re-reads the prompt.
    """
    skill_file = SKILL_DIR / "SKILL.md"
    skill_content = skill_file.read_text()
    # Strip frontmatter (between --- delimiters)
    parts = skill_content.split("---", 2)
    if len(parts) >= 3:
        skill_body = parts[2].strip()
    else:
        skill_body = skill_content

    return (
        f"Follow these instructions for creating a handoff document.\n\n"
        f"IMPORTANT ADAPTATION: You are running in non-interactive mode "
        f"(claude -p). The prompt below IS your entire conversation context "
        f"and there is no prior conversation history. When the instructions say "
        f"'re-read your conversation context', re-read this prompt. "
        f"For the verification step that asks you to 'spawn a subagent', "
        f"skip it if the Agent tool is not available:perform a thorough "
        f"self-review instead. All other instructions apply as written.\n\n"
        f"{skill_body}\n\n"
        f"---\n\n"
        f"Here is the session context. Treat this as if you have been working "
        f"in this session and these are the decisions, progress, and state "
        f"you need to capture in the handoff document:\n\n"
        f"{prompt}"
    )


def run_skill(tmpdir: Path, prompt: str) -> tuple[bool, str, float]:
    """Run claude -p with the eval prompt. Returns (success, output, seconds)."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    full_prompt = build_prompt(prompt)

    start = time.monotonic()
    try:
        result = subprocess.run(
            [
                "claude", "-p", full_prompt,
                "--output-format", "json",
                "--allowedTools", "Write,Read,Edit,Bash,Glob,Grep,Agent",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return False, f"timed out after {elapsed:.0f}s", elapsed
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        return False, result.stderr or result.stdout, elapsed

    return True, result.stdout, elapsed


def grade_deterministic(tmpdir: Path, expectations: list[dict]) -> list[dict]:
    """Run deterministic grading (file checks, pattern grep). Returns results list."""
    results = []
    for exp in expectations:
        etype = exp["type"]
        desc = exp["description"]

        if etype == "file_exists":
            target = tmpdir / exp["path"]
            passed = target.is_file()
            evidence = "file exists" if passed else f"file not found: {exp['path']}"
            results.append({
                "description": desc,
                "passed": passed,
                "grading": "deterministic",
                "evidence": evidence,
            })

        elif etype == "content":
            target = tmpdir / exp["file"]
            if not target.is_file():
                results.append({
                    "description": desc,
                    "passed": False,
                    "grading": "deterministic",
                    "evidence": f"file not found: {exp['file']}",
                })
                continue

            content = target.read_text()
            missing = []
            for pattern in exp["patterns"]:
                if not re.search(pattern, content, re.IGNORECASE):
                    missing.append(pattern)

            passed = len(missing) == 0
            if passed:
                evidence = "all patterns matched"
            else:
                evidence = f"patterns not found: {', '.join(missing)}"

            results.append({
                "description": desc,
                "passed": passed,
                "grading": "deterministic",
                "evidence": evidence,
            })

        elif etype == "file_not_exists":
            target = tmpdir / exp["path"]
            passed = not target.exists()
            evidence = "file absent" if passed else f"file unexpectedly exists: {exp['path']}"
            results.append({
                "description": desc,
                "passed": passed,
                "grading": "deterministic",
                "evidence": evidence,
            })

    return results


def grade_llm(tmpdir: Path, expectations: list[dict]) -> dict:
    """Run LLM grading for content expectations marked with grading: llm.

    Returns a dict mapping expectation index (within the full expectations list)
    to {"passed": bool, "evidence": str}.
    """
    llm_items = []
    llm_indices = []
    for i, exp in enumerate(expectations):
        if exp.get("grading") == "llm":
            llm_items.append(exp)
            llm_indices.append(i)

    if not llm_items:
        return {}

    handoff_path = tmpdir / ".claude" / "handoff" / "state.md"
    if not handoff_path.is_file():
        return {i: {"passed": False, "evidence": "handoff file not found"} for i in llm_indices}

    doc_content = handoff_path.read_text()

    numbered = "\n".join(
        f"{j+1}. {item['description']}" for j, item in enumerate(llm_items)
    )
    judge_prompt = (
        "You are grading a handoff document for quality. Read the document below, "
        "then evaluate each expectation. Return ONLY a JSON array, no other text.\n\n"
        'Each element: {"index": <n>, "passed": <bool>, "evidence": "<brief reason>"}\n\n'
        "Indices are 1-based and correspond to the numbered expectations below.\n\n"
        f"Document:\n```\n{doc_content}\n```\n\n"
        f"Expectations to grade:\n{numbered}\n"
    )

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        result = subprocess.run(
            ["claude", "-p", judge_prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("  WARNING: LLM judge timed out, falling back to deterministic", file=sys.stderr)
        return {}

    if result.returncode != 0:
        print(f"  WARNING: LLM judge failed: {result.stderr[:200]}", file=sys.stderr)
        return {}

    try:
        outer = json.loads(result.stdout)
        response_text = outer.get("result", result.stdout) if isinstance(outer, dict) else result.stdout
        if isinstance(response_text, str):
            match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if match:
                grades = json.loads(match.group())
            else:
                grades = json.loads(response_text)
        else:
            grades = response_text
    except (json.JSONDecodeError, TypeError):
        print(f"  WARNING: LLM judge returned unparseable output, falling back to deterministic", file=sys.stderr)
        return {}

    llm_results = {}
    for grade in grades:
        one_based = grade.get("index", 0)
        if 1 <= one_based <= len(llm_indices):
            real_index = llm_indices[one_based - 1]
            llm_results[real_index] = {
                "passed": bool(grade.get("passed", False)),
                "evidence": grade.get("evidence", ""),
            }

    return llm_results


def merge_results(
    det_results: list[dict],
    llm_results: dict,
    expectations: list[dict],
) -> list[dict]:
    """Merge deterministic and LLM results. LLM overrides for grading:llm expectations."""
    merged = []
    for i, (det, exp) in enumerate(zip(det_results, expectations)):
        if i in llm_results:
            merged.append({
                "description": det["description"],
                "passed": llm_results[i]["passed"],
                "grading": "llm",
                "evidence": llm_results[i]["evidence"],
            })
        else:
            merged.append(det)
    return merged


def print_results(eval_name: str, results: list[dict], elapsed: float, mode: str):
    """Print results to stdout."""
    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    if mode == "human":
        print(f"\n=== Eval: {eval_name} ===")
        for r in results:
            tag = " [LLM]" if r["grading"] == "llm" else ""
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  {status}: {r['description']}{tag}")
        print("---")
        print(f"{eval_name}: {passed}/{total} passed ({elapsed:.0f}s)")
    else:
        for r in results:
            if not r["passed"]:
                tag = " [LLM]" if r["grading"] == "llm" else ""
                print(f"  FAIL: {eval_name}: {r['description']}{tag}")


def write_benchmark(output_dir: Path, all_runs: list[dict], timestamp: str):
    """Write benchmark.json."""
    total_passed = sum(r["passed"] for run in all_runs for r in run["results"])
    total_expectations = sum(len(run["results"]) for run in all_runs)
    mean_pass = total_passed / total_expectations if total_expectations else 0
    mean_time = (
        sum(run["time_seconds"] for run in all_runs) / len(all_runs)
        if all_runs else 0
    )

    benchmark = {
        "metadata": {
            "skill_name": "handoff",
            "timestamp": timestamp,
        },
        "runs": [
            {
                "eval_id": run["eval_id"],
                "eval_name": run["eval_name"],
                "pass_rate": (
                    sum(1 for r in run["results"] if r["passed"]) / len(run["results"])
                    if run["results"] else 0
                ),
                "passed": sum(1 for r in run["results"] if r["passed"]),
                "failed": sum(1 for r in run["results"] if not r["passed"]),
                "total": len(run["results"]),
                "time_seconds": round(run["time_seconds"], 1),
                "expectations": run["results"],
            }
            for run in all_runs
        ],
        "summary": {
            "pass_rate": {"mean": round(mean_pass, 2)},
            "time_seconds": {"mean": round(mean_time, 1)},
            "evals_run": len(all_runs),
        },
    }

    (output_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2) + "\n")


def write_dashboard(output_dir: Path, all_runs: list[dict], timestamp: str):
    """Write dashboard.md."""
    total_passed = sum(r["passed"] for run in all_runs for r in run["results"])
    total_expectations = sum(len(run["results"]) for run in all_runs)
    total_time = sum(run["time_seconds"] for run in all_runs)
    overall_rate = (total_passed / total_expectations * 100) if total_expectations else 0
    llm_evals = sum(
        1 for run in all_runs
        if any(r["grading"] == "llm" for r in run["results"])
    )

    minutes = int(total_time // 60)
    seconds = int(total_time % 60)
    time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

    lines = [
        f"# Eval Run: {timestamp}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Evals run | {len(all_runs)} |",
        f"| Overall pass rate | {overall_rate:.0f}% |",
        f"| Total time | {time_str} |",
        f"| LLM grading | {llm_evals}/{len(all_runs)} evals |",
        "",
        "## Results",
        "",
    ]

    for run in all_runs:
        passed = sum(1 for r in run["results"] if r["passed"])
        total = len(run["results"])
        lines.append(
            f"### {run['eval_id']}. {run['eval_name']} "
            f"({passed}/{total} passed, {run['time_seconds']:.0f}s)"
        )
        lines.append("")
        lines.append("| # | Expectation | Grade | Result |")
        lines.append("|---|-------------|-------|--------|")
        for i, r in enumerate(run["results"], 1):
            grade = "llm" if r["grading"] == "llm" else "det"
            result = "PASS" if r["passed"] else "FAIL"
            lines.append(f"| {i} | {r['description']} | {grade} | {result} |")
        lines.append("")

    (output_dir / "dashboard.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Run handoff skill evals")
    parser.add_argument("--mode", default="human", choices=["human", "llm"])
    args = parser.parse_args()

    check_prerequisites()

    evals_data = json.loads(EVALS_FILE.read_text())
    evals = evals_data["evals"]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    output_dir = PROJECT_ROOT / "handoff-workspace" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    all_runs = []
    any_failed = False

    for ev in evals:
        eval_name = ev["name"]
        if args.mode == "human":
            print(f"\nRunning eval: {eval_name}...")

        tmpdir = Path(tempfile.mkdtemp(prefix=f"handoff-eval-{eval_name}-"))
        try:
            scaffold_repo(tmpdir, ev["scaffolding"])
            install_skill(tmpdir)

            success, output, elapsed = run_skill(tmpdir, ev["prompt"])
            if not success:
                if args.mode == "human":
                    print(f"  ERROR: claude -p failed ({elapsed:.0f}s)")
                    print(f"  {output[:300]}")
                else:
                    print(f"  ERROR: {eval_name}: claude -p failed")
                all_runs.append({
                    "eval_id": ev["id"],
                    "eval_name": eval_name,
                    "time_seconds": elapsed,
                    "results": [{
                        "description": "claude -p execution",
                        "passed": False,
                        "grading": "deterministic",
                        "evidence": output[:300],
                    }],
                })
                any_failed = True
                continue

            det_results = grade_deterministic(tmpdir, ev["expectations"])
            all_det_passed = all(r["passed"] for r in det_results)

            llm_results = {}
            if all_det_passed:
                has_llm = any(
                    exp.get("grading") == "llm" for exp in ev["expectations"]
                )
                if has_llm:
                    if args.mode == "human":
                        print("  Running LLM grading...")
                    llm_results = grade_llm(tmpdir, ev["expectations"])

            merged = merge_results(det_results, llm_results, ev["expectations"])
            print_results(eval_name, merged, elapsed, args.mode)

            if any(not r["passed"] for r in merged):
                any_failed = True

            all_runs.append({
                "eval_id": ev["id"],
                "eval_name": eval_name,
                "time_seconds": elapsed,
                "results": merged,
            })
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    write_benchmark(output_dir, all_runs, timestamp)
    write_dashboard(output_dir, all_runs, timestamp)

    total_passed = sum(r["passed"] for run in all_runs for r in run["results"])
    total_exp = sum(len(run["results"]) for run in all_runs)
    total_time = sum(run["time_seconds"] for run in all_runs)
    minutes = int(total_time // 60)
    seconds = int(total_time % 60)
    time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

    print(f"\n=== Summary ===")
    print(f"Evals: {len(all_runs)} total, "
          f"{sum(1 for run in all_runs if all(r['passed'] for r in run['results']))} pass, "
          f"{sum(1 for run in all_runs if any(not r['passed'] for r in run['results']))} fail")
    print(f"Expectations: {total_passed}/{total_exp} passed")
    print(f"Time: {time_str}")
    print(f"Results: {output_dir.relative_to(PROJECT_ROOT)}/")

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
