import json
d = json.load(open("coverage.json"))
rows = [(v["summary"]["percent_covered"], k) for k, v in d["files"].items()
        if "analytics" in k and v["summary"]["percent_covered"] < 85]
for p, f in sorted(rows):
    print(f"{p:.0f}%  {f}")
