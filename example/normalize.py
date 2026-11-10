import csv
from pathlib import Path

with Path("raw.csv").open(newline="", encoding="utf-8") as source:
    rows = list(csv.DictReader(source))
with Path("normalized.csv").open("w", newline="", encoding="utf-8") as output:
    writer = csv.writer(output)
    writer.writerow(["region", "sales"])
    writer.writerows((row["region"].strip().casefold(), int(row["sales"])) for row in rows)
