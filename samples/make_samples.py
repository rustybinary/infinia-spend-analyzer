"""Generates FICTIONAL, password-protected demo statements (password: demo1234).
Names, merchants and amounts are invented. Nothing here comes from a real statement."""
import random
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

PASSWORD = "demo1234"
G, K = (0.02, 0.78, 0.28), (0.2, 0.2, 0.2)
MERCH = [("SWIGGY BENGALURU", 180, 900), ("ZOMATO GURGAON", 200, 1100), ("BIGBASKET BENGALURU", 600, 3200),
         ("AMAZON PAY INDIA", 400, 9000), ("MYNTRA DESIGNS BENGALURU", 900, 6500), ("INDIGO AIRLINES GURGAON", 3500, 14000),
         ("IRCTC DELHI", 600, 4200), ("NETFLIX MUMBAI", 649, 649), ("AIRTEL POSTPAID DELHI", 999, 1499),
         ("APOLLO PHARMACIES LIMITED CHENNAI", 250, 1900), ("HP PETROL PUMP BENGALURU", 1500, 4000),
         ("GYFTR TECHNOLOGIES BENGALURU", 1000, 5000), ("TANISHQ JEWELLERY MUMBAI", 8000, 60000),
         ("STARBUCKS COFFEE BENGALURU", 300, 900), ("BESCOM ELECTRICITY BENGALURU", 900, 2600),
         ("PVR CINEMAS BENGALURU", 400, 1600), ("SMARTBUY REWARDS MUMBAI", 1000, 8000),
         ("MAX HEALTHCARE DELHI", 800, 7000), ("DECATHLON SPORTS BENGALURU", 700, 5200), ("CROMA ELECTRONICS MUMBAI", 2000, 38000)]

def fmt(n):
    s = f"{n:.2f}"; i, d = s.split("."); 
    if len(i) > 3:
        head, tail = i[:-3], i[-3:]; parts = []
        while len(head) > 2: parts.insert(0, head[-2:]); head = head[:-2]
        if head: parts.insert(0, head)
        i = ",".join(parts + [tail])
    return f"{i}.{d}"

def statement(fname, month, year, seed, progs):
    rnd = random.Random(seed); lines = [("RIYA SHARMA [CKYC ID : 0000 ]", K)]
    days = sorted(rnd.sample(range(1, 21), 12)); addon_at = 8
    for n, d in enumerate(days):
        if n == addon_at: lines.append(("ARJUN SHARMA [CKYC ID : 0000 ]", K))
        m, lo, hi = rnd.choice(MERCH); amt = round(rnd.uniform(lo, hi))
        lines.append((f"{d:02d}/{month:02d}/{year}| {rnd.randint(8,22):02d}:{rnd.choice(['05','18','42','56'])} {m} + {max(2,amt//150)} C {fmt(amt)} l", K))
    lines.append((f"22/{month:02d}/{year}| 09:10 + C {fmt(25000)} l", G))   # card bill payment (green = credit)
    lines += [("Rewards Program Points Summary", K), ("SR NO. PROGRAMS BONUS POINTS", K)]
    tot = 0
    for i, (n, p) in enumerate(progs, 1): lines.append((f"{i} {n} {p:,} pts", K)); tot += p
    lines += [(f"Total {tot:,} pts", K), ("Important Information", K)]
    tmp = fname + ".tmp"; c = canvas.Canvas(tmp, pagesize=A4); y = 800
    for t, col in lines: c.setFillColorRGB(*col); c.drawString(30, y, t); y -= 16
    c.save(); r = PdfReader(tmp); w = PdfWriter()
    for pg in r.pages: w.add_page(pg)
    w.encrypt(PASSWORD); w.write(open(fname, "wb")); import os; os.remove(tmp)

if __name__ == "__main__":
    statement("DEMO_21-08-2026.pdf", 8, 2026, 1, [("SmartBuy_Aug26_Bonus_10X_RP_Pro0000", 2400), ("SmartBuy_Aug26_Bonus_5X_RP_Pro0000", 1800), ("Reward Points_on_Insurance", 3000), ("Reward Points_on_Grocery", 450)])
    statement("DEMO_21-09-2026.pdf", 9, 2026, 2, [("SmartBuy_Sep26_Bonus_5X_RP_Pro0000", 2100), ("SmartBuy_Sep26_Bonus_3X_RP_Pro0000", 320), ("Reward Points_on_Telecom", 400), ("Reward Points_on_Grocery", 520)])
    statement("DEMO_21-10-2026.pdf", 10, 2026, 3, [("SmartBuy_Oct26_Bonus_10X_RP_Pro0000", 3100), ("SmartBuy_Oct26_Bonus_5X_RP_Pro0000", 1500), ("Reward Points_on_Insurance", 2600)])
    print("Wrote 3 demo statements. Password:", PASSWORD)
