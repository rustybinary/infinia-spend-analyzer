#!/usr/bin/env python3
"""Infinia Spend Analyzer - local-only web app. Binds to 127.0.0.1; nothing leaves your computer.
PDF bytes and the password are handled in memory only and never written to disk."""
import io
import os
import re
import secrets
import socket
import threading
import time
import sys
import webbrowser
from datetime import datetime

import pandas as pd
import pdfplumber
from flask import Flask, jsonify, request, send_file, Response


DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
                "%d %b %Y", "%d %b %y", "%d-%b-%Y", "%d-%b-%y", "%d %B %Y"]
DATE_RE = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[ -][A-Za-z]{3,9}[ -,]*\d{2,4})"
LINE_RE = re.compile(
    rf"^\s*{DATE_RE}\s+(?P<desc>.+?)\s+(?P<amt>-?[\d,]+\.\d{{2}})\s*(?P<crdr>CR|Cr|cr|DR|Dr|dr)?\s*$"
)

app = Flask(__name__)
RESULTS = {}          # token -> DataFrame (memory only)
LAST_PING = {"t": None}


def parse_date(s):
    s = re.sub(r"[ ,]+", " ", s.strip())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ---- Category rules (edit freely) ------------------------------------------
# Order matters: the first category with a matching word wins.
# A keyword starting with "~" must match as a whole word (e.g. "~ola" won't match "SOLAR").
RULES = [
    ("GyFTR", ["gyftr"]),
    ("Fuel", ["fuel", "petrol", "petro", "diesel", "hpcl", "bpcl", "iocl", "indian oil", "indianoil", "bharat petroleum",
              "hindustan petroleum", "~shell", "nayara", "reliance bp", "jio-bp", "jio bp", "essar oil", "filling station", "~cng"]),
    ("Payments / Refunds", ["payment received", "cc payment", "bppy", "bbps", "neft", "imps", "upi payment", "thank you",
                            "reversal", "refund", "cashback", "autopay", "netbanking"]),
    ("Fees & Interest", ["finance charge", "interest", "late fee", "late payment", "annual fee", "joining fee", "membership fee",
                         "overlimit", "~gst", "igst", "cgst", "sgst", "convenience fee", "forex markup", "surcharge"]),
    ("Medicine", ["pharmeasy", "pharmacy", "pharmacies", "pharma", "medplus", "1mg", "netmeds", "medicine", "medicines",
                  "medical store", "medicals", "medico", "chemist", "drugs", "drugstore"]),
    ("Health", ["apollo", "hospital", "clinic", "diagnostic", "healthcare", "health care", "ortho", "dental", "dentist",
                "~lab", "labs", "laborator", "radiology", "eye care", "optical", "nursing", "physio", "doctor", "ayurved",
                "cardio", "derma", "fertility", "hearing", "~scan", "scans", "medical", "~medic"]),
    ("Food & Dining", ["swiggy", "zomato", "restaurant", "resto", "~cafe", "coffee", "starbucks", "dominos", "domino", "mcdonald",
                       "~kfc", "burger", "pizza", "food", "~veg", "bakery", "bakers", "sweets", "kitchen", "biryani", "dhaba",
                       "~mess", "ice cream", "juice", "~tea", "~chai", "~pub", "brewery", "eatery", "canteen", "tiffin", "udupi",
                       "darshini", "~dosa", "~idli", "chaat", "thali", "meals", "eatfit", "box8", "faasos", "barbeque", "haldiram",
                       "chai point", "third wave", "blue tokai", "subway", "~dunkin", "baskin", "~cake", "magicpin", "dineout"]),
    ("Groceries", ["bigbasket", "blinkit", "zepto", "dmart", "d mart", "instamart", "grofers", "reliance fresh", "jiomart",
                   "~more", "spencer", "natures basket", "nature's basket", "supermarket", "super market", "hypermarket", "kirana",
                   "provision", "general store", "~fresh", "vegetable", "fruits", "~milk", "dairy", "nandini", "~amul", "~mart",
                   "grocer", "ration", "licious", "country delight", "star bazaar", "big bazaar"]),
    ("Travel & Stays", ["uber", "~ola", "rapido", "makemytrip", "~mmt", "irctc", "indigo", "air india", "vistara", "akasa", "spicejet",
                        "goibibo", "cleartrip", "redbus", "abhibus", "ixigo", "yatra", "airlines", "airways", "airport", "railway",
                        "~metro", "bmtc", "ksrtc", "~taxi", "~cab", "cabs", "fastag", "~toll", "parking", "~flight", "easemytrip",
                        "~oyo", "airbnb", "booking.com", "agoda", "treebo", "fabhotels", "resort", "~inn", "lodge", "homestay",
                        "tours", "travels", "holidays", "~visa", "emirates", "qatar", "lufthansa", "marriott", "taj hotels", "hyatt",
                        "~ihg", "oberoi", "itc hotels", "lemon tree", "radisson", "hotels", "~hotel"]),
    ("Bills & Utilities", ["airtel", "~jio", "~vi", "vodafone", "idea cellular", "bsnl", "act fibernet", "hathway", "tata play",
                           "tatasky", "dish tv", "bescom", "electricity", "~power", "water board", "bwssb", "~gas", "indane",
                           "bharat gas", "piped gas", "broadband", "fibernet", "recharge", "postpaid", "prepaid", "~dth",
                           "municipal", "property tax", "billdesk", "bill desk", "cred club"]),
    ("Subscriptions & Streaming", ["netflix", "spotify", "hotstar", "disney", "prime video", "youtube", "google play", "~google",
                                   "apple.com", "itunes", "icloud", "sonyliv", "zee5", "jiocinema", "gaana", "wynk", "audible",
                                   "kindle", "openai", "chatgpt", "anthropic", "claude", "github", "adobe", "microsoft", "dropbox",
                                   "notion", "canva", "linkedin", "~zoom", "1password", "lastpass", "amazon prime", "prime membership"]),
    ("Entertainment & Events", ["bookmyshow", "~pvr", "~inox", "cinema", "cinepolis", "theatre", "theater", "multiplex", "gaming",
                                "steam", "playstation", "xbox", "dream11", "~mpl", "amusement", "imagica", "wonderla", "bowling",
                                "concert", "~event", "events", "insider.in", "paytm insider"]),
    ("Insurance & Investments", ["insurance", "~lic", "hdfc life", "icici pru", "sbi life", "star health", "max life", "policybazaar",
                                 "acko", "mutual fund", "zerodha", "groww", "upstox", "~nps", "assurance"]),
    ("Education", ["school", "college", "university", "tuition", "coaching", "academy", "institute", "byju", "unacademy", "udemy",
                   "coursera", "vedantu", "bookstore", "book store", "crossword", "sapna book", "stationery", "~books"]),
    ("Jewellery & Watches", ["jewel", "tanishq", "~titan", "caratlane", "malabar", "kalyan", "joyalukkas", "senco", "~gold",
                             "diamond", "~silver", "fastrack", "sonata", "~watch", "watches"]),
    ("Fashion & Apparel", ["myntra", "ajio", "zara", "h&m", "westside", "pantaloons", "lifestyle", "max fashion", "trends",
                           "textile", "silk", "saree", "fashion", "apparel", "clothing", "garment", "boutique", "tailor", "readymade",
                           "denim", "levi", "allen solly", "van heusen", "peter england", "raymond", "fabindia", "shoppers stop",
                           "footwear", "shoes", "~bata", "woodland", "~puma", "~nike", "adidas", "skechers", "lenskart", "~central",
                           "wear"]),
    ("Electronics", ["croma", "reliance digital", "vijay sales", "apple store", "samsung", "oneplus", "xiaomi", "~boat", "ezone",
                     "laptop", "~mobile", "~phone", "computer", "electronics", "electronic", "gadget", "~dell", "lenovo", "~asus",
                     "~acer", "~bose", "~jbl", "headphone", "camera", "~canon", "~nikon", "~gopro", "printer", "imagine store"]),
    ("Home & Furniture", ["ikea", "pepperfry", "urban ladder", "home centre", "homecentre", "furniture", "furnishing", "mattress",
                          "sleepwell", "kurlon", "wakefit", "godrej interio", "hardware", "~paint", "asian paints", "berger",
                          "plywood", "electricals", "electrical", "sanitary", "~tiles", "kitchenware", "appliance", "hometown",
                          "home town", "decor", "interior", "curtain", "urban company", "housekeeping"]),
    ("Personal Care", ["salon", "~spa", "parlour", "parlor", "beauty", "naturals", "jawed habib", "lakme", "nykaa", "sephora",
                       "purplle", "barber", "grooming", "cosmetic", "bodycare", "the body shop"]),
    ("Sports & Fitness", ["~gym", "fitness", "cult.fit", "cultfit", "decathlon", "yoga", "~sports", "~sport", "~golf", "cricket",
                          "swimming", "badminton", "~turf"]),
    ("Kids & Toys", ["hamleys", "firstcry", "~toys", "~toy", "~kids", "~baby"]),
    ("Gifts & Flowers", ["ferns", "~fnp", "~igp", "floral", "florist", "~gift", "gifts", "archies", "bouquet"]),
    ("Pets", ["~pet", "~pets", "~vet", "petco", "pawsh", "heads up for tails"]),
    ("Government & Taxes", ["income tax", "challan", "govt", "government", "passport", "~rto", "traffic", "stamp duty",
                            "registrar", "bbmp"]),
    ("Donations", ["donation", "foundation", "charity", "temple", "devasthana", "~trust", "iskcon", "gurudwara", "~ngo"]),
    ("Rent & Housing", ["~rent", "nobroker", "nestaway", "housing.com", "maintenance", "~society", "apartment"]),
    ("Shopping", ["amazon", "flipkart", "meesho", "snapdeal", "tata cliq", "tatacliq", "~mall", "bazaar", "emporium",
                  "collections", "stores", "~store", "retail", "trading", "bhandar", "agencies", "~enterprises"]),
    ("SmartBuy", ["smartbuy"]),
]
BUSINESS_WORDS = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "ventures", "venture", "enterprises", "traders",
                  "associates", "industries", "sons", "bros", "brothers", "services", "solutions", "technologies", "systems"}
