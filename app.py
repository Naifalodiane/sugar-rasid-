from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import streamlit as st
import urllib.parse
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ============================================================
#  نظام «سند» - تطبيق الأب
#  التحديثات الجديدة في هذه النسخة:
#   1) زر فزعة (SOS) يدوي فوري - لا يحتاج قراءة سكر
#   2) قاعدة بيانات SQLite حقيقية - البيانات ما تضيع بعد التحديث
#   3) موقع GPS حقيقي من متصفح الجهاز (بدل الإحداثيات الثابتة)
# ============================================================

st.set_page_config(page_title="تطبيق الأب - سند", layout="wide")

# ------------------------------------------------------------
# تنسيق بصري مخصص بهوية «سند» - خط أكبر، أزرار أوضح، SOS نابض
# ------------------------------------------------------------
st.markdown("""
<style>
    html, body, [class*="css"]  {
        font-size: 18px !important;
    }
    h1 { font-size: 34px !important; }
    h3 { font-size: 24px !important; }

    /* زر الفزعة (SOS) - كبير، أحمر، نابض */
    div.stButton > button[kind="primary"] {
        background-color: #D5574A;
        color: white;
        font-size: 28px !important;
        font-weight: bold;
        padding: 26px 20px;
        border-radius: 18px;
        border: none;
        width: 100%;
        animation: sanad-pulse 2s infinite;
    }
    @keyframes sanad-pulse {
        0%   { box-shadow: 0 0 0 0 rgba(213,87,74,0.55); }
        70%  { box-shadow: 0 0 0 22px rgba(213,87,74,0); }
        100% { box-shadow: 0 0 0 0 rgba(213,87,74,0); }
    }

    /* الأزرار العادية - أكبر وأوضح للمس السهل */
    div.stButton > button[kind="secondary"] {
        font-size: 19px !important;
        padding: 16px !important;
        border-radius: 14px !important;
        border: 2px solid #16403f !important;
    }

    /* حقول الإدخال - خط أكبر */
    [data-testid="stNumberInput"] input, [data-testid="stTextInput"] input {
        font-size: 20px !important;
        padding: 12px !important;
    }
    [data-testid="stSelectbox"] div[data-baseweb="select"] {
        font-size: 20px !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🛡️ نظام «سند» - تطبيق الأب")
st.markdown("لوحة تسجيل البيانات وحالات الطوارئ المباشرة.")

# ------------------------------------------------------------
# الثوابت
# ------------------------------------------------------------
father_phone = "0509036511"
default_lat = "24.549513"   # يُستخدم فقط إذا تعذّر الحصول على GPS حقيقي
default_lon = "44.377016"
DB_PATH = "sanad.db"

# ------------------------------------------------------------
# 1) قاعدة البيانات - SQLite (تحل محل session_state المؤقت)
# ------------------------------------------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT,
            reading REAL,
            true_state TEXT,
            system_class TEXT,
            alert_sent TEXT,
            processed_at TEXT,
            alert_ms REAL,
            accuracy TEXT,
            event_type TEXT DEFAULT 'قراءة سكر'
        )
    """)
    # ترحيل آمن: إضافة أعمدة الذكاء الاستباقي بدون فقدان أي بيانات قديمة
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(logs)").fetchall()}
    if "smart_level" not in existing_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN smart_level TEXT DEFAULT 'طبيعي'")
    if "smart_reason" not in existing_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN smart_reason TEXT DEFAULT ''")
    conn.commit()
    conn.close()

def insert_log(row: dict):
    row.setdefault("smart_level", row.get("system_class", ""))
    row.setdefault("smart_reason", "")
    conn = get_conn()
    conn.execute("""
        INSERT INTO logs (test_id, reading, true_state, system_class, alert_sent,
                           processed_at, alert_ms, accuracy, event_type, smart_level, smart_reason)
        VALUES (:test_id, :reading, :true_state, :system_class, :alert_sent,
                :processed_at, :alert_ms, :accuracy, :event_type, :smart_level, :smart_reason)
    """, row)
    conn.commit()
    conn.close()

def load_logs() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM logs ORDER BY id DESC", conn)
    conn.close()
    return df

def next_test_id() -> str:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    conn.close()
    return f"TEST-{count + 1:03d}"

