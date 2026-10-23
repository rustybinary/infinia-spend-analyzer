#!/usr/bin/env python3
"""Builds dist/Infinia-Spend-Analyzer-Mac.zip and dist/Infinia-Spend-Analyzer-Windows.zip from src/ and assets/.
Zips use a fixed timestamp and no owner/uid metadata, so they carry nothing about the machine that built them."""
import os, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, AS, DIST = (os.path.join(ROOT, d) for d in ("src", "assets", "dist"))
STAMP = (2026, 1, 1, 0, 0, 0)

def add(z, arc, data, mode=0o644):
    zi = zipfile.ZipInfo(arc, STAMP); zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = (0o100000 | mode) << 16; zi.create_system = 3; z.writestr(zi, data)

def rd(*p):
    with open(os.path.join(*p), "rb") as f: return f.read()

os.makedirs(DIST, exist_ok=True)
app = "Infinia Spend Analyzer.app/Contents/"
with zipfile.ZipFile(os.path.join(DIST, "Infinia-Spend-Analyzer-Mac.zip"), "w") as z:
    add(z, app + "Info.plist", rd(AS, "mac", "Info.plist"))
    add(z, app + "MacOS/InfiniaSpendAnalyzer", rd(AS, "mac", "launcher.sh"), 0o755)   # must stay executable
    add(z, app + "Resources/app.py", rd(SRC, "app.py"))
    add(z, app + "Resources/page.html", rd(SRC, "page.html"))
    add(z, app + "Resources/AppIcon.icns", rd(AS, "AppIcon.icns"))
folder = "InfiniaSpendAnalyzer-Windows/"
with zipfile.ZipFile(os.path.join(DIST, "Infinia-Spend-Analyzer-Windows.zip"), "w") as z:
    add(z, folder + "Start-Infinia-Spend-Analyzer.bat", rd(AS, "windows", "Start-Infinia-Spend-Analyzer.bat"))
    add(z, folder + "README.txt", rd(AS, "windows", "README.txt"))
    add(z, folder + "app.py", rd(SRC, "app.py"))
    add(z, folder + "page.html", rd(SRC, "page.html"))
print("Built:", *sorted(os.listdir(DIST)), sep="\n  ")