UNCAT = "Uncategorised"
CATEGORY_NAMES = [n for n, _ in RULES] + ["Individual / local merchant", UNCAT]


def _compile(kws):
    return re.compile("|".join((r"\b" + re.escape(k[1:]) + r"\b") if k.startswith("~") else re.escape(k) for k in kws), re.I)


COMPILED = [(n, _compile(k)) for n, k in RULES]

def _support_dir():
    if os.environ.get("CCSORTER_DIR"):
        return os.environ["CCSORTER_DIR"]
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "CCSorter")
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"), "CCSorter")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "CCSorter")


SUPPORT_DIR = _support_dir()
OVERRIDES_PATH = os.path.join(SUPPORT_DIR, "category_overrides.json")


def _norm(desc):
    return re.sub(r"\s+", " ", desc.strip().lower())


def load_overrides():
    try:
        import json
        with open(OVERRIDES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_overrides(ov):
    import json
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    tmp = OVERRIDES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ov, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, OVERRIDES_PATH)


OVERRIDES = load_overrides()


def categorize(desc, credit=False):
    """Your remembered fixes first, then the rules above, then a name-shape guess."""
    key = _norm(desc)
    if key in OVERRIDES:
        return OVERRIDES[key]
    for name, rx in COMPILED:
        if name == "Payments / Refunds" and not credit:
            continue  # a debit can't be a payment/refund, whatever its name says
        if rx.search(desc):
            return name
    if credit:
        return "Payments / Refunds"
    words = re.sub(r"[^A-Za-z ]", " ", desc).split()
    if words and not any(w.lower() in BUSINESS_WORDS for w in words):
        initials = sum(1 for w in words[:-1] if len(w) == 1)
        looks_like_person = (len(words) == 2 and all(len(w) >= 3 for w in words)) or \
                            (2 <= len(words) <= 4 and initials == len(words) - 1 and len(words[-1]) >= 4)
        if looks_like_person:
            return "Individual / local merchant"   # e.g. "BHARATH PATEL", "V R WALAVALKAR": a person-named shop
    return UNCAT
