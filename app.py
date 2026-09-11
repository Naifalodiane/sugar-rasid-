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

st.set_page_config(page_title="سند - Sanad", layout="wide")

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

st.title("🛡️ نظام «سند»")
st.markdown("لوحة تسجيل البيانات وحالات الطوارئ المباشرة.")

# ------------------------------------------------------------
# بوابة اختيار الدور: أب (تحكم كامل) أو أحد أفراد العائلة (عرض فقط)
# كلاهما يقرأ من نفس قاعدة البيانات (نفس التطبيق، نفس الخادم)
# ------------------------------------------------------------
if "role" not in st.session_state:
    st.session_state.role = None

if st.session_state.role is None:
    st.markdown("## 👋 أهلاً بك في سند")
    st.markdown("اختر كيف تستخدم التطبيق الآن:")
    rc1, rc2 = st.columns(2)
    with rc1:
        if st.button("👴 أنا الأب", use_container_width=True, type="primary"):
            st.session_state.role = "father"
            st.rerun()
        st.caption("تسجيل القراءات، إدارة الأدوية، زر الاستغاثة، وإعدادات التنبيهات.")
    with rc2:
        if st.button("👨‍👩‍👧 أنا أحد أفراد العائلة", use_container_width=True):
            st.session_state.role = "family"
            st.rerun()
        st.caption("متابعة الحالة والتقارير فقط، بدون إمكانية التعديل.")
    st.stop()

role = st.session_state.role
_role_label = "تطبيق الأب" if role == "father" else "متابعة العائلة"
st.caption(f"الوضع الحالي: **{_role_label}**")
if st.button("🔄 تبديل الدور"):
    st.session_state.role = None
    st.rerun()

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
    if "is_demo" not in existing_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN is_demo INTEGER DEFAULT 0")
    if "escalated" not in existing_cols:
        conn.execute("ALTER TABLE logs ADD COLUMN escalated INTEGER DEFAULT 0")
    conn.commit()
    conn.close()

