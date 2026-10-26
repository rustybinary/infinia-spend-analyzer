#!/usr/bin/env python3
"""Infinia Spend Analyzer - local-only web app. Binds to 127.0.0.1; nothing leaves your computer.
PDF bytes and the password are handled in memory only and never written to disk."""
import base64
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


NAME_LINE = re.compile(r"^[A-Za-z][A-Za-z.']*(?: [A-Za-z][A-Za-z.']*){0,4}$")   # words and initials only, e.g. "ANITA K R"
NOT_A_NAME = {"date", "time", "description", "transaction", "transactions", "rewards", "amount", "total", "domestic",
              "international", "payment", "payments", "offers", "card", "statement", "balance", "debit", "credit",
              "details", "particulars", "emi", "sr", "no", "programs", "bonus", "points", "summary", "convert",
              "eligible", "pi", "page", "your", "on", "the", "of", "and", "to", "for"}


def is_name_heading(lines, i):
    """A line that is only a person's name (any case, initials allowed, no CKYC tag needed) sitting directly above a
    transaction row that has its own description. Column titles and labels are excluded by word list."""
    line = lines[i].strip()
    if len(line) > 45 or not NAME_LINE.match(line) or i + 1 >= len(lines):
        return False
    words = line.lower().replace(".", "").split()
    if any(w in NOT_A_NAME for w in words) or any(k in line.lower() for k in CREDIT_HINTS):
        return False
    nxt = PIPE_RE.match(lines[i + 1])
    return bool(nxt and nxt.group("desc").strip().rstrip("+").strip())


class Rows(list):
    """List of parsed rows that also remembers lines that looked like transactions but could not be read."""
    unparsed = None