# -----------------------------------------------------------------------------


PIPE_RE = re.compile(
    r"^\s*(?P<d>\d{2}/\d{2}/\d{4})\s*\|\s*(?P<t>\d{1,2}:\d{2})\s+(?P<desc>.*?)"
    r"(?:\s*(?P<plus>\+)\s*(?P<pts>\d*))?"
    r"\s+(?:[C₹`]|Rs\.?)?\s*(?P<amt>[\d,]+\.\d{2})\s*(?P<crdr>CR|Cr|cr|DR|Dr|dr)?\s*\S?\s*$"
)
HOLDER_RE = re.compile(r"^\s*(?P<n>[A-Z][A-Za-z.' ]{1,40}?)\s*\[CKYC ID")
# The statement glues merchant and city together (e.g. "SWIGGYBengaluru"); split a known trailing city.
CITIES = ["BENGALURU", "BANGALORE", "DAVANGERE", "DAVANAGERE", "MUMBAI", "GURGAON", "GURUGRAM", "DELHI",
          "NEW DELHI", "CHENNAI", "HYDERABAD", "PUNE", "KOLKATA", "NOIDA", "MYSORE", "MANGALORE", "COCHIN", "KOCHI"]


def split_city(desc):
    up = desc.upper()
    for c in sorted(CITIES, key=len, reverse=True):
        if up.endswith(c) and len(desc) > len(c):
            return desc[:-len(c)].rstrip(), desc[-len(c):].title()
    return desc, ""


