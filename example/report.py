import csv
import json
from collections import Counter
from pathlib import Path

totals = Counter()
with Path("normalized.csv").open(newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        totals[row["region"]] += int(row["sales"])
Path("summary.json").write_text(json.dumps(totals, indent=2, sort_keys=True) + "\n", encoding="utf-8")