def extract(pdf, source):
    rows, holder = Rows(), None   # None = no cardholder heading seen yet
    rows.unparsed = []
    for page in pdf.pages:
        plines = page_lines(page)
        lines = [t for t, _ in plines]
        for i, line in enumerate(lines):
            h = HOLDER_RE.match(line)
            if h:
                holder = first_name(h.group("n").strip())
                continue
            if is_name_heading(lines, i):
                holder = first_name(line.strip())
                continue
            if re.search(r"TRANSACTIONS\s+TOTAL\s+AMOUNT", line):
                holder = None   # end of this statement's transaction list: the next list starts with the main cardholder
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
                desc = re.sub(r"\s+-\s*\d+\s*$", "", desc)   # reversed reward points printed as "- 5"
                desc, city = split_city(desc)
                rows.append({"Date": dt, "Description": desc, "City": city, "Amount": amt,
                             "Base Pts": int(m.group("pts")) if m.group("pts") else 0,
                             "Cardholder": holder, "Source": source,
                             "_text_credit": text_credit, "_green": amount_is_green(plines[i][1])})
                continue
            m = LINE_RE.match(line)  # generic fallback: "DD/MM/YYYY  DESC  amount [CR]"
            if not m:
                if re.match(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*\|", line):
                    rows.unparsed.append(line.strip()[:80])
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


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def segment_date(base, progs):
    """Normally the statement date is the one in the file name. If a file holds several statements, a later summary
    names programmes from a later month, so move that summary's date to the same day in that month."""
    latest = None
    for p in progs:
        m = re.search(r"_([A-Za-z]{3})(\d{2})(?:_|$)", p["raw"])
        if m and m.group(1).lower() in MONTHS:
            key = (2000 + int(m.group(2)), MONTHS.index(m.group(1).lower()) + 1)
            latest = max(latest, key) if latest else key
    if latest and latest > (int(base[:4]), int(base[5:7])):
        return f"{latest[0]}-{latest[1]:02d}-{base[8:10]}"
    return base


def extract_rewards(pdf, source, txns):
    """Reads each 'Rewards Program Points Summary' table: programme rows + total. Returns (programmes, totals)."""
    base = statement_date(source, txns)
    segs, cur, inside = [], None, False
    for page in pdf.pages:
        for line in (page.extract_text() or "").splitlines():
            if REWARD_HDR.search(line):
                inside = True
                if cur is None:
                    cur = {"progs": [], "total": None}
                continue
            if not inside:
                continue
            m = PROG_RE.match(line)
            if m:
                cur["progs"].append({"raw": m.group("prog"), "program": m.group("prog").replace("_", " ").strip(),
                                     "points": int(m.group("pts").replace(",", ""))})
                continue
            m = TOTAL_RE.match(line)
            if m:
                cur["total"] = int(m.group("pts").replace(",", ""))
                segs.append(cur); cur, inside = None, False
            elif re.match(r"^\s*Important Information", line):
                inside = False
    if cur and cur["progs"]:
        segs.append(cur)
    progs, totals = [], []
    for s in segs:
        if not s["progs"] and s["total"] is None:
            continue
        sd = segment_date(base, s["progs"])
        for p in s["progs"]:
            progs.append({"statement": sd, "source": source, "program": p["program"], "points": p["points"]})
        calc = sum(p["points"] for p in s["progs"])
        totals.append({"statement": sd, "source": source, "total": s["total"] if s["total"] is not None else calc, "calc_total": calc})
    return progs, totals


@app.errorhandler(Exception)
def json_errors(e):
    from werkzeug.exceptions import HTTPException
    code = e.code if isinstance(e, HTTPException) else 500
    print("Error while handling a request:", repr(e))   # shown only in the app's own window, never saved
    return jsonify({"error": f"The app hit a problem ({type(e).__name__}). Please tell the author which statement it was."}), code


@app.route("/process", methods=["POST"])
def process():
    class _Upload:   # a file that arrived as base64 inside a JSON body
        def __init__(self, name, raw):
            self.filename, self._raw = name, raw

        def read(self):
            return self._raw

    if request.is_json:
        body = request.get_json(silent=True) or {}
        password = str(body.get("password", ""))
        uploads = []
        for item in body.get("files", []):
            try:
                uploads.append(_Upload(str(item.get("name", "statement.pdf")), base64.b64decode(item.get("data", ""))))
            except Exception:
                pass
    else:
        password = request.form.get("password", "")
        uploads = request.files.getlist("pdfs")
    log, rows, rewards, totals, lead_names = [], [], [], [], []
    for f in uploads:
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
            progs, tots = extract_rewards(pdf, f.filename, r)
        if r and r[0].get("Cardholder"):
            lead_names.append(r[0]["Cardholder"])   # heading appeared before the first transaction => that's the main cardholder
        rows += r
        rewards += progs
        totals += tots
        flagged = sum(1 for x in r if x.get("Check"))
        msg = f"{len(r)} transactions" if r else "Opened, but no transactions matched - layout may need a custom pattern"
        if progs:
            msg += f", {len(progs)} reward programmes"
        if flagged:
            msg += f" - {flagged} marked 'Review' (colour and text disagree about credit/debit)"
        unread = list(getattr(r, "unparsed", []) or [])
        if unread:
            msg += f" - WARNING: {len(unread)} line(s) start with a date but could not be read, e.g. “{unread[0]}”"
        log.append({"file": f.filename, "status": ("warn" if (flagged or unread or not r) else "ok"), "msg": msg, "_rows": r})
    password = None

    if not rows:
        return jsonify({"log": log, "error": "No transactions extracted."})

    from collections import Counter
    primary = Counter(lead_names).most_common(1)[0][0] if lead_names else "Primary"
    for x in rows:
        if not x.get("Cardholder"):
            x["Cardholder"] = primary   # transactions printed before any heading belong to the main cardholder
    for entry in log:   # statement check: who got how many transactions from each file
        fr = entry.pop("_rows", None)
        if fr:
            cnt = Counter(x["Cardholder"] for x in fr)
            entry["msg"] += " · by cardholder: " + ", ".join(f"{k} {v}" for k, v in cnt.most_common())
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


@app.route("/reassign", methods=["POST"])
def reassign():
    """Move one transaction to another cardholder (for this session only)."""
    body = request.get_json(force=True)
    name = first_name(str(body.get("holder", "")).strip())[:30]
    res = RESULTS.get(body.get("token"))
    if res is None or not name:
        return "Bad request", 400
    df = res["df"]
    df.loc[df["id"] == body.get("id"), "Cardholder"] = name
    return jsonify({"ok": True, "holder": name})


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
    return "ok-infinia"


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
