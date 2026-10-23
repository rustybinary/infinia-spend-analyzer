# Privacy

**What the app does with your data**
- Statements and the PDF password are read from your browser upload into the app's memory on your own computer (`127.0.0.1`). They are not written to disk and are cleared when you close the app.
- The server listens only on the local loopback address, so other devices on your network cannot reach it.
- No analytics, tracking, telemetry, fonts or scripts are loaded from the internet. The page works offline.
- The only internet use is the one-time install of open-source Python packages (`flask`, `pdfplumber`, `pandas`, `openpyxl`) from the public Python package index. No personal data is sent.

**What is saved on your computer**
- `category_overrides.json`, containing only merchant-name → category choices (for example `PHARMEASY → Medicine`), in:
  - Mac: `~/Library/Application Support/CCSorter/`
  - Windows: `%LOCALAPPDATA%\CCSorter\`
- A private Python environment and `install.log` in the same folder.
- Exports (Excel/CSV) are saved wherever your browser downloads them. They contain your transactions, so store them carefully.

**Keeping this repository free of personal data**
Contributors and the author should:
1. Never commit real statements, exports or screenshots of real transactions. `.gitignore` blocks PDFs (except `samples/DEMO_*.pdf`), spreadsheets, CSV, JSON and images (except README screenshots).
2. Run `python3 scripts/check_pii.py` before each commit. It looks for emails, card numbers, masked card numbers, CKYC ids, PAN, Aadhaar-like numbers, phone numbers, local user paths and stray data files.
3. Make screenshots only from the fictional demo statements.
4. Set a private commit identity: `git config user.name "<first name>"` and `git config user.email "<id>+<username>@users.noreply.github.com"`, and turn on GitHub's *Keep my email address private* and *Block command line pushes that expose my email*.
5. Do not paste real error logs or statement text into issues. Redact card digits, names and amounts first.

**Reporting a problem**
Open an issue without attaching statements. Describe the layout difference instead.