CREDIT_HINTS = ["cc payment", "payment received", "bppy", "thank you", "reversal", "refund",
                "cashback", "waiver", "credit voucher", "autopay"]
SKIP_NEIGHBOR = re.compile(r"DATE & TIME|Domestic|International|TRANSACTIONS TOTAL|CKYC|Page \d|REWARDS|AMOUNT|PI$", re.I)


def neighbor_desc(lines, i):
    """When the description sits on the line above/below the dated row, borrow it."""
    for j in (i + 1, i - 1):
        if 0 <= j < len(lines):
            s = lines[j].strip()
            if (s and not re.match(r"^\d{2}/\d{2}/\d{4}", s) and not SKIP_NEIGHBOR.search(s)
                    and not re.search(r"\d[\d,]*\.\d{2}", s) and len(s) <= 80):
                return s
    return ""


def page_lines(page):
    """[(text, chars)] per visual line; chars carry the font colour."""
    try:
        return [(l["text"], l["chars"]) for l in page.extract_text_lines(return_chars=True)]
    except Exception:
        return [(t, []) for t in (page.extract_text() or "").splitlines()]


def to_rgb(col):
    try:
        col = tuple(float(x) for x in col)
    except Exception:
        return None
    if len(col) == 1:
        return (col[0],) * 3
    if len(col) == 3:
        return col
    if len(col) == 4:  # CMYK
        c, m, y, k = col
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def amount_is_green(chars):
    """True/False from the colour of the amount digits; None if it can't be read."""
    digits = [c for c in chars if c.get("text") in "0123456789"]
    if not digits:
        return None
    rgb = to_rgb(digits[-1].get("non_stroking_color"))
    if rgb is None:
        return None
    r, g, b = rgb
    return g >= 0.35 and g > r + 0.15 and g > b + 0.15


