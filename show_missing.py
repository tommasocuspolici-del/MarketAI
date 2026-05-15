import json
d = json.load(open("coverage.json"))
targets = [
    "engine\\analytics\\labour_market\\claims_cycle_detector.py",
    "engine\\analytics\\valuation\\pe_calculator.py",
]
for t in targets:
    if t in d["files"]:
        info = d["files"][t]
        pct = info["summary"]["percent_covered"]
        missing = info["missing_lines"]
        print(f"\n{t} ({pct:.0f}%)")
        print(f"  Missing lines: {missing[:15]}")