def insert_log(row: dict):
    row.setdefault("smart_level", row.get("system_class", ""))
    row.setdefault("smart_reason", "")
    row.setdefault("is_demo", 0)
    conn = get_conn()
    conn.execute("""
        INSERT INTO logs (test_id, reading, true_state, system_class, alert_sent,
                           processed_at, alert_ms, accuracy, event_type, smart_level, smart_reason, is_demo)
        VALUES (:test_id, :reading, :true_state, :system_class, :alert_sent,
                :processed_at, :alert_ms, :accuracy, :event_type, :smart_level, :smart_reason, :is_demo)
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

def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

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
    # ترحيل آمن: علامة البيانات التجريبية
    med_cols = {row[1] for row in conn.execute("PRAGMA table_info(medications)").fetchall()}
    if "is_demo" not in med_cols:
        conn.execute("ALTER TABLE medications ADD COLUMN is_demo INTEGER DEFAULT 0")
    # ترحيل آمن: دعم الموعد المرتبط بالصلاة بدل الساعة الثابتة
    if "schedule_type" not in med_cols:
        conn.execute("ALTER TABLE medications ADD COLUMN schedule_type TEXT DEFAULT 'clock'")
    if "prayer_name" not in med_cols:
        conn.execute("ALTER TABLE medications ADD COLUMN prayer_name TEXT DEFAULT ''")
    if "prayer_offset" not in med_cols:
        conn.execute("ALTER TABLE medications ADD COLUMN prayer_offset INTEGER DEFAULT 0")
    medlog_cols = {row[1] for row in conn.execute("PRAGMA table_info(medication_logs)").fetchall()}
    if "is_demo" not in medlog_cols:
        conn.execute("ALTER TABLE medication_logs ADD COLUMN is_demo INTEGER DEFAULT 0")
    conn.commit()
    conn.close()

def add_medication(name, dose, time_str, is_demo=0, schedule_type="clock", prayer_name="", prayer_offset=0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO medications (name, dose, time_of_day, created_at, is_demo, schedule_type, prayer_name, prayer_offset) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, dose, time_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), is_demo, schedule_type, prayer_name, prayer_offset)
    )
    conn.commit()
    conn.close()

# ------------------------------------------------------------
# مواقيت الصلاة (Aladhan API) - لحساب موعد الأدوية المرتبطة بالصلاة
# ------------------------------------------------------------
PRAYER_NAMES_AR = ["الفجر", "الظهر", "العصر", "المغرب", "العشاء"]
_ALADHAN_KEYS = {"الفجر": "Fajr", "الظهر": "Dhuhr", "العصر": "Asr", "المغرب": "Maghrib", "العشاء": "Isha"}

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_prayer_times_cached(lat, lon, date_str):
    """يجلب مواقيت الصلاة الخمسة لليوم الحالي عبر Aladhan API (مجاني، بدون مفتاح).
    مخزّن مؤقتاً 6 ساعات لتقليل الطلبات. يرجع None لو تعذّر الاتصال."""
    try:
        url = f"https://api.aladhan.com/v1/timings/{date_str}"
        resp = requests.get(url, params={"latitude": lat, "longitude": lon, "method": 4}, timeout=8)
        if resp.status_code == 200:
            timings = resp.json()["data"]["timings"]
            return {ar: timings[en][:5] for ar, en in _ALADHAN_KEYS.items()}
    except Exception:
        pass
    return None

def get_prayer_times(lat, lon):
    return get_prayer_times_cached(lat, lon, datetime.now().strftime("%d-%m-%Y"))

def add_minutes_to_time_str(time_str, minutes):
    """يضيف عدد دقائق لوقت بصيغة HH:MM ويرجع نفس الصيغة."""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + int(minutes)
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"

def get_effective_time_str(med, prayer_times):
    """يرجع وقت الجرعة الفعلي لليوم (HH:MM) - مباشرة لو موعد ثابت،
    أو محسوب من مواقيت الصلاة + الإزاحة لو مرتبط بصلاة."""
    sched_type = med.get("schedule_type", "clock") or "clock"
    if sched_type == "prayer" and prayer_times:
        base = prayer_times.get(med.get("prayer_name", ""))
        if base:
            return add_minutes_to_time_str(base, med.get("prayer_offset", 0) or 0)
    return med["time_of_day"]

def format_medication_schedule(med, prayer_times):
    """نص وصفي واضح لموعد الدواء، يُعرض بالواجهة."""
    sched_type = med.get("schedule_type", "clock") or "clock"
    if sched_type == "prayer":
        offset = int(med.get("prayer_offset", 0) or 0)
        prayer = med.get("prayer_name", "")
        offset_txt = f"بعد {offset} دقيقة من" if offset > 0 else ("قبل " + str(abs(offset)) + " دقيقة من" if offset < 0 else "عند")
        eff = get_effective_time_str(med, prayer_times)
        suffix = f" (تقريباً {eff})" if eff else ""
        return f"{offset_txt} صلاة {prayer}{suffix}"
    return f"الساعة {med['time_of_day']}"

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
    """يرجع دائماً 5 قيم بالضبط بغض النظر عن أي أعمدة إضافية بالجدول مستقبلاً."""
    med_id = int(med_id)
    today = datetime.now().strftime("%Y-%m-%d")
    cols = "id, medication_id, log_date, taken_at, reminder_sent"
    conn = get_conn()
    row = conn.execute(
        f"SELECT {cols} FROM medication_logs WHERE medication_id = ? AND log_date = ?",
        (med_id, today)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO medication_logs (medication_id, log_date, taken_at, reminder_sent) VALUES (?, ?, NULL, 0)",
            (med_id, today)
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {cols} FROM medication_logs WHERE medication_id = ? AND log_date = ?",
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

def check_overdue_and_alert(telegram_token, telegram_chat_id, location_str, prayer_times=None):
    """يفحص كل أدوية اليوم، ولو تجاوزت موعدها الفعلي (ثابت أو مرتبط بصلاة) + المهلة
    بدون تسجيل أخذ، يرسل تنبيه تلقائي مرة واحدة.
    يتجاهل الأدوية التجريبية تماماً (حماية إضافية من إرسال تنبيهات وهمية)."""
    meds = get_medications()
    now = datetime.now()
    alerts_sent = []
    for _, med in meds.iterrows():
        if int(med.get("is_demo", 0) or 0) == 1:
            continue
        log = get_or_create_today_log(med["id"])
        log_id, _, _, taken_at, reminder_sent = log
        if taken_at is not None or reminder_sent:
            continue
        effective_time = get_effective_time_str(med, prayer_times)
        try:
            sched_h, sched_m = map(int, effective_time.split(":"))
        except Exception:
            continue
        scheduled_dt = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
        overdue_minutes = (now - scheduled_dt).total_seconds() / 60
        if overdue_minutes >= MED_GRACE_MINUTES:
            schedule_desc = format_medication_schedule(med, prayer_times)
            msg = (
                f"💊 *تذكير فائت من تطبيق الأب* 💊\n"
                f"لم يتم تسجيل أخذ دواء «{med['name']}» ({med['dose']}) "
                f"المقرر {schedule_desc}.\n"
                f"📍 الموقع: {location_str}"
            )
            ok, _ = send_telegram_alert(telegram_token, telegram_chat_id, msg)
            if ok:
                mark_reminder_sent(log_id)
                alerts_sent.append(med["name"])
    return alerts_sent

# ------------------------------------------------------------
# تصعيد الجار الموثوق: لو مرّت مهلة معينة على نداء SOS أو خطر
# مؤكد بدون أي رد/إجراء من العائلة، يُرسل تنبيه إضافي لجار موثوق
# ------------------------------------------------------------
def check_neighbor_escalation(telegram_token, neighbor_chat_id, grace_minutes, location_str):
    """يفحص آخر حدث طارئ (SOS أو خطر مؤكد) غير مُصعَّد بعد؛ لو تجاوز مهلة الانتظار
    يرسل تنبيه لجار موثوق مرة واحدة فقط لكل حدث. يتجاهل البيانات التجريبية تماماً."""
    if not neighbor_chat_id:
        return False
    conn = get_conn()
    row = conn.execute("""
        SELECT id, event_type, reading, smart_level, processed_at FROM logs
        WHERE is_demo = 0 AND escalated = 0
          AND (event_type = 'زر SOS' OR smart_level = 'خطر مؤكد')
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    if row is None:
        return False
    log_id, event_type, reading, smart_level, processed_at = row
    try:
        event_dt = datetime.strptime(processed_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    elapsed_minutes = (datetime.now() - event_dt).total_seconds() / 60
    if elapsed_minutes < grace_minutes:
        return False
    reason = "نداء استغاثة (SOS)" if event_type == "زر SOS" else f"قراءة سكر خطيرة ({reading:g} mg/dL)"
    msg = (
        f"🏠 *تصعيد طارئ — يحتاج مساعدتك* 🏠\n"
        f"حالة طوارئ ({reason}) قبل {int(elapsed_minutes)} دقيقة تقريباً، ولم يتم الرد من العائلة بعد.\n"
        f"إذا كنت قريباً، الرجاء الاطمئنان على الجار.\n"
        f"📍 الموقع: {location_str}"
    )
    ok, _ = send_telegram_alert(telegram_token, neighbor_chat_id, msg)
    if ok:
        conn = get_conn()
        conn.execute("UPDATE logs SET escalated = 1 WHERE id = ?", (log_id,))
        conn.commit()
        conn.close()
    return ok

init_medications_db()

# ------------------------------------------------------------
# 8) إعدادات عامة (key-value) - لتخزين اسم المريض وغيره بشكل دائم
# ------------------------------------------------------------
def init_settings_db():
    conn = get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
    conn.close()

init_settings_db()

# ------------------------------------------------------------
# 9) وضع العرض التجريبي (Demo Mode)
#    يعبّي بيانات واقعية بالماضي فقط لعرض الرسم البياني والتقرير
#    فوراً أمام اللجنة - بدون إرسال أي تنبيهات تيليجرام حقيقية،
#    لأنه يكتب مباشرة بقاعدة البيانات (نفس آلية insert_log العادية)
#    ولا يمر إطلاقاً على دوال الإرسال.
# ------------------------------------------------------------
def has_demo_data():
    conn = get_conn()
    n1 = conn.execute("SELECT COUNT(*) FROM logs WHERE is_demo = 1").fetchone()[0]
    conn.close()
    return n1 > 0

def generate_demo_data():
    """يبني تاريخاً واقعياً لآخر 12 يوماً: قراءات متنوعة، نداء SOS واحد، والتزام أدوية جزئي.
    كل القراءات بتواريخ ماضية (اليوم الحالي يبقى فاضياً) عشان ما يتعارض مع فحص
    التذكير الفوري، وكل الإدراج مباشر بقاعدة البيانات بدون استدعاء أي دالة إرسال."""
    now = datetime.now()

    # -------- 12 قراءة سكر موزعة على آخر 12 يوماً (نمط واقعي فيه تدرج وخطر) --------
    demo_readings = [
        (12, 119, "طبيعي", ""),
        (11, 122, "طبيعي", ""),
        (10, 117, "طبيعي", ""),
        (9,  130, "طبيعي", ""),
        (8,  115, "طبيعي", ""),
        (7,  98,  "تنبيه استباقي", "خارج نطاقك الشخصي المعتاد و اتجاه انخفاض ملحوظ بآخر القراءات"),
        (6,  88,  "تنبيه استباقي", "اتجاه انخفاض متتالي وملحوظ بآخر القراءات"),
        (5,  210, "خطر مؤكد", "القراءة 210 خارج الحدود الطبية الثابتة (ارتفاع)."),
        (4,  128, "طبيعي", ""),
        (3,  121, "طبيعي", ""),
        (2,  60,  "خطر مؤكد", "القراءة 60 خارج الحدود الطبية الثابتة (انخفاض)."),
        (1,  118, "طبيعي", ""),
    ]
    for days_ago, reading, level, reason in demo_readings:
        dt = now - timedelta(days=days_ago, hours=int(now.hour * 0.3))
        fixed_class = "طبيعي" if level == "طبيعي" else ("ارتفاع" if reading > 180 else "انخفاض")
        insert_log({
            "test_id": next_test_id(),
            "reading": reading,
            "true_state": fixed_class,
            "system_class": fixed_class,
            "alert_sent": "نعم" if level != "طبيعي" else "لا",
            "processed_at": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "alert_ms": 45.0,
            "accuracy": "صحيح",
            "event_type": "قراءة سكر",
            "smart_level": level,
            "smart_reason": reason,
            "is_demo": 1,
        })

    # -------- نداء استغاثة واحد قبل 5 أيام --------
    insert_log({
        "test_id": next_test_id(), "reading": None, "true_state": "-",
        "system_class": "فزعة يدوية", "alert_sent": "نعم",
        "processed_at": (now - timedelta(days=5, hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "alert_ms": None, "accuracy": "-", "event_type": "زر SOS",
        "smart_level": "فزعة يدوية", "smart_reason": "", "is_demo": 1,
    })

    # -------- دواءان تجريبيان بالتزام جزئي واقعي لآخر 10 أيام --------
    demo_meds = [("دواء السكر (تجريبي)", "حبة واحدة", "08:00"), ("دواء الضغط (تجريبي)", "نصف حبة", "20:00")]
    conn = get_conn()
    for name, dose, time_str in demo_meds:
        conn.execute(
            "INSERT INTO medications (name, dose, time_of_day, created_at, is_demo) VALUES (?, ?, ?, ?, 1)",
            (name, dose, time_str, now.strftime("%Y-%m-%d %H:%M:%S"))
        )
        med_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for days_ago in range(10, 0, -1):  # آخر 10 أيام، اليوم الحالي غير مشمول
            log_date = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            taken = days_ago % 3 != 0  # حوالي 70% التزام
            taken_at = (now - timedelta(days=days_ago, hours=-1)).strftime("%Y-%m-%d %H:%M:%S") if taken else None
            conn.execute(
                "INSERT INTO medication_logs (medication_id, log_date, taken_at, reminder_sent, is_demo) VALUES (?, ?, ?, 0, 1)",
                (med_id, log_date, taken_at)
            )
        # سجل اليوم الحالي: نضعه "مأخوذ" مسبقاً حتى لا يفعّل فحص التذكير الفوري تنبيهاً حقيقياً
        today_str = now.strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO medication_logs (medication_id, log_date, taken_at, reminder_sent, is_demo) VALUES (?, ?, ?, 0, 1)",
            (med_id, today_str, now.strftime("%Y-%m-%d %H:%M:%S"))
        )
    conn.commit()
    conn.close()

def clear_demo_data():
    """يحذف كل البيانات التجريبية فقط، ولا يمس أي بيانات حقيقية أدخلها المستخدم."""
    conn = get_conn()
    conn.execute("DELETE FROM logs WHERE is_demo = 1")
    conn.execute("DELETE FROM medication_logs WHERE is_demo = 1")
    conn.execute("DELETE FROM medications WHERE is_demo = 1")
    conn.commit()
    conn.close()

# ------------------------------------------------------------
# 9) تجميع بيانات التقرير الصحي الأسبوعي
# ------------------------------------------------------------
def get_weekly_report_data(days=7):
    """يجمع كل بيانات آخر N يوم من قاعدة البيانات في قاموس واحد جاهز للتقرير."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()

    readings_df = pd.read_sql_query(
        "SELECT reading, processed_at, smart_level, smart_reason FROM logs "
        "WHERE event_type='قراءة سكر' AND reading IS NOT NULL AND processed_at >= ? "
        "ORDER BY processed_at ASC",
        conn, params=(since,)
    )
    sos_df = pd.read_sql_query(
        "SELECT processed_at FROM logs WHERE event_type='زر SOS' AND processed_at >= ? "
        "ORDER BY processed_at ASC",
        conn, params=(since,)
    )
    conn.close()

    counts = {
        "طبيعي": int((readings_df["smart_level"] == "طبيعي").sum()),
        "تنبيه استباقي": int((readings_df["smart_level"] == "تنبيه استباقي").sum()),
        "خطر مؤكد": int((readings_df["smart_level"] == "خطر مؤكد").sum()),
    }

    incidents = []
    flagged = readings_df[readings_df["smart_level"] != "طبيعي"]
    for _, row in flagged.iterrows():
        incidents.append({
            "date": row["processed_at"],
            "reading": row["reading"],
            "level": row["smart_level"],
            "reason": row["smart_reason"] or "",
        })

    mean, std, n = get_personal_baseline()

    # التزام الأدوية خلال نفس الفترة
    meds = get_medications()
    med_adherence = []
    conn = get_conn()
    for _, med in meds.iterrows():
        med_id = int(med["id"])
        logs = pd.read_sql_query(
            "SELECT log_date, taken_at FROM medication_logs WHERE medication_id = ? AND log_date >= ?",
            conn, params=(med_id, since[:10])
        )
        scheduled_days = max(len(logs), 1)
        taken_days = int(logs["taken_at"].notna().sum())
        med_adherence.append({
            "name": med["name"], "dose": med["dose"], "time": med["time_of_day"],
            "taken": taken_days, "scheduled": scheduled_days,
            "pct": round(100 * taken_days / scheduled_days) if scheduled_days else 0,
        })
    conn.close()

    return {
        "period_days": days,
        "readings": readings_df,
        "counts": counts,
        "total_readings": len(readings_df),
        "incidents": incidents,
        "sos_count": len(sos_df),
        "baseline_mean": mean,
        "baseline_std": std,
        "medications": med_adherence,
    }

# ------------------------------------------------------------
# 10) توليد تقرير PDF صحي أسبوعي (عربي، بخط مرفق مع الكود)
# ------------------------------------------------------------
import os
from datetime import datetime as _dt

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_REGULAR = os.path.join(FONT_DIR, "FreeSerif.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "FreeSerifBold.ttf")

def _pdf_fonts_available():
    return os.path.exists(FONT_REGULAR) and os.path.exists(FONT_BOLD)

def generate_weekly_pdf_report(patient_name: str, report: dict) -> str:
    """يبني تقرير PDF من صفحة أو صفحتين، ويرجع مسار الملف الناتج.
    يستخدم arabic_reshaper + python-bidi لتشكيل النص العربي (بدل raqm) لأنها
    مكتبات بايثون خالصة بدون اعتماد على مكونات نظام قد لا تتوفر على كل سيرفر."""
    from PIL import Image, ImageDraw, ImageFont
    import img2pdf
    import arabic_reshaper
    from bidi.algorithm import get_display

    DPI = 200
    PAGE_W, PAGE_H = int(8.27 * DPI), int(11.69 * DPI)
    MARGIN = 130
    RIGHT = PAGE_W - MARGIN
    LEFT = MARGIN
    CONTENT_W = RIGHT - LEFT

    NAVY = (22, 58, 62); TEAL = (27, 94, 98); CORAL = (213, 87, 68)
    SAGE = (122, 158, 138); MUTED = (105, 113, 112); DARK = (36, 40, 40)
    CREAM = (250, 247, 240); CARD = (255, 255, 255); BORDER = (221, 227, 224)

    _font_cache = {}
    def font(path, size):
        key = (path, size)
        if key not in _font_cache:
            _font_cache[key] = ImageFont.truetype(path, size)  # طبقة عرض أساسية، بدون raqm
        return _font_cache[key]

    def shape(text):
        """يحوّل النص العربي المنطقي إلى شكل بصري جاهز للرسم مباشرة بدون raqm."""
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)

    def rtext(draw, xy, text, f, fill, anchor="ra"):
        """يرسم نصاً عربياً/مختلطاً بشكل صحيح بصرياً (تشكيل + إعادة ترتيب)."""
        draw.text(xy, shape(text), font=f, fill=fill, anchor=anchor)

    def rwrap(draw, text, f, max_w):
        """يلف النص على أسطر بالاعتماد على القياس بعد التشكيل (العرض الفعلي)."""
        words = str(text).split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip() if cur else w
            if draw.textlength(shape(trial), font=f) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur); cur = w
        if cur: lines.append(cur)
        return lines

    def draw_para(draw, text, f, top, right, max_w, fill=DARK, lh=None, align="right"):
        lh = lh or f.size * 1.6
        y = top
        for line in rwrap(draw, text, f, max_w):
            if align == "right":
                rtext(draw, (right, y), line, f, fill, anchor="ra")
            else:
                rtext(draw, (right - max_w/2, y), line, f, fill, anchor="ma")
            y += lh
        return y

    pages = []

    # ---------------- الصفحة الأولى ----------------
    img = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, PAGE_W, 12], fill=TEAL)

    y = 90
    rtext(d, (RIGHT, y), "التقرير الصحي الأسبوعي", font(FONT_BOLD, 34), NAVY)
    y += 55
    rtext(d, (RIGHT, y), "نظام سند — SANAD", font(FONT_REGULAR, 16), TEAL)
    y += 60
    d.line([(LEFT, y), (RIGHT, y)], fill=BORDER, width=2)
    y += 35

    period_start = (_dt.now() - timedelta(days=report["period_days"])).strftime("%Y-%m-%d")
    period_end = _dt.now().strftime("%Y-%m-%d")
    rtext(d, (RIGHT, y), f"اسم المريض: {patient_name}", font(FONT_BOLD, 20), DARK)
    y += 34
    rtext(d, (RIGHT, y), f"الفترة: من {period_start} إلى {period_end}", font(FONT_REGULAR, 16), MUTED)
    y += 34
    rtext(d, (RIGHT, y), f"تاريخ إنشاء التقرير: {_dt.now().strftime('%Y-%m-%d %H:%M')}", font(FONT_REGULAR, 13), MUTED)
    y += 55

    # ملخص عددي
    stats = [
        (str(report["total_readings"]), "إجمالي القراءات", TEAL),
        (str(report["counts"]["خطر مؤكد"]), "قراءات خطر مؤكد", CORAL),
        (str(report["counts"]["تنبيه استباقي"]), "تنبيهات استباقية", (191, 149, 79)),
        (str(report["sos_count"]), "نداءات استغاثة", CORAL),
    ]
    gap, n_cols = 22, 4
    cw = (CONTENT_W - gap * (n_cols - 1)) / n_cols
    ch = 150
    for i, (num, label, color) in enumerate(stats):
        x1 = RIGHT - i * (cw + gap); x0 = x1 - cw
        d.rounded_rectangle([x0, y, x1, y + ch], 16, fill=CARD, outline=BORDER, width=2)
        d.text(((x0+x1)/2, y+55), num, font=font(FONT_BOLD, 34), fill=color, anchor="mm")
        for li, line in enumerate(rwrap(d, label, font(FONT_REGULAR, 13), cw-24)):
            rtext(d, ((x0+x1)/2, y+95+li*20), line, font(FONT_REGULAR, 13), DARK, anchor="ma")
    y += ch + 45

    if report["baseline_mean"] is not None:
        lo = round(report["baseline_mean"] - 1.5*report["baseline_std"])
        hi = round(report["baseline_mean"] + 1.5*report["baseline_std"])
        d.rounded_rectangle([LEFT, y, RIGHT, y+70], 14, fill=(227, 238, 237), outline=(227, 238, 237))
        rtext(d, (RIGHT-25, y+35), f"نطاق القراءات الطبيعي الخاص بالمريض: {lo} – {hi} mg/dL", font(FONT_BOLD, 16),
              TEAL, anchor="rm")
        y += 100

    # رسم بياني للقراءات
    rdf = report["readings"]
    if len(rdf) >= 2:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt
        fig, ax = _plt.subplots(figsize=(7.6, 2.6), dpi=150)
        xs = range(len(rdf))
        colors_map = {"طبيعي": "#1B5E62", "تنبيه استباقي": "#D4A017", "خطر مؤكد": "#D5574A"}
        pc = [colors_map.get(l, "#1B5E62") for l in rdf["smart_level"]]
        if report["baseline_mean"] is not None:
            lo = report["baseline_mean"] - 1.5*report["baseline_std"]
            hi = report["baseline_mean"] + 1.5*report["baseline_std"]
            ax.axhspan(lo, hi, color="#1B5E62", alpha=0.10)
        ax.plot(xs, rdf["reading"], color="#163A3E", linewidth=1.3, zorder=1)
        ax.scatter(xs, rdf["reading"], c=pc, s=45, zorder=2, edgecolors="white", linewidths=0.8)
        ax.set_ylabel("mg/dL", fontsize=9)
        ax.set_xticks(list(xs)); ax.set_xticklabels([str(i+1) for i in xs], fontsize=7)
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
        fig.tight_layout()
        chart_path = "/tmp/_sanad_report_chart.png"
        fig.savefig(chart_path, dpi=150)
        _plt.close(fig)
        chart_img = Image.open(chart_path)
        ratio = CONTENT_W / chart_img.width
        chart_img = chart_img.resize((int(chart_img.width*ratio), int(chart_img.height*ratio)))
        img.paste(chart_img, (LEFT, int(y)))
        y += chart_img.height + 30

    pages.append(img)

    # ---------------- الصفحة الثانية: الوقائع + الأدوية ----------------
    img2 = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([0, 0, PAGE_W, 12], fill=TEAL)
    y2 = 90
    rtext(d2, (RIGHT, y2), "الوقائع البارزة خلال الفترة", font(FONT_BOLD, 26), NAVY)
    y2 += 55
    d2.line([(LEFT, y2), (RIGHT, y2)], fill=BORDER, width=2)
    y2 += 30

    if not report["incidents"]:
        rtext(d2, (RIGHT, y2), "لا توجد وقائع خارجة عن الطبيعي خلال هذه الفترة. الحمد لله.", font(FONT_REGULAR, 16), MUTED)
        y2 += 40
    else:
        for inc in report["incidents"]:
            color = CORAL if inc["level"] == "خطر مؤكد" else (191, 149, 79)
            d2.ellipse([RIGHT-14, y2+6, RIGHT, y2+20], fill=color)
            line1 = f"{inc['date']} — قراءة {inc['reading']:g} mg/dL ({inc['level']})"
            rtext(d2, (RIGHT-24, y2), line1, font(FONT_BOLD, 15), DARK)
            y2 += 26
            if inc["reason"]:
                y2 = draw_para(d2, inc["reason"], font(FONT_REGULAR, 13), y2, RIGHT-24, CONTENT_W-24, fill=MUTED, lh=20)
            y2 += 18

    y2 += 25
    d2.line([(LEFT, y2), (RIGHT, y2)], fill=BORDER, width=2)
    y2 += 35
    rtext(d2, (RIGHT, y2), "الالتزام بالأدوية", font(FONT_BOLD, 24), NAVY)
    y2 += 50

    if not report["medications"]:
        rtext(d2, (RIGHT, y2), "لا توجد أدوية مسجلة بالنظام.", font(FONT_REGULAR, 15), MUTED)
    else:
        for med in report["medications"]:
            d2.rounded_rectangle([LEFT, y2, RIGHT, y2+60], 12, fill=CARD, outline=BORDER, width=2)
            rtext(d2, (RIGHT-20, y2+30), f"{med['name']} ({med['dose']}) — {med['time']}", font(FONT_BOLD, 15),
                  DARK, anchor="rm")
            pct_color = TEAL if med["pct"] >= 70 else (CORAL if med["pct"] < 40 else (191, 149, 79))
            d2.text((LEFT+20, y2+30), f"{med['pct']}%  ({med['taken']}/{med['scheduled']})", font=font(FONT_BOLD, 16),
                     fill=pct_color, anchor="lm")
            y2 += 75

    rtext(d2, (PAGE_W/2, PAGE_H-90),
          "تم إنشاء هذا التقرير تلقائياً بواسطة نظام سند — لأغراض المتابعة، لا يُغني عن استشارة الطبيب المعالج",
          font(FONT_REGULAR, 12), MUTED, anchor="mm")
    pages.append(img2)

    out_path = "/tmp/sanad_weekly_report.pdf"
    tmp_imgs = []
    for i, p in enumerate(pages):
        pth = f"/tmp/_sanad_report_page_{i}.png"
        p.save(pth)
        tmp_imgs.append(pth)
    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(tmp_imgs))
    return out_path

def _send_telegram_document_single(bot_token, chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (os.path.basename(file_path), f, "application/pdf")},
                timeout=20,
            )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, None
        return False, resp.json().get("description", f"HTTP {resp.status_code}")
    except requests.exceptions.RequestException as e:
        return False, str(e)

def send_telegram_document(bot_token: str, chat_ids, file_path: str, caption: str = ""):
    """يرسل ملفاً لكل مستقبل مُدخل. يرجع (نجح لمستقبل واحد على الأقل؟, تفاصيل الأخطاء إن وُجدت)."""
    ids = parse_chat_ids(chat_ids)
    if not bot_token or not ids:
        return False, "التوكن أو معرف المحادثة غير مُدخل"
    failures = []
    any_ok = False
    for cid in ids:
        ok, err = _send_telegram_document_single(bot_token, cid, file_path, caption)
        if ok:
            any_ok = True
        else:
            failures.append(f"{cid}: {err}")
    detail = " | ".join(failures) if failures else None
    return any_ok, detail


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
def parse_chat_ids(raw):
    """يحوّل مدخل معرفات المحادثة (نص مفصول بفواصل أو قائمة) إلى قائمة نظيفة بدون تكرار أو مسافات."""
    if isinstance(raw, (list, tuple)):
        items = [str(c).strip() for c in raw]
    else:
        items = [c.strip() for c in str(raw or "").split(",")]
    seen, out = set(), []
    for c in items:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _send_telegram_message_single(bot_token, chat_id, message):
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

def send_telegram_alert(bot_token: str, chat_ids, message: str):
    """يرسل رسالة فوراً لكل مستقبل مُدخل (فريق الرعاية كامل).
    chat_ids: نص واحد، أو نص معرفات مفصولة بفاصلة، أو قائمة.
    يرجع (نجح لمستقبل واحد على الأقل؟, تفاصيل الأخطاء إن وُجدت)."""
    ids = parse_chat_ids(chat_ids)
    if not bot_token or not ids:
        return False, "التوكن أو معرف المحادثة غير مُدخل"
    failures = []
    any_ok = False
    for cid in ids:
        ok, err = _send_telegram_message_single(bot_token, cid, message)
        if ok:
            any_ok = True
        else:
            failures.append(f"{cid}: {err}")
    detail = " | ".join(failures) if failures else None
    return any_ok, detail

# ------------------------------------------------------------
# قراءة إعدادات تيليجرام (مشتركة بين الدورين - القراءة فقط بدون واجهة)
# ------------------------------------------------------------
try:
    telegram_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
except Exception:
    telegram_token = ""
    telegram_chat_id = ""

if role == "father":
    # ------------------------------------------------------------
    # الشريط الجانبي (متاح للأب فقط - إعدادات وتحكم)
    # ------------------------------------------------------------
    with st.sidebar.expander("🎬 وضع العرض التجريبي (Demo)", expanded=False):
        st.caption(
            "يعبّي النظام ببيانات واقعية لآخر 12 يوماً (قراءات متنوعة، نداء استغاثة، "
            "والتزام أدوية) عشان يظهر الرسم البياني والتقرير فوراً أمام اللجنة."
        )
        st.warning("⚠️ بيانات تجريبية فقط لأغراض العرض — لا تُرسل أي تنبيهات تيليجرام حقيقية أثناء التحميل.")
        if has_demo_data():
            st.info("📊 يوجد بيانات تجريبية محمّلة حالياً.")
            if st.button("🗑️ حذف البيانات التجريبية (رجوع للوضع الطبيعي)", use_container_width=True):
                clear_demo_data()
                st.success("تم حذف البيانات التجريبية. النظام رجع لوضعه الطبيعي.")
                st.rerun()
        else:
            if st.button("📊 تحميل بيانات تجريبية للعرض", use_container_width=True):
                generate_demo_data()
                st.success("تم تحميل البيانات التجريبية بنجاح.")
                st.rerun()

    st.sidebar.subheader("⚙️ إعدادات الطوارئ والاتصال")
    target_phone = st.sidebar.text_input("رقم طوارئ الابن (واتساب - احتياطي يدوي)", value="966500000000")

    with st.sidebar.expander("🏠 تصعيد الجار الموثوق (اختياري)"):
        st.caption(
            "لو ما تجاوب أحد من العائلة على نداء استغاثة أو تنبيه خطر خلال مدة معينة، "
            "يرسل النظام تلقائياً تنبيه إضافي لجار موثوق يقدر يوصل بسرعة."
        )
        _neighbor_enabled = st.checkbox("تفعيل تصعيد الجار", value=get_setting("neighbor_enabled", "0") == "1")
        set_setting("neighbor_enabled", "1" if _neighbor_enabled else "0")
        if _neighbor_enabled:
            _neighbor_chat_id = st.text_input(
                "معرف محادثة الجار على تيليجرام (Chat ID)", value=get_setting("neighbor_chat_id", "")
            )
            if _neighbor_chat_id != get_setting("neighbor_chat_id", ""):
                set_setting("neighbor_chat_id", _neighbor_chat_id)
            _neighbor_grace = st.number_input(
                "مهلة الانتظار قبل التصعيد (دقائق)",
                min_value=2, max_value=60, value=int(get_setting("neighbor_grace_minutes", "10") or 10)
            )
            if str(_neighbor_grace) != get_setting("neighbor_grace_minutes", "10"):
                set_setting("neighbor_grace_minutes", str(_neighbor_grace))
            st.caption("ملاحظة: نفس خطوات إعداد بوت تيليجرام أعلاه — الجار يفتح محادثة مع نفس البوت ويرسل أي رسالة عشان تحصل على Chat ID الخاص فيه.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 بوت تيليجرام (إرسال تلقائي لفريق الرعاية)")
    with st.sidebar.expander("ℹ️ كيف أحصل على التوكن ومعرفات المحادثة؟"):
        st.markdown("""
        **1. أنشئ البوت (مرة واحدة فقط):**
        - افتح تيليجرام وابحث عن `BotFather`
        - أرسل له `/newbot` واتبع التعليمات
        - راح يعطيك **Token** — انسخه

        **2. احصل على معرف محادثة كل فرد من العائلة (Chat ID):**
        - كل فرد (الابن، البنت، أي أحد تبيه يستلم التنبيهات) يفتح محادثة مع البوت ويرسل له أي رسالة (مثلاً "مرحبا")
        - لكل واحد منهم: افتح هذا الرابط بالمتصفح (استبدل TOKEN بتوكنك):
          `https://api.telegram.org/botTOKEN/getUpdates`
        - بتلاقي `"chat":{"id": 123456789 ...}` لكل شخص — هذا رقمه الخاص

        **3. اجمعهم بخانة واحدة مفصولين بفاصلة:**
        مثال: `111111111,222222222,333333333`
        """)

    _recipient_count = len(parse_chat_ids(telegram_chat_id))

    if telegram_token and telegram_chat_id:
        st.sidebar.success(f"🔒 محفوظين بشكل دائم — عدد مستقبلي التنبيه: {_recipient_count}")
        with st.sidebar.expander("تعديل القيم المحفوظة؟"):
            st.caption("عدّلها من إعدادات Secrets في لوحة تحكم Streamlit Cloud مباشرة (أدق من الكتابة هنا في كل مرة).")
    else:
        st.sidebar.warning("⚠️ لم يتم حفظ التوكن بعد بشكل دائم — أدخله الآن، وراجع الشرح تحت لحفظه نهائياً.")
        telegram_token = st.sidebar.text_input("توكن البوت (Bot Token) - مؤقت", type="password", value=telegram_token)
        telegram_chat_id = st.sidebar.text_input(
            "معرفات محادثة فريق الرعاية (Chat IDs) - مؤقت",
            value=telegram_chat_id,
            placeholder="مثال: 111111111,222222222",
            help="ضع معرف كل شخص تبي يستلم التنبيهات، مفصولين بفاصلة"
        )
        if telegram_chat_id:
            st.sidebar.caption(f"عدد مستقبلي التنبيه المُدخلين: {len(parse_chat_ids(telegram_chat_id))}")
        with st.sidebar.expander("💾 كيف أحفظهم بشكل دائم ولا يروحون بعد التحديث؟"):
            st.markdown("""
            **إذا تطبيقك على Streamlit Cloud:**
            1. افتح [share.streamlit.io](https://share.streamlit.io) ولقِ تطبيقك
            2. اضغط القائمة (⋮) بجنب التطبيق ← **Settings** ← **Secrets**
            3. الصق هذا بالضبط (بقيمك الحقيقية، وضع كل معرفات فريق الرعاية مفصولة بفاصلة):
            ```
            TELEGRAM_BOT_TOKEN = "8879255452:AAETJet4SR8UdIQdfyh7oD7unDx25jPaO74"
            TELEGRAM_CHAT_ID = "7026633810,111111111,222222222"
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

# مواقيت الصلاة لليوم (تُستخدم لحساب مواعيد الأدوية المرتبطة بالصلاة)
_prayer_times = get_prayer_times(live_lat, live_lon)

# فحص صامت لأي دواء فات موعده دون تسجيل + إرسال تنبيه تلقائي عند اللزوم
_overdue_alerts = check_overdue_and_alert(telegram_token, telegram_chat_id, location_str, _prayer_times)
if _overdue_alerts:
    st.warning("⏰ تم إرسال تنبيه تلقائي بخصوص تأخّر أخذ: " + "، ".join(_overdue_alerts))

# فحص صامت لتصعيد الجار الموثوق لو فُعّلت الميزة ومرّت مهلة الانتظار على حدث طارئ
if get_setting("neighbor_enabled", "0") == "1":
    _neighbor_escalated = check_neighbor_escalation(
        telegram_token,
        get_setting("neighbor_chat_id", ""),
        int(get_setting("neighbor_grace_minutes", "10") or 10),
        location_str,
    )
    if _neighbor_escalated:
        st.warning("🏠 تم تصعيد آخر حالة طارئة للجار الموثوق (لم يصل رد من العائلة خلال المهلة).")

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
        n = len(parse_chat_ids(telegram_chat_id))
        who = f"{n} من أفراد العائلة" if n > 1 else "الابن"
        st.success(f"✅ تم إرسال التنبيه تلقائياً عبر تيليجرام إلى {who} (بدون أي تدخل يدوي).")
        if tg_error:
            st.caption(f"⚠️ ملاحظة: تعذّر الوصول لبعض المستقبلين: {tg_error}")
    else:
        st.warning(f"⚠️ لم يُرسل التنبيه التلقائي عبر تيليجرام لأي مستقبل: {tg_error}\n\nيمكنك استخدام رابط الواتساب اليدوي بالأعلى كبديل مؤقت.")

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

if role == "father":
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
    # تسجيل قراءة السكر يدوياً (classify_sugar معرّفة على مستوى الملف بالأعلى)
    # ------------------------------------------------------------
    st.markdown("### 🩸 تسجيل قراءة سكر الدم")

    _baseline_mean, _baseline_std, _baseline_n = get_personal_baseline()
    if _baseline_mean is not None:
        _lo, _hi = round(_baseline_mean - 1.5*_baseline_std), round(_baseline_mean + 1.5*_baseline_std)
        st.caption(f"🧠 نطاقك الشخصي المعتاد (بناءً على آخر {_baseline_n} قراءة): {_lo} – {_hi} mg/dL")
    else:
        st.caption(f"🧠 التعلم الذكي يحتاج {MIN_HISTORY_FOR_BASELINE} قراءات على الأقل ليبدأ بتحديد نطاقك الشخصي (المسجل حالياً: {_baseline_n}).")

    with st.expander("🔍 كيف يفكر سند؟ (الذكاء القابل للتفسير)"):
        st.markdown(
            "سند **لا يعتمد ذكاءً اصطناعياً معقداً يصعب تفسيره** — كل قرار فيه مبني على "
            "خطوتين واضحتين تقدر تشرحهما لأي أحد بجملة واحدة:"
        )
        st.markdown("**1) الحدود الطبية الثابتة:** أقل من 75 أو أكثر من 180 = خطر مؤكد دايماً، لأي شخص.")
        if _baseline_mean is not None:
            st.markdown(
                f"**2) نطاقك الشخصي:** متوسط آخر {_baseline_n} قراءة ({round(_baseline_mean)}) "
                f"± 1.5 من الانحراف المعياري ({round(_baseline_std,1)}) = نطاقك الطبيعي **{_lo}–{_hi}**. "
                f"أي قراءة برّا هذا النطاق (حتى لو ضمن الحدود الثابتة) أو اتجاه هبوط/صعود متتالي بآخر 4 قراءات → تنبيه استباقي."
            )
        else:
            st.markdown("**2) نطاقك الشخصي:** لسا ما توفرت قراءات كافية لحسابه (يحتاج 5 على الأقل).")
        st.caption("بهذا الشكل، أي تنبيه يوصلك له سبب رياضي واضح تقدر تراجعه بنفسك — مو نموذج صندوق أسود.")

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
        _new_med_schedule_type = st.radio(
            "نوع الموعد", ["وقت محدد", "مرتبط بصلاة"], horizontal=True, key="new_med_schedule_type_radio"
        )
        with st.form("add_med_form", clear_on_submit=True):
            med_name = st.text_input("اسم الدواء")
            med_dose = st.text_input("الجرعة (مثال: حبة واحدة)")
            if _new_med_schedule_type == "وقت محدد":
                med_time = st.time_input("موعد الجرعة اليومي")
                prayer_name_sel, prayer_offset_sel = "", 0
            else:
                prayer_name_sel = st.selectbox("الصلاة", PRAYER_NAMES_AR)
                prayer_offset_sel = st.number_input(
                    "بعد الصلاة بكم دقيقة؟ (رقم سالب = قبل الصلاة)", value=15, step=5
                )
                med_time = None
                if _prayer_times is None:
                    st.caption("⚠️ ما قدرنا نجيب مواقيت الصلاة الآن (يحتاج اتصال إنترنت) — بيتم حسابها تلقائياً أول ما يتوفر الاتصال.")
            submitted = st.form_submit_button("إضافة الدواء")
            if submitted:
                if med_name.strip():
                    if _new_med_schedule_type == "وقت محدد":
                        add_medication(med_name.strip(), med_dose.strip(), med_time.strftime("%H:%M"), schedule_type="clock")
                    else:
                        _fallback_med = {"schedule_type": "prayer", "prayer_name": prayer_name_sel,
                                          "prayer_offset": prayer_offset_sel, "time_of_day": "00:00"}
                        approx_time = get_effective_time_str(_fallback_med, _prayer_times) if _prayer_times else "00:00"
                        add_medication(med_name.strip(), med_dose.strip(), approx_time,
                                        schedule_type="prayer", prayer_name=prayer_name_sel, prayer_offset=prayer_offset_sel)
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
                schedule_desc = format_medication_schedule(med, _prayer_times)
                label = f"{status_icon} **{med['name']}** ({med['dose']}) — {schedule_desc}"
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

    st.markdown("---")

    # ------------------------------------------------------------
    # واجهة التقرير الصحي الأسبوعي
    # ------------------------------------------------------------
    st.markdown("### 📄 التقرير الصحي الأسبوعي")

    patient_name = st.text_input(
        "اسم المريض (يظهر بالتقرير)",
        value=get_setting("patient_name", ""),
        placeholder="مثال: عبدالله العضياني",
    )
    if patient_name and patient_name != get_setting("patient_name", ""):
        set_setting("patient_name", patient_name)

    if not _pdf_fonts_available():
        st.error("⚠️ ملفات الخط المطلوبة (fonts/FreeSerif.ttf و fonts/FreeSerifBold.ttf) غير موجودة بجانب app.py — أضفها أولاً لتفعيل هذه الميزة.")
    else:
        if st.button("📄 توليد التقرير الأسبوعي الآن", use_container_width=True):
            if not patient_name.strip():
                st.error("الرجاء إدخال اسم المريض أولاً.")
            else:
                with st.spinner("جاري إنشاء التقرير..."):
                    report_data = get_weekly_report_data(days=7)
                    pdf_path = generate_weekly_pdf_report(patient_name.strip(), report_data)
                st.success("✅ تم إنشاء التقرير بنجاح.")

                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                st.download_button(
                    "⬇️ تنزيل التقرير (PDF)", data=pdf_bytes,
                    file_name=f"sanad_weekly_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf", use_container_width=True,
                )

                tg_ok, tg_err = send_telegram_document(
                    telegram_token, telegram_chat_id, pdf_path,
                    caption=f"📄 التقرير الصحي الأسبوعي — {patient_name}"
                )
                if tg_ok:
                    st.success("✅ تم إرسال التقرير تلقائياً عبر تيليجرام.")
                else:
                    st.warning(f"⚠️ لم يُرسل التقرير عبر تيليجرام: {tg_err}\n\nيمكنك تنزيله يدوياً من الزر أعلاه.")

    # ------------------------------------------------------------
    # السجل التفصيلي (مطوي افتراضياً - للاطلاع التقني فقط)
    # ------------------------------------------------------------
    with st.expander("📋 عرض السجل التفصيلي الكامل"):
        logs_df = load_logs()
        st.dataframe(logs_df, use_container_width=True)

        if len(logs_df) > 0:
            csv = logs_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ تنزيل السجل كملف CSV", data=csv, file_name="sanad_logs.csv", mime="text/csv")

else:
    # ------------------------------------------------------------
    # عرض العائلة (للقراءة فقط - بدون أي إمكانية تعديل)
    # ملاحظة: بطاقة الحالة والرسم البياني معروضان أصلاً فوق لكلا الدورين
    # ------------------------------------------------------------
    st.markdown("### ⚠️ آخر الوقائع البارزة")
    _fam_report = get_weekly_report_data(days=14)
    if not _fam_report["incidents"]:
        st.info("لا توجد وقائع خارجة عن الطبيعي خلال آخر 14 يوماً. الحمد لله.")
    else:
        for _inc in _fam_report["incidents"]:
            _clr = "#D5574A" if _inc["level"] == "خطر مؤكد" else "#B8860B"
            st.markdown(f"""
                <div style="border-right:4px solid {_clr}; padding:8px 14px; margin-bottom:10px; background:#FAFAFA; border-radius:8px;">
                    <b>{_inc["date"]}</b> — قراءة {_inc["reading"]:g} mg/dL ({_inc["level"]})<br>
                    <span style="color:#666; font-size:14px;">{_inc["reason"]}</span>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("### 💊 الالتزام بالأدوية")
    _fam_meds = get_medications()
    if len(_fam_meds) == 0:
        st.caption("لا توجد أدوية مسجلة بعد.")
    else:
        for _, _med in _fam_meds.iterrows():
            _log = get_or_create_today_log(_med["id"])
            _taken_at = _log[3]
            _status = "✅ تم أخذه اليوم" if _taken_at else "⏳ لم يُسجَّل بعد اليوم"
            _sched_desc = format_medication_schedule(_med, _prayer_times)
            st.markdown(f"**{_med['name']}** ({_med['dose']}) — {_sched_desc} — {_status}")

    st.markdown("### 📄 التقرير الصحي الأسبوعي")
    _fam_patient_name = get_setting("patient_name", "")
    if not _pdf_fonts_available():
        st.error("⚠️ ميزة التقرير غير مفعّلة حالياً.")
    elif not _fam_patient_name:
        st.info("لم يُدخل الأب اسم المريض بعد، لذا لا يمكن توليد التقرير حالياً.")
    else:
        if st.button("📄 توليد وتنزيل آخر تقرير أسبوعي", use_container_width=True):
            with st.spinner("جاري إنشاء التقرير..."):
                _report_data = get_weekly_report_data(days=7)
                _pdf_path = generate_weekly_pdf_report(_fam_patient_name, _report_data)
            with open(_pdf_path, "rb") as f:
                _pdf_bytes = f.read()
            st.download_button(
                "⬇️ تنزيل التقرير (PDF)", data=_pdf_bytes,
                file_name=f"sanad_weekly_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf", use_container_width=True,
            )
