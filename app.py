from datetime import datetime
import sqlite3
import pandas as pd
import streamlit as st
import urllib.parse
import requests

# ============================================================
#  نظام «سند» - تطبيق الأب
#  التحديثات الجديدة في هذه النسخة:
#   1) زر فزعة (SOS) يدوي فوري - لا يحتاج قراءة سكر
#   2) قاعدة بيانات SQLite حقيقية - البيانات ما تضيع بعد التحديث
#   3) موقع GPS حقيقي من متصفح الجهاز (بدل الإحداثيات الثابتة)
# ============================================================

st.set_page_config(page_title="تطبيق الأب - سند", layout="wide")

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
    conn.commit()
    conn.close()

def insert_log(row: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO logs (test_id, reading, true_state, system_class, alert_sent,
                           processed_at, alert_ms, accuracy, event_type)
        VALUES (:test_id, :reading, :true_state, :system_class, :alert_sent,
                :processed_at, :alert_ms, :accuracy, :event_type)
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

init_db()

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
manual_val = st.number_input("قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=120)
true_state_manual = st.selectbox("الحالة الفعلية", ["انخفاض", "طبيعي", "ارتفاع"])

if st.button("معالجة وتسجيل القراءة فوراً", use_container_width=True):
    start_time = datetime.now()
    system_classification = classify_sugar(manual_val)
    alert_sent = "نعم" if system_classification != "طبيعي" else "لا"
    elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

    new_row = {
        "test_id": next_test_id(),
        "reading": manual_val,
        "true_state": true_state_manual,
        "system_class": system_classification,
        "alert_sent": alert_sent,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_ms": round(elapsed_ms, 2),
        "accuracy": "صحيح" if system_classification == true_state_manual else "خاطئ",
        "event_type": "قراءة سكر",
    }
    insert_log(new_row)

    if system_classification != "طبيعي":
        auto_alert_text = (
            f"🚨 *تنبيه طوارئ من تطبيق الأب* 🚨\n"
            f"القراءة المسجلة خطيرة: {manual_val} mg/dL ({system_classification}).\n"
            f"📍 الموقع: {location_str}"
        )
        render_alert_box(
            f"🚨 تحذير خطير: القراءة ({system_classification}: {manual_val}) غير طبيعية!",
            auto_alert_text,
        )
    else:
        st.success("✅ تمت معالجة وتسجيل القراءة بنجاح (الحالة طبيعية).")

# ------------------------------------------------------------
# السجل الحالي (من قاعدة البيانات - يبقى محفوظاً دائماً)
# ------------------------------------------------------------
st.markdown("### 📋 السجل الحالي:")
logs_df = load_logs()
st.dataframe(logs_df, use_container_width=True)

if len(logs_df) > 0:
    csv = logs_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ تنزيل السجل كملف CSV", data=csv, file_name="sanad_logs.csv", mime="text/csv")
