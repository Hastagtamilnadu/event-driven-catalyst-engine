import json
from pathlib import Path

for filename in ["announcements_18_sep_2026.json", "announcements_14_17_sep_2026.json"]:
    path = Path(r"D:\02_Trading\data") / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"{filename}: type={type(data)}, len={len(data) if isinstance(data, list) else 'dict'}")
            if isinstance(data, list) and len(data) > 0:
                print("Sample keys:", list(data[0].keys()))
                print("Sample item:", data[0])