# ------------------------------------------------------------
# 5) الذكاء الاستباقي: خط أساس شخصي + كشف اتجاه الخطر
# ------------------------------------------------------------
MIN_HISTORY_FOR_BASELINE = 5   # أقل عدد قراءات قبل ما نعتمد على الخط الشخصي
BASELINE_LOOKBACK = 15         # عدد القراءات المستخدمة بحساب المتوسط والانحراف
TREND_LOOKBACK = 4             # عدد القراءات السابقة المفحوصة للاتجاه
TREND_MIN_CHANGE = 20          # أقل فرق إجمالي (mg/dL) يعتبر اتجاه خطر حقيقي

def get_personal_baseline():
    """يرجع (المتوسط, الانحراف المعياري, عدد القراءات المستخدمة) من آخر قراءات سكر حقيقية."""
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT reading FROM logs WHERE event_type='قراءة سكر' AND reading IS NOT NULL "
        "ORDER BY id DESC LIMIT ?",
        conn, params=(BASELINE_LOOKBACK,)
    )
    conn.close()
    if len(df) < MIN_HISTORY_FOR_BASELINE:
        return None, None, len(df)
    mean = df["reading"].mean()
    std = df["reading"].std()
    if pd.isna(std) or std < 3:
        std = 5.0  # حد أدنى منطقي لتفادي نطاق ضيق جداً بقراءات شبه ثابتة
    return round(mean, 1), round(std, 1), len(df)

def get_recent_readings(n=TREND_LOOKBACK):
    """يرجع آخر n قراءات سابقة، من الأقدم إلى الأحدث."""
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT reading FROM logs WHERE event_type='قراءة سكر' AND reading IS NOT NULL "
        "ORDER BY id DESC LIMIT ?",
        conn, params=(n,)
    )
    conn.close()
    return df["reading"].tolist()[::-1]

def detect_danger_trend(readings):
    """يكشف اتجاه هبوط/صعود متتالي وملحوظ. يرجع 'down' / 'up' / None."""
    if len(readings) < 3:
        return None
    diffs = [readings[i + 1] - readings[i] for i in range(len(readings) - 1)]
    total_change = readings[-1] - readings[0]
    down_moves = sum(1 for d in diffs if d < 0)
    up_moves = sum(1 for d in diffs if d > 0)
    if down_moves >= len(diffs) - 1 and total_change <= -TREND_MIN_CHANGE:
        return "down"
    if up_moves >= len(diffs) - 1 and total_change >= TREND_MIN_CHANGE:
        return "up"
    return None

def smart_classify(value):
    """
    يرجع (fixed_class, smart_level, explanation):
    - fixed_class: انخفاض / طبيعي / ارتفاع (العتبة الثابتة كما هي)
    - smart_level: طبيعي / تنبيه استباقي / خطر مؤكد
    """
    fixed_class = classify_sugar(value)
    if fixed_class != "طبيعي":
        return fixed_class, "خطر مؤكد", f"القراءة {value} خارج الحدود الطبية الثابتة ({fixed_class})."

    reasons = []
    is_alert = False

    mean, std, n = get_personal_baseline()
    if mean is not None:
        lower, upper = mean - 1.5 * std, mean + 1.5 * std
        if value < lower or value > upper:
            is_alert = True
            reasons.append(f"خارج نطاقك الشخصي المعتاد ({round(lower)}–{round(upper)})")

    prev_readings = get_recent_readings(TREND_LOOKBACK)
    trend = detect_danger_trend(prev_readings + [value]) if prev_readings else None
    if trend == "down":
        is_alert = True
        reasons.append("اتجاه انخفاض متتالي وملحوظ بآخر القراءات")
    elif trend == "up":
        is_alert = True
        reasons.append("اتجاه ارتفاع متتالي وملحوظ بآخر القراءات")

    if is_alert:
        return fixed_class, "تنبيه استباقي", " و".join(reasons)
    return fixed_class, "طبيعي", ""

init_db()

