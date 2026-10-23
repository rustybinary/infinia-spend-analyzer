#!/usr/bin/env python3
"""Run before every commit:  python3 scripts/check_pii.py
Fails if tracked-looking files contain things that look like personal or card data."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "dist", "venv", ".venv", "__pycache__"}
PATTERNS = {
    "email address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "16-digit card number": r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)",
    "masked card (e.g. 4375XXXXXXXXXX60)": r"\b\d{4}X{4,}\d{2,4}\b",
    "CKYC id with digits": r"CKYC ID\s*:?\s*\d{5,}",
    "PAN number": r"\b[A-Z]{5}\d{4}[A-Z]\b",
    "12-digit id (Aadhaar-like)": r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)",
    "phone number": r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)",
    "local user path": r"(?:/Users/|/home/|C:\\Users\\)[A-Za-z0-9._-]+",
}
bad = []
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in SKIP_DIRS]
    for f in fn:
        p = os.path.join(dp, f); rel = os.path.relpath(p, ROOT)
        ext = f.lower().rsplit(".", 1)[-1] if "." in f else ""
        if ext == "pdf" and not re.match(r"samples[/\\]DEMO_", rel): bad.append((rel, "PDF that is not a DEMO_ sample")); continue
        if ext in ("xlsx", "xls", "csv", "zip", "heic", "jpg", "jpeg"): bad.append((rel, f"data/binary file type .{ext}")); continue
        if ext in ("png", "icns", "pdf"): continue
        try: t = open(p, encoding="utf-8").read()
        except Exception: continue
        t = re.sub(r"data:[a-z/+-]+;base64,[A-Za-z0-9+/=]+", "", t)           # embedded images
        if f == "check_pii.py": continue
        for name, rx in PATTERNS.items():
            for m in re.finditer(rx, t):
                if name == "16-digit card number" and re.fullmatch(r"[\d.\- ]+", m.group(0)) and "." in m.group(0): continue
                bad.append((rel, f"{name}: {m.group(0)[:40]}"))
if bad:
    print("Possible personal data found:"); [print(" -", r, "->", why) for r, why in bad]; sys.exit(1)
print("OK: nothing that looks like personal or card data.")