SALUTATIONS = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "sri", "mx"}


def first_name(n):
    parts = [p for p in n.split() if p]
    while len(parts) > 1 and parts[0].rstrip(".").lower() in SALUTATIONS:
        parts.pop(0)
    return parts[0].title() if parts else n.title()


def extract(pdf, source):
    rows, holder = [], None   # None = no cardholder heading seen yet
    for page in pdf.pages:
        plines = page_lines(page)
        lines = [t for t, _ in plines]
        for i, line in enumerate(lines):
            h = HOLDER_RE.match(line)
            if h:
                holder = first_name(h.group("n").strip())
                continue
            m = PIPE_RE.match(line)
            if m:  # HDFC-style: "DD/MM/YYYY| HH:MM  DESC  [+ pts]  C amount"
                dt = datetime.strptime(f'{m.group("d")} {m.group("t")}', "%d/%m/%Y %H:%M")
                amt = float(m.group("amt").replace(",", ""))
                sign_credit = bool((m.group("plus") and not m.group("pts")) or (m.group("crdr") or "").upper() == "CR")
                desc = m.group("desc").strip().rstrip("+").strip()
                if not desc:
                    desc = neighbor_desc(lines, i) or "(no description on statement)"
                text_credit = sign_credit or any(k in desc.lower() for k in CREDIT_HINTS)
                if desc.upper().startswith("EMI "):   # badge text = "eligible to convert to EMI", not an EMI
                    desc = desc[4:].strip()
                desc, city = split_city(desc)
                rows.append({"Date": dt, "Description": desc, "City": city, "Amount": amt,
                             "Base Pts": int(m.group("pts")) if m.group("pts") else 0,
                             "Cardholder": holder, "Source": source,
                             "_text_credit": text_credit, "_green": amount_is_green(plines[i][1])})
                continue
            m = LINE_RE.match(line)  # generic fallback: "DD/MM/YYYY  DESC  amount [CR]"
            if not m:
                continue
            dt = parse_date(m.group(1))
            if not dt:
                continue
            amt = float(m.group("amt").replace(",", ""))
            crdr = (m.group("crdr") or "").upper()
            desc = m.group("desc").strip()
            rows.append({"Date": dt, "Description": desc, "City": "", "Amount": abs(amt),
                         "Base Pts": 0, "Cardholder": holder, "Source": source,
                         "_text_credit": crdr == "CR" or amt < 0, "_green": None})

    # Decide credit vs debit. If this statement colours credits green, colour is authoritative
    # (green = credit, other = debit). If no green amounts exist, colour isn't used by this
    # bank/statement, so rely on the "+" sign, CR marker and payment/refund wording instead.
    colour_used = any(r["_green"] for r in rows)
    for r in rows:
        green, text = r.pop("_green"), r.pop("_text_credit")
        credit = green if (colour_used and green is not None) else (text or bool(green))
        r["Check"] = "Review" if (colour_used and green is not None and green != text) else ""
        r["Amount"] = -r["Amount"] if credit else r["Amount"]
        r["Type"] = "Credit" if credit else "Debit"
        r["Category"] = categorize(r["Description"], credit)
    return rows


def fy_label(d):
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


REWARD_HDR = re.compile(r"Rewards?\s+Program\s+Points\s+Summary", re.I)
PROG_RE = re.compile(r"^\s*(?P<n>\d+)\s+(?P<prog>.+?)\s+(?P<pts>[\d,]+)\s*pts\s*$", re.I)
TOTAL_RE = re.compile(r"^\s*Total\s+(?P<pts>[\d,]+)\s*pts\s*$", re.I)