# ------------------------------------------------------------
# 6) الرسم البياني لتطور القراءات + نطاق الأساس الشخصي
# ------------------------------------------------------------
def render_history_chart():
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT reading, processed_at, smart_level FROM logs "
        "WHERE event_type='قراءة سكر' AND reading IS NOT NULL "
        "ORDER BY id DESC LIMIT 20",
        conn
    )
    conn.close()
    if len(df) < 2:
        st.info("سجّل قراءتين على الأقل ليظهر الرسم البياني.")
        return

    df = df.iloc[::-1].reset_index(drop=True)  # من الأقدم إلى الأحدث
    mean, std, n = get_personal_baseline()

    fig, ax = plt.subplots(figsize=(9, 3.2))
    x = range(len(df))

    if mean is not None:
        lower, upper = mean - 1.5 * std, mean + 1.5 * std
        ax.axhspan(lower, upper, color="#1B5E62", alpha=0.12, label=None)
        ax.axhline(mean, color="#1B5E62", linestyle="--", linewidth=1, alpha=0.5)

    point_colors = []
    for lvl in df["smart_level"]:
        if lvl == "خطر مؤكد":
            point_colors.append("#D5574A")
        elif lvl == "تنبيه استباقي":
            point_colors.append("#D4A017")
        else:
            point_colors.append("#1B5E62")

    ax.plot(x, df["reading"], color="#163A3E", linewidth=1.5, zorder=1)
    ax.scatter(x, df["reading"], c=point_colors, s=55, zorder=2, edgecolors="white", linewidths=1)

    ax.set_ylabel("mg/dL", fontsize=10)
    ax.set_xticks(list(x))
    ax.set_xticklabels([str(i + 1) for i in x], fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()

    st.pyplot(fig)
    plt.close(fig)

    st.markdown("""
        <div style="display:flex; gap:22px; font-size:13px; margin-top:-10px;">
            <span>🟢 طبيعي</span>
            <span>🟡 تنبيه استباقي</span>
            <span>🔴 خطر مؤكد</span>
            <span style="color:#888;">▬ ▬ نطاق الأساس الشخصي المظلّل</span>
        </div>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------
# 7) تذكير الأدوية والجرعات
# ------------------------------------------------------------
def init_medications_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, dose TEXT, time_of_day TEXT, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS medication_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medication_id INTEGER, log_date TEXT, taken_at TEXT,
            reminder_sent INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def add_medication(name, dose, time_str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO medications (name, dose, time_of_day, created_at) VALUES (?, ?, ?, ?)",
        (name, dose, time_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_medications():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM medications ORDER BY time_of_day", conn)
    conn.close()
    return df

def delete_medication(med_id):
    med_id = int(med_id)
    conn = get_conn()
    conn.execute("DELETE FROM medications WHERE id = ?", (med_id,))
    conn.execute("DELETE FROM medication_logs WHERE medication_id = ?", (med_id,))
    conn.commit()
    conn.close()

def get_or_create_today_log(med_id):
    med_id = int(med_id)
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM medication_logs WHERE medication_id = ? AND log_date = ?",
        (med_id, today)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO medication_logs (medication_id, log_date, taken_at, reminder_sent) VALUES (?, ?, NULL, 0)",
            (med_id, today)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM medication_logs WHERE medication_id = ? AND log_date = ?",
            (med_id, today)
        ).fetchone()
    conn.close()
    return row  # (id, medication_id, log_date, taken_at, reminder_sent)

def mark_taken(log_id):
    log_id = int(log_id)
    conn = get_conn()
    conn.execute(
        "UPDATE medication_logs SET taken_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), log_id)
    )
    conn.commit()
    conn.close()

def mark_reminder_sent(log_id):
    log_id = int(log_id)
    conn = get_conn()
    conn.execute("UPDATE medication_logs SET reminder_sent = 1 WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()

MED_GRACE_MINUTES = 60  # مهلة السماح قبل اعتبار الجرعة متأخرة

def check_overdue_and_alert(telegram_token, telegram_chat_id, location_str):
    """يفحص كل أدوية اليوم، ولو تجاوزت موعدها + المهلة بدون تسجيل أخذ، يرسل تنبيه تلقائي مرة واحدة."""
    meds = get_medications()
    now = datetime.now()
    alerts_sent = []
    for _, med in meds.iterrows():
        log = get_or_create_today_log(med["id"])
        log_id, _, _, taken_at, reminder_sent = log
        if taken_at is not None or reminder_sent:
            continue
        try:
            sched_h, sched_m = map(int, med["time_of_day"].split(":"))
        except Exception:
            continue
        scheduled_dt = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
        overdue_minutes = (now - scheduled_dt).total_seconds() / 60
        if overdue_minutes >= MED_GRACE_MINUTES:
            msg = (
                f"💊 *تذكير فائت من تطبيق الأب* 💊\n"
                f"لم يتم تسجيل أخذ دواء «{med['name']}» ({med['dose']}) "
                f"المقرر الساعة {med['time_of_day']}.\n"
                f"📍 الموقع: {location_str}"
            )
            ok, _ = send_telegram_alert(telegram_token, telegram_chat_id, msg)
            if ok:
                mark_reminder_sent(log_id)
                alerts_sent.append(med["name"])
    return alerts_sent

init_medications_db()

# ------------------------------------------------------------
# 2) الموقع الجغرافي الحقيقي (GPS من المتصفح)
#    يتطلب تثبيت الحزمة:  pip install streamlit-js-eval
#    إذا لم تكن الحزمة مثبتة أو رفض المستخدم إذن الموقع،
#    يرجع النظام تلقائياً للإحداثيات الافتراضية بدون أي خطأ.
# ------------------------------------------------------------
def get_live_location():
    try:
        from streamlit_js_eval import get_geolocation
        loc = get_geolocation()
        if loc and "coords" in loc:
            lat = loc["coords"]["latitude"]
            lon = loc["coords"]["longitude"]
            return str(lat), str(lon), True
    except ModuleNotFoundError:
        st.sidebar.warning(
            "⚠️ لتفعيل الموقع الحقيقي: أضف السطر التالي إلى requirements.txt\n\n"
            "streamlit-js-eval"
        )
    except Exception:
        pass
    return default_lat, default_lon, False

live_lat, live_lon, is_live_gps = get_live_location()
location_str = f"https://maps.google.com/?q={live_lat},{live_lon}"

# ------------------------------------------------------------
# 4) تيليجرام - إرسال تلقائي حقيقي (بدون أي ضغطة من المستلم)
# ------------------------------------------------------------
def send_telegram_alert(bot_token: str, chat_id: str, message: str):
    """يرسل رسالة فوراً عبر بوت تيليجرام. يرجع (نجح؟, تفاصيل الخطأ إن وجد)."""
    if not bot_token or not chat_id:
        return False, "التوكن أو معرف المحادثة غير مُدخل"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=8,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, None
        return False, resp.json().get("description", f"HTTP {resp.status_code}")
    except requests.exceptions.RequestException as e:
        return False, str(e)

# ------------------------------------------------------------
# الشريط الجانبي
# ------------------------------------------------------------
st.sidebar.subheader("⚙️ إعدادات الطوارئ والاتصال")
target_phone = st.sidebar.text_input("رقم طوارئ الابن (واتساب - احتياطي يدوي)", value="966500000000")

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 بوت تيليجرام (إرسال تلقائي)")
with st.sidebar.expander("ℹ️ كيف أحصل على التوكن ومعرف المحادثة؟"):
    st.markdown("""
    **1. أنشئ البوت (مرة واحدة فقط):**
    - افتح تيليجرام وابحث عن `BotFather`
    - أرسل له `/newbot` واتبع التعليمات
    - راح يعطيك **Token** — انسخه

    **2. احصل على معرف محادثة الابن (Chat ID):**
    - الابن يفتح محادثة مع البوت الجديد ويرسل له أي رسالة (مثلاً "مرحبا")
    - افتح هذا الرابط بالمتصفح (استبدل TOKEN بتوكنك):
      `https://api.telegram.org/botTOKEN/getUpdates`
    - بتلاقي `"chat":{"id": 123456789 ...}` — هذا الرقم هو الـ Chat ID
    """)
try:
    telegram_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
except Exception:
    telegram_token = ""
    telegram_chat_id = ""

if telegram_token and telegram_chat_id:
    st.sidebar.success("🔒 توكن البوت ومعرف المحادثة محفوظين بشكل دائم (Secrets)")
    with st.sidebar.expander("تعديل القيم المحفوظة؟"):
        st.caption("عدّلها من إعدادات Secrets في لوحة تحكم Streamlit Cloud مباشرة (أدق من الكتابة هنا في كل مرة).")
else:
    st.sidebar.warning("⚠️ لم يتم حفظ التوكن بعد بشكل دائم — أدخله الآن، وراجع الشرح تحت لحفظه نهائياً.")
    telegram_token = st.sidebar.text_input("توكن البوت (Bot Token) - مؤقت", type="password", value=telegram_token)
    telegram_chat_id = st.sidebar.text_input("معرف محادثة الابن (Chat ID) - مؤقت", value=telegram_chat_id)
    with st.sidebar.expander("💾 كيف أحفظهم بشكل دائم ولا يروحون بعد التحديث؟"):
        st.markdown("""
        **إذا تطبيقك على Streamlit Cloud:**
        1. افتح [share.streamlit.io](https://share.streamlit.io) ولقِ تطبيقك
        2. اضغط القائمة (⋮) بجنب التطبيق ← **Settings** ← **Secrets**
        3. الصق هذا بالضبط (بقيمك الحقيقية):
        ```
        TELEGRAM_BOT_TOKEN = "8879255452:AAETJet4SR8UdIQdfyh7oD7unDx25jPaO74"
        TELEGRAM_CHAT_ID = "7026633810"
        ```
        4. احفظ (Save) — التطبيق يعيد التشغيل تلقائياً ويصير يقرأهم دايماً من نفسه

        **إذا تشغّله محلياً على جهازك:**
        أنشئ ملف `.streamlit/secrets.toml` بنفس مجلد المشروع وحط فيه نفس السطرين أعلاه.
        """)

st.sidebar.markdown("---")
st.sidebar.info(f"📱 جوال الأب المسجل: {father_phone}")
st.sidebar.error("🚨 رقم الإسعاف السعودي المعتمد: 997")
st.sidebar.markdown("---")
if is_live_gps:
    st.sidebar.success(f"📍 الموقع الحالي (GPS حقيقي): {live_lat}, {live_lon}")
else:
    st.sidebar.warning(f"📍 موقع افتراضي (تجريبي): {live_lat}, {live_lon}")

# فحص صامت لأي دواء فات موعده دون تسجيل + إرسال تنبيه تلقائي عند اللزوم
_overdue_alerts = check_overdue_and_alert(telegram_token, telegram_chat_id, location_str)
if _overdue_alerts:
    st.warning("⏰ تم إرسال تنبيه تلقائي بخصوص تأخّر أخذ: " + "، ".join(_overdue_alerts))

# ------------------------------------------------------------
# دالة مساعدة: بناء روابط التنبيه (واتساب + اتصال)
# ------------------------------------------------------------
def build_alert_links(message: str):
    encoded = urllib.parse.quote(message)
    whatsapp_url = f"https://wa.me/{target_phone}?text={encoded}"
    return whatsapp_url

def render_alert_box(title: str, message: str, box_color="#ff4d4d", bg_color="#fff5f5"):
    # 1) إرسال تلقائي فوري عبر تيليجرام - بدون أي تدخل بشري
    tg_ok, tg_error = send_telegram_alert(telegram_token, telegram_chat_id, message)

    whatsapp_url = build_alert_links(message)
    st.markdown(f"""
        <div style="background-color:{bg_color}; padding:20px; border-radius:12px; border:2px solid {box_color}; text-align:center; margin-bottom:15px;">
            <h3 style="color:#cc0000; margin-top:0;">{title}</h3>
            <div style="display: flex; justify-content: center; gap: 15px; flex-wrap: wrap;">
                <a href="{whatsapp_url}" target="_blank" style="background-color:#25D366; color:white; padding:12px 20px; text-decoration:none; font-size:16px; font-weight:bold; border-radius:8px; display:inline-block;">
                    💬 إرسال يدوي عبر الواتساب (احتياطي)
                </a>
                <a href="tel:997" style="background-color:#cc0000; color:white; padding:12px 20px; text-decoration:none; font-size:16px; font-weight:bold; border-radius:8px; display:inline-block;">
                    🚑 الاتصال الفوري بالإسعاف (997)
                </a>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if tg_ok:
        st.success("✅ تم إرسال التنبيه تلقائياً عبر تيليجرام إلى الابن (بدون أي تدخل يدوي).")
    else:
        st.warning(f"⚠️ لم يُرسل التنبيه التلقائي عبر تيليجرام: {tg_error}\n\nيمكنك استخدام رابط الواتساب اليدوي بالأعلى كبديل مؤقت.")

# ------------------------------------------------------------
# 3) زر الفزعة الطارئة (SOS) - فوري ولا يحتاج قراءة سكر
# ------------------------------------------------------------
# ------------------------------------------------------------
# بطاقة "آخر حالة" - ملخص مبسّط وواضح لكبار السن والعائلة
# ------------------------------------------------------------
_recent_logs = load_logs()
if len(_recent_logs) > 0:
    _last = _recent_logs.iloc[0]
    _last_level = _last["smart_level"] if pd.notna(_last["smart_level"]) else _last["system_class"]
    if _last_level == "طبيعي":
        _card_color, _card_bg, _card_icon = "#1B5E62", "#E7F0EE", "✅"
        _card_text = "الحالة طبيعية"
    elif _last_level == "فزعة يدوية":
        _card_color, _card_bg, _card_icon = "#D5574A", "#FBEAE7", "🆘"
        _card_text = "تم إرسال نداء استغاثة"
    elif _last_level == "تنبيه استباقي":
        _card_color, _card_bg, _card_icon = "#B8860B", "#FFF8E1", "🧠"
        _reason = _last["smart_reason"] if pd.notna(_last["smart_reason"]) else ""
        _card_text = f"تنبيه استباقي ذكي — {_reason}" if _reason else "تنبيه استباقي ذكي"
    else:
        _card_color, _card_bg, _card_icon = "#D5574A", "#FBEAE7", "⚠️"
        _card_text = f"تنبيه: {_last_level}"
    st.markdown(f"""
        <div style="background-color:{_card_bg}; border:2px solid {_card_color}; border-radius:16px;
                    padding:18px 24px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-size:22px; font-weight:bold; color:{_card_color};">{_card_icon} آخر حالة: {_card_text}</span><br>
                <span style="font-size:15px; color:#555;">وقت آخر تسجيل: {_last['processed_at']}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
else:
    st.info("لا توجد قراءات مسجلة بعد.")

st.markdown("### 📈 سجل القراءات وتطورها")
render_history_chart()

st.markdown("### 🆘 الفزعة الطارئة")
sos_col1, sos_col2 = st.columns([1, 3])
with sos_col1:
    sos_clicked = st.button("🆘 نداء استغاثة فورية", type="primary", use_container_width=True)
with sos_col2:
    st.caption("اضغط هذا الزر في أي وقت لإرسال نداء طوارئ فوري بدون الحاجة لتسجيل قراءة سكر.")

if sos_clicked:
    sos_row = {
        "test_id": next_test_id(),
        "reading": None,
        "true_state": "-",
        "system_class": "فزعة يدوية",
        "alert_sent": "نعم",
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_ms": None,
        "accuracy": "-",
        "event_type": "زر SOS",
    }
    insert_log(sos_row)
    sos_message = f"🆘 *نداء استغاثة فورية من تطبيق الأب* 🆘\nتم الضغط على زر الفزعة الطارئة.\n📍 الموقع: {location_str}"
    render_alert_box("🆘 تم إرسال نداء استغاثة فورية!", sos_message)

st.markdown("---")

# ------------------------------------------------------------
# تسجيل قراءة السكر يدوياً
# ------------------------------------------------------------
def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

st.markdown("### 🩸 تسجيل قراءة سكر الدم")

_baseline_mean, _baseline_std, _baseline_n = get_personal_baseline()
if _baseline_mean is not None:
    _lo, _hi = round(_baseline_mean - 1.5*_baseline_std), round(_baseline_mean + 1.5*_baseline_std)
    st.caption(f"🧠 نطاقك الشخصي المعتاد (بناءً على آخر {_baseline_n} قراءة): {_lo} – {_hi} mg/dL")
else:
    st.caption(f"🧠 التعلم الذكي يحتاج {MIN_HISTORY_FOR_BASELINE} قراءات على الأقل ليبدأ بتحديد نطاقك الشخصي (المسجل حالياً: {_baseline_n}).")

manual_val = st.number_input("قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=120)
true_state_manual = st.selectbox("الحالة الفعلية", ["انخفاض", "طبيعي", "ارتفاع"])

if st.button("معالجة وتسجيل القراءة فوراً", use_container_width=True):
    start_time = datetime.now()
    fixed_class, smart_level, smart_reason = smart_classify(manual_val)
    alert_sent = "نعم" if smart_level != "طبيعي" else "لا"
    elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

    new_row = {
        "test_id": next_test_id(),
        "reading": manual_val,
        "true_state": true_state_manual,
        "system_class": fixed_class,
        "alert_sent": alert_sent,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_ms": round(elapsed_ms, 2),
        "accuracy": "صحيح" if fixed_class == true_state_manual else "خاطئ",
        "event_type": "قراءة سكر",
        "smart_level": smart_level,
        "smart_reason": smart_reason,
    }
    insert_log(new_row)

    if smart_level == "خطر مؤكد":
        auto_alert_text = (
            f"🚨 *تنبيه طوارئ من تطبيق الأب* 🚨\n"
            f"القراءة المسجلة خطيرة: {manual_val} mg/dL ({fixed_class}).\n"
            f"📍 الموقع: {location_str}"
        )
        render_alert_box(
            f"🚨 تحذير خطير: القراءة ({fixed_class}: {manual_val}) غير طبيعية!",
            auto_alert_text,
        )
    elif smart_level == "تنبيه استباقي":
        auto_alert_text = (
            f"⚠️ *تنبيه استباقي ذكي من تطبيق الأب* ⚠️\n"
            f"القراءة {manual_val} mg/dL ضمن الحدود الثابتة، لكن النظام لاحظ نمطاً يستدعي الانتباه:\n"
            f"السبب: {smart_reason}\n"
            f"📍 الموقع: {location_str}"
        )
        render_alert_box(
            f"⚠️ تنبيه استباقي: {smart_reason}",
            auto_alert_text,
            box_color="#d4a017",
            bg_color="#fffbea",
        )
    else:
        st.success("✅ تمت معالجة وتسجيل القراءة بنجاح (الحالة طبيعية، ولا يوجد نمط يستدعي القلق).")

st.markdown("---")

# ------------------------------------------------------------
# واجهة تذكير الأدوية والجرعات
# ------------------------------------------------------------
st.markdown("### 💊 تذكير الأدوية والجرعات")

with st.expander("➕ إضافة دواء جديد"):
    with st.form("add_med_form", clear_on_submit=True):
        med_name = st.text_input("اسم الدواء")
        med_dose = st.text_input("الجرعة (مثال: حبة واحدة)")
        med_time = st.time_input("موعد الجرعة اليومي")
        submitted = st.form_submit_button("إضافة الدواء")
        if submitted:
            if med_name.strip():
                add_medication(med_name.strip(), med_dose.strip(), med_time.strftime("%H:%M"))
                st.success(f"تمت إضافة دواء «{med_name}» بنجاح.")
                st.rerun()
            else:
                st.error("الرجاء إدخال اسم الدواء.")

meds_df = get_medications()
if len(meds_df) == 0:
    st.caption("لا توجد أدوية مسجلة بعد. أضف أول دواء من الأعلى.")
else:
    st.markdown(f"**أدوية اليوم ({datetime.now().strftime('%Y-%m-%d')}):**")
    for _, med in meds_df.iterrows():
        log = get_or_create_today_log(med["id"])
        log_id, _, _, taken_at, reminder_sent = log
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            status_icon = "✅" if taken_at else ("⏰" if reminder_sent else "⏳")
            label = f"{status_icon} **{med['name']}** ({med['dose']}) — الساعة {med['time_of_day']}"
            if taken_at:
                label += f"  \n*تم الأخذ الساعة {taken_at.split(' ')[1]}*"
            st.markdown(label)
        with col2:
            if not taken_at:
                if st.button("تم أخذه", key=f"take_{med['id']}"):
                    mark_taken(log_id)
                    st.rerun()
        with col3:
            if st.button("حذف", key=f"del_{med['id']}"):
                delete_medication(med["id"])
                st.rerun()

# ------------------------------------------------------------
# السجل التفصيلي (مطوي افتراضياً - للاطلاع التقني فقط)
# ------------------------------------------------------------
with st.expander("📋 عرض السجل التفصيلي الكامل"):
    logs_df = load_logs()
    st.dataframe(logs_df, use_container_width=True)

    if len(logs_df) > 0:
        csv = logs_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ تنزيل السجل كملف CSV", data=csv, file_name="sanad_logs.csv", mime="text/csv")
