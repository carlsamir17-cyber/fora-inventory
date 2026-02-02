from flask import Flask, render_template, request, redirect, url_for, session, flash
import csv, io, requests
import re

app = Flask(__name__)
app.secret_key = "FORA_SECRET_KEY_123456"

APP_PASSWORD = "Fora123"

DATABASE_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSCP2EPO0o-gj--OnVG5RP2S0pUItZtj0P_1OnQ-0DmPBvrwIRZ9q-47RaSaahqirkKK-htBcmN_ggL/pub?gid=1535841073&single=true&output=csv"
BOM_URL      = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS1rs_v3_8-Jub1LArBQCpmuGmyiZHUkWsA9yFn1b-bWOTGFJwwxKH394JjeYPkfgJoI6uRMgJmvlUo/pub?gid=1732588072&single=true&output=csv"


def clean_text(s):
    return str(s).replace("\u200f", "").replace("\u200e", "").strip() if s is not None else ""


def to_int(x, default=0):
    try:
        t = str(x).strip()
        if t == "":
            return default
        return int(float(t))
    except:
        return default


def extract_drive_file_id(value: str) -> str:
    v = clean_text(value)
    if not v:
        return ""

    # /file/d/<id>
    m = re.search(r"/file/d/([A-Za-z0-9_-]+)", v)
    if m:
        return m.group(1)

    # id=<id>
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", v)
    if m:
        return m.group(1)

    # لو مجرد ID
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", v):
        return v

    return ""


def normalize_image_url(value):
    """
    أفضل طريقة لعرض صور Google Drive داخل <img>:
    drive thumbnail endpoint
    """
    v = clean_text(value)
    if not v:
        return ""

    file_id = extract_drive_file_id(v)
    if file_id:
        # sz = حجم الصورة (كبره أو صغره حسب احتياجك)
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"

    # لو لينك صورة مباشر خارجي
    if v.startswith("http://") or v.startswith("https://"):
        return v

    return ""


def fetch_csv_rows(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        clean_row = {clean_text(k): clean_text(v) for k, v in row.items()}
        rows.append(clean_row)
    return rows


def normalize_database_rows(db_rows):
    out = []
    for r in db_rows:
        r["الدولاب"] = r.get("ستاند", "")

        item = {
            "الاسم": r.get("الاسم", ""),
            "المخزن": r.get("المخزن", ""),
            "الدولاب": r.get("الدولاب", ""),
            "الرف": r.get("الرف", ""),
            "باليتة": r.get("باليتة", ""),
            "الصورة": normalize_image_url(r.get("الصورة", "")),
            "المخزون": to_int(r.get("المخزون", 0))
        }
        out.append(item)
    return out


def normalize_bom_rows(bom_rows):
    out = []
    for r in bom_rows:
        out.append({
            "المنتج": r.get("المنتج", ""),
            "المكون": r.get("المكون", ""),
            "عدد في المنتج": to_int(r.get("عدد في المنتج", 0))
        })
    return out


def explode_bom(bom_rows, product, qty):
    need = {}
    for r in bom_rows:
        if r["المنتج"] == product:
            comp = r["المكون"]
            need[comp] = need.get(comp, 0) + r["عدد في المنتج"] * qty
    return need


def load_all_data():
    db = normalize_database_rows(fetch_csv_rows(DATABASE_URL))
    bom = normalize_bom_rows(fetch_csv_rows(BOM_URL))
    products = sorted(set(r["المنتج"] for r in bom if r["المنتج"]))
    return db, bom, products


def is_logged_in():
    return session.get("logged_in", False)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password", "") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("كلمة المرور غلط")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
    if not is_logged_in():
        return redirect(url_for("login"))

    db_rows, bom_rows, products = load_all_data()

    rows = []
    selected_product = ""
    x_qty = 1

    if request.method == "POST":
        selected_product = request.form.get("product", "")
        x_qty = to_int(request.form.get("qty", 1), default=1)
        if x_qty < 1:
            x_qty = 1

        need = explode_bom(bom_rows, selected_product, x_qty)
        db_map = {r["الاسم"]: r for r in db_rows}

        for item, req_qty in need.items():
            db_row = db_map.get(item, {})
            stock = db_row.get("المخزون", 0)
            missing = max(0, req_qty - stock)

            rows.append({
                "العنصر": item,
                "الكمية المطلوبة": req_qty,
                "المخزون": stock,
                "الناقص": missing,
                "الحالة": "متوفر" if missing == 0 else "ناقص",
                "المخزن": db_row.get("المخزن", ""),
                "الدولاب": db_row.get("الدولاب", ""),
                "الرف": db_row.get("الرف", ""),
                "باليتة": db_row.get("باليتة", ""),
                "الصورة": db_row.get("الصورة", "")
            })

    return render_template(
        "index.html",
        products=products,
        rows=rows,
        selected_product=selected_product,
        x_qty=x_qty
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