def statement_date(filename, txns):
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", filename)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return max((t["Date"] for t in txns), default=datetime.now()).strftime("%Y-%m-%d")


def extract_rewards(pdf, source, txns):
    """Reads the 'Rewards Program Points Summary' table: programme rows + total."""
    sdate, progs, total, inside = statement_date(source, txns), [], None, False
    for page in pdf.pages:
        for line in (page.extract_text() or "").splitlines():
            if REWARD_HDR.search(line):
                inside = True
                continue
            if not inside:
                continue
            m = PROG_RE.match(line)
            if m:
                progs.append({"statement": sdate, "source": source,
                              "program": m.group("prog").replace("_", " ").strip(),
                              "points": int(m.group("pts").replace(",", ""))})
                continue
            m = TOTAL_RE.match(line)
            if m:
                total = int(m.group("pts").replace(",", ""))
                inside = False
            elif re.match(r"^\s*Important Information", line):
                inside = False
    if not progs and total is None:
        return [], None
    return progs, {"statement": sdate, "source": source,
                   "total": total if total is not None else sum(p["points"] for p in progs),
                   "calc_total": sum(p["points"] for p in progs)}


@app.route("/process", methods=["POST"])
def process():
    password = request.form.get("password", "")
    log, rows, rewards, totals, lead_names = [], [], [], [], []
    for f in request.files.getlist("pdfs"):
        data, pdf = f.read(), None
        for pw in (password, ""):
            try:
                pdf = pdfplumber.open(io.BytesIO(data), password=pw)
                _ = pdf.pages[0]
                break
            except Exception:
                pdf = None
        if pdf is None:
            log.append({"file": f.filename, "status": "error", "msg": "Could not open (wrong password?)"})
            continue
        with pdf:
            r = extract(pdf, f.filename)
            progs, tot = extract_rewards(pdf, f.filename, r)
        if r and r[0].get("Cardholder"):
            lead_names.append(r[0]["Cardholder"])   # heading appeared before the first transaction => that's the main cardholder
        rows += r
        rewards += progs
        if tot:
            totals.append(tot)
        flagged = sum(1 for x in r if x.get("Check"))
        msg = f"{len(r)} transactions" if r else "Opened, but no transactions matched - layout may need a custom pattern"
        if progs:
            msg += f", {len(progs)} reward programmes"
        if flagged:
            msg += f" - {flagged} marked 'Review' (colour and text disagree about credit/debit)"
        log.append({"file": f.filename, "status": ("warn" if (flagged or not r) else "ok"), "msg": msg})
    password = None

    if not rows:
        return jsonify({"log": log, "error": "No transactions extracted."})

    from collections import Counter
    primary = Counter(lead_names).most_common(1)[0][0] if lead_names else "Primary"
    for x in rows:
        if not x.get("Cardholder"):
            x["Cardholder"] = primary   # transactions printed before any heading belong to the main cardholder
    df = pd.DataFrame(rows)
    # drop overlaps between different statements, but keep genuine repeats within one statement
    df["_n"] = df.groupby(["Date", "Description", "Amount", "Source"]).cumcount()
    df = df.drop_duplicates(subset=["Date", "Description", "Amount", "_n"]).drop(columns="_n")
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["id"] = df.index
    df["FY"] = df["Date"].apply(fy_label)
    df["Month"] = df["Date"].dt.strftime("%Y-%m")

    token = secrets.token_urlsafe(12)
    RESULTS[token] = {"df": df, "rewards": rewards, "totals": totals}

    out = pd.DataFrame({
        "id": df["id"], "date": df["Date"].dt.strftime("%Y-%m-%d"),
        "time": df["Date"].dt.strftime("%H:%M").where(df["Date"].dt.strftime("%H:%M") != "00:00", ""),
        "desc": df["Description"], "city": df["City"], "amt": df["Amount"], "type": df["Type"],
        "cat": df["Category"], "pts": df["Base Pts"], "holder": df["Cardholder"],
        "check": df["Check"], "src": df["Source"], "month": df["Month"], "fy": df["FY"]})
    for p in rewards:
        p["fy"] = fy_label(datetime.strptime(p["statement"], "%Y-%m-%d"))
    for t in totals:
        t["fy"] = fy_label(datetime.strptime(t["statement"], "%Y-%m-%d"))
    cats = list(CATEGORY_NAMES)
    for c in list(OVERRIDES.values()) + list(df["Category"]):
        if c not in cats:
            cats.insert(len(cats) - 1, c)
    return jsonify({"log": log, "token": token, "rows": out.to_dict("records"), "cats": cats,
                    "rewards": rewards, "totals": totals})


