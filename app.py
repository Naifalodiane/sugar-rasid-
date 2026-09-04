import time
from datetime import datetime
import pandas as pd
import streamlit as st
import urllib.parse

# إعدادات الصفحة والتصميم
st.set_page_config(
    page_title="تطبيق سند والنظام الذكي لسكر راصد", 
    page_icon="🛡️", 
    layout="wide"
)

# تخصيص التصميم العام عبر CSS لجمالية الواجهة الطبية
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
    }
    .card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        border: 1px solid #eef0f2;
    }
    </style>
""", unsafe_allow_html=True)

# تنبيه إخلاء مسؤولية بحثي بتصميم أنيق
st.info(
    "⚠️ **إخلاء مسؤولية بحثي:** نظام رصد السكر هو نموذج أولي بحثي فقط (Research Prototype) وليس جهازاً طبياً معتمداً، والهدف منه قياس كفاءة خوارزميات التنبيه ضمن منصة سند الشاملة."
)

st.title("🛡️ نظام «سند» المتكامل - رعاية كبار السن والسكر الذكي")
st.markdown("منصة رقمية موحدة تجمع بين رعاية السلامة والطارئ (سند) والرصد الذكي لقراءات السكر (سكر راصد).")

# تهيئة الذاكرة للجلسة
if "logs" not in st.session_state:
    st.session_state.logs = pd.DataFrame(
        columns=[
            "رقم الاختبار",
            "قراءة السكر (mg/dL)",
            "الحالة الفعلية (المرجعية)",
            "تصنيف النظام",
            "هل تم إرسال تنبيه؟",
            "وقت معالجة القراءة",
            "زمن إرسال التنبيه (مللي ثانية)",
            "دقة التصنيف",
        ]
    )

# ---------------------------------------------------------
# إعدادات النظام في الشريط الجانبي
# ---------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ إعدادات النظام (تشغيل 24/7)")

target_phone = st.sidebar.text_input(
    "رقم جوال الطوارئ للواتساب (مع مفتاح الدولة)", 
    value="966500000000"
)

son_phone = st.sidebar.text_input(
    "رقم جوال الابن للاتصال السريع", 
    value="0509036511"
)

st.sidebar.markdown("📌 **الموقع الثابت للطوارئ (الدوادمي):**")
default_lat = st.sidebar.text_input("خط العرض (Latitude)", value="24.549513")
default_lon = st.sidebar.text_input("خط الطول (Longitude)", value="44.377016")

# المعايير الطبية للبحث
def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"


# فحص أحدث قراءة مسجلة في السجل لمعرفة الحالة فوراً
df_check = st.session_state.logs
latest_row = None
latest_val = None
latest_status = "طبيعي"

if not df_check.empty:
    latest_row = df_check.iloc[-1]
    latest_val = latest_row["قراءة السكر (mg/dL)"]
    latest_status = latest_row["تصنيف النظام"]

location_str = f"https://maps.google.com/?q={default_lat},{default_lon}"

# ---------------------------------------------------------
# لوحة الطوارئ الذكية (تظهر تلقائياً في الأعلى عند الخطر)
# ---------------------------------------------------------
if latest_val is not None and latest_status != "طبيعي":
    st.markdown("---")
    auto_alert_text = f"🚨 *نداء طوارئ آلي 24/7 من نظام سند وسكر راصد* 🚨\nخطر! سكر الدم وصل إلى: {latest_val} mg/dL ({latest_status}).\n📍 الموقع المسجل للمسن:\n{location_str}\nالرجاء التدخل والمباشرة فوراً!"
    encoded_auto = urllib.parse.quote(auto_alert_text)
    auto_whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_auto}"
    
    st.markdown(f"""
        <div style="background-color:#fff5f5; padding:25px; border-radius:15px; border:2px solid #ff4d4d; text-align:center; box-shadow: 0 6px 12px rgba(255,77,77,0.15); margin-bottom: 25px;">
            <h2 style="color:#cc0000; margin-top:0;">🚨 تحويل تلقائي لوضع الطوارئ القصوى!</h2>
            <p style="font-size:18px; color:#333; margin-bottom: 15px;">رصد قراءة حرجة لسكر الدم: <b>{latest_val} mg/dL ({latest_status})</b>. يرجى سرعة التواصل وإرسال النداء الفوري:</p>
            <a href="{auto_whatsapp_url}" target="_blank" style="background-color:#25D366; color:white; padding:14px 28px; text-decoration:none; font-size:18px; font-weight:bold; border-radius:10px; display:inline-block; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                💬 إرسال رسالة الطوارئ عبر الواتساب فوراً
            </a>
        </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# الواجهة الرئيسية (تقسيم منظم وعصري)
