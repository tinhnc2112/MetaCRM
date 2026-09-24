"""Allow the measured existing lint backlog, but reject a larger diagnostic count."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {
    "B008": 2, "B904": 4, "E501": 281, "F401": 1, "F821": 15,
    "I001": 37, "UP035": 2, "UP037": 21, "UP043": 1, "UP046": 1,
}


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend", "--output-format", "json", "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr)
        return result.returncode
    counts = Counter(item["code"] for item in json.loads(result.stdout))
    print(
        f"Ruff: {sum(counts.values())} existing/current diagnostics; "
        f"counts by rule: {dict(sorted(counts.items()))}"
    )
    increases = {code: count for code, count in counts.items() if count > BASELINE.get(code, 0)}
    if increases:
        print(f"Above M0 baseline: {increases}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