@app.route("/override", methods=["POST"])
def override():
    """Remember a category fix for a merchant name (stored locally; applies to future uploads too)."""
    body = request.get_json(force=True)
    desc, cat = str(body.get("desc", "")).strip(), str(body.get("cat", "")).strip()
    if not desc or not cat or len(cat) > 40:
        return "Bad request", 400
    OVERRIDES[_norm(desc)] = cat
    try:
        save_overrides(OVERRIDES)
    except Exception:
        pass   # still applies for this session
    res = RESULTS.get(body.get("token"))
    if res is not None:
        df = res["df"]
        mask = df["Description"].map(_norm) == _norm(desc)
        df.loc[mask, "Category"] = cat
    return jsonify({"ok": True})


@app.route("/export", methods=["POST"])
def export():
    body = request.get_json(force=True)
    res = RESULTS.get(body.get("token"))
    if res is None:
        return "Not found", 404
    df = res["df"]
    sel = df[df["id"].isin(body.get("ids", []))].copy()
    fmt = body.get("fmt", "xlsx")
    cols = ["Date", "Description", "City", "Amount", "Type", "Category", "Base Pts", "Cardholder", "Check", "Source"]
    if fmt == "csv":
        return Response(sel[cols].to_csv(index=False), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=transactions.csv"})
    spend = sel[sel["Type"] == "Debit"]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", datetime_format="DD-MMM-YYYY HH:MM") as xw:
        sel[cols].to_excel(xw, sheet_name="Transactions", index=False)
        for name, key in (("By Month", "Month"), ("By Category", "Category"), ("By Cardholder", "Cardholder")):
            g = spend.groupby(key)["Amount"].agg(Txns="count", TotalSpend="sum")
            (g.sort_values("TotalSpend", ascending=False) if key != "Month" else g).to_excel(xw, sheet_name=name)
        sel[sel["Category"] == "GyFTR"][cols].to_excel(xw, sheet_name="GyFTR", index=False)
        rw = pd.DataFrame(res["rewards"] or [{"statement": "", "source": "", "program": "(none found)", "points": 0}])
        rw["counts_as"] = rw["program"].apply(lambda p: "Accelerated" if re.search(r"\d+\s*X\b", p, re.I) else "Base (category)")
        rw.rename(columns={"statement": "Statement", "source": "Source", "program": "Programme", "points": "Points", "fy": "FY", "counts_as": "Counts as"}) \
            .to_excel(xw, sheet_name="Rewards", index=False)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="transactions.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/ping")
def ping():
    LAST_PING["t"] = time.time()
    return "ok"


@app.route("/quit", methods=["POST"])
def quit_app():
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return "bye"


PAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")


@app.route("/")
def index():
    with open(PAGE_PATH, encoding="utf-8") as fh:
        return Response(fh.read(), mimetype="text/html")


def watchdog():
    # Exit when the browser tab is closed (no heartbeat for 20s after first ping)
    while True:
        time.sleep(5)
        t = LAST_PING["t"]
        if t and time.time() - t > 20:
            os._exit(0)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


if __name__ == "__main__":
    port = free_port()
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    app.run(host="127.0.0.1", port=port, debug=False)