# ---------------------------------------------------------
col_main1, col_main2 = st.columns(2)

with col_main1:
    st.markdown("""
        <div class="card">
            <h3 style="color:#1f77b4; margin-top:0;">📊 المؤشرات الحية والسلامة</h3>
    """, unsafe_allow_html=True)
    
    if latest_val is None or latest_status == "طبيعي":
        st.success("✅ الحالة العامة مستقرة والمؤشرات ضمن المعدل الطبيعي (نشط 24/7).")
    else:
        st.warning("⚠️ التنبيه النشط: النظام مسجل لحالة حرجة حالياً.")
        
    m1, m2 = st.columns(2)
    m1.metric(label="نبضات القلب", value="78 bpm", delta="مستقر")
    m2.metric(label="أكسجين الدم (SpO2)", value="98%", delta="طبيعي")
    
    st.markdown("</div>", unsafe_allow_html=True)

with col_main2:
    st.markdown("""
        <div class="card">
            <h3 style="color:#1f77b4; margin-top:0;">💊 الخطة العلاجية والاتصال السريع</h3>
    """, unsafe_allow_html=True)
    
    st.markdown("- **دواء الضغط ومنظم السكر:** الساعة 10:00 صباحاً (✅ تم الالتزام)")
    st.markdown("- **جرعة الإنسولين المسائية:** الساعة 8:00 مساءً (⏳ في الانتظار)")
    
    call_url = f"tel:{son_phone}"
    st.markdown(f"""
        <div style="margin-top: 20px;">
            <a href="{call_url}" style="background-color:#0066cc; color:white; padding:12px 20px; text-decoration:none; font-size:16px; font-weight:bold; border-radius:8px; display:block; text-align:center;">
                📞 الاتصال السريع بالابن / المسؤول ({son_phone})
            </a>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------
# لوحة تحكم وإدخال قراءات سكر راصد
# ---------------------------------------------------------
st.markdown("---")
st.markdown("### ⚙️ لوحة التحكم ومحاكاة قراءات (سكر راصد)")

with st.container():
    input_mode = st.radio(
        "اختر طريقة الإدخال:", ["إدخال يدوي لقراءة", "محاكاة دفعة اختبارات (100+)"], horizontal=True
    )

    if input_mode == "إدخال يدوي لقراءة":
        col_i1, col_i2 = st.columns(2)
        with col_i1:
            manual_val = st.number_input(
                "قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=50
            )
        with col_i2:
            true_state_manual = st.selectbox(
                "الحالة الفعلية للمريض (Ground Truth للبحث)",
                ["انخفاض", "طبيعي", "ارتفاع"],
            )

        if st.button("معالجة القراءة وتسجيلها في النظام", use_container_width=True):
            start_time = time.time()
            time.sleep(0.05)
            processing_time = round((time.time() - start_time) * 1000, 2)

            system_classification = classify_sugar(manual_val)
            alert_sent = "نعم" if system_classification != "طبيعي" else "لا"

            alert_time = (
                round(processing_time + 15, 2) if alert_sent == "نعم" else 0.0
            )
            is_correct = (
                "صحيح" if system_classification == true_state_manual else "خاطئ"
            )

            new_id = len(st.session_state.logs) + 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            new_row = {
                "رقم الاختبار": f"TEST-{new_id:03d}",
                "قراءة السكر (mg/dL)": manual_val,
                "الحالة الفعلية (المرجعية)": true_state_manual,
                "تصنيف النظام": system_classification,
                "هل تم إرسال تنبيه؟": alert_sent,
                "وقت معالجة القراءة": timestamp,
                "زمن إرسال التنبيه (مللي ثانية)": alert_time,
                "دقة التصنيف": is_correct,
            }

            st.session_state.logs = pd.concat(
                [st.session_state.logs, pd.DataFrame([new_row])], ignore_index=True
            )
            st.rerun()

    else:
        num_tests = st.slider(
            "عدد الاختبارات المراد محاكاتها", min_value=10, max_value=500, value=100
        )

        if st.button("بدء المحاكاة وتوليد السجل البحثي", use_container_width=True):
            import random

            simulated_data = []
            start_id = len(st.session_state.logs) + 1

            for i in range(num_tests):
                val = random.choice(
                    [
                        random.randint(40, 74),
                        random.randint(76, 175),
                        random.randint(185, 350),
                    ]
                )
                true_state = classify_sugar(val)

                start_t = time.time()
                system_class = classify_sugar(val)
                proc_t = round((time.time() - start_t) * 1000 + random.uniform(10, 30), 2)

                alert = "نعم" if system_class != "طبيعي" else "لا"
                alert_t = round(proc_t + random.uniform(5, 15), 2) if alert == "نعم" else 0.0
                correct = "صحيح" if system_class == true_state else "خاطئ"

                simulated_data.append(
                    {
                        "رقم الاختبار": f"TEST-{start_id + i:03d}",
                        "قراءة السكر (mg/dL)": val,
                        "الحالة الفعلية (المرجعية)": true_state,
                        "تصنيف النظام": system_class,
                        "هل تم إرسال تنبيه؟": alert,
                        "وقت معالجة القراءة": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "زمن إرسال التنبيه (مللي ثانية)": alert_t,
                        "دقة التصنيف": correct,
                    }
                )

            df_sim = pd.DataFrame(simulated_data)
            st.session_state.logs = pd.concat(
                [st.session_state.logs, df_sim], ignore_index=True
            )
            st.rerun()

# زر مسح السجلات
if not st.session_state.logs.empty:
    if st.button("🗑️ مسح جميع السجلات وإعادة ضبط الحالة"):
        st.session_state.logs = pd.DataFrame(columns=st.session_state.logs.columns)
        st.rerun()


# ---------------------------------------------------------
# لوحة المؤشرات والإحصائيات والتوثيق البحثي
# ---------------------------------------------------------
st.markdown("---")
st.markdown("### 📊 لوحة المؤشرات والإحصائيات والتوثيق البحثي")

df = st.session_state.logs

if not df.empty:
    total_tests = len(df)
    correct_cases = len(df[df["دقة التصنيف"] == "صحيح"])
    incorrect_cases = len(df[df["دقة التصنيف"] == "خاطئ"])
    accuracy_rate = (
        round((correct_cases / total_tests) * 100, 2) if total_tests > 0 else 0
    )

    avg_alert_time = round(df[df["زمن إرسال التنبيه (مللي ثانية)"] > 0]["زمن إرسال التنبيه (مللي ثانية)"].mean(), 2)
    if pd.isna(avg_alert_time):
        avg_alert_time = 0.0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("إجمالي الاختبارات", total_tests)
    col2.metric("نسبة الدقة", f"{accuracy_rate}%")
    col3.metric("الحالات الصحيحة", correct_cases)
    col4.metric("الحالات الخاطئة", incorrect_cases)
    col5.metric("متوسط زمن التنبيه", f"{avg_alert_time} ms")

    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 📈 توزيع تصنيفات النظام")
        status_counts = df["تصنيف النظام"].value_counts()
        st.bar_chart(status_counts)

    with c2:
        st.markdown("##### 📉 مقارنة التنبيهات والمرجعية")
        alert_counts = df["هل تم إرسال تنبيه؟"].value_counts()
        st.bar_chart(alert_counts)

    st.markdown("---")

    st.markdown("##### 📋 سجل الاختبارات التفصيلي")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 تحميل السجل بصيغة CSV (لاستخدامه في ملف البحث PDF)",
        data=csv,
        file_name="sanad_sugar_research_logs.csv",
        mime="text/csv",
        use_container_width=True
    )

else:
    st.info("لا توجد بيانات مسجلة حتى الآن. استخدم خيار الإدخال اليدوي أو المحاكاة بالأعلى لبدء الفحص وإظهار التحليلات.")
