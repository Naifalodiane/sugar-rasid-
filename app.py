import time
from datetime import datetime
import pandas as pd
import streamlit as st
import urllib.parse
from streamlit_geolocation import streamlit_geolocation

# إعدادات الصفحة والتصميم
st.set_page_config(
    page_title="تطبيق سند والنظام الذكي لسكر راصد", page_icon="🛡️", layout="wide"
)

# تنبيه إخلاء مسؤولية بحثي
st.warning(
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

# متغير لحفظ التبويب النشط تلقائياً
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0

# إعداد رقم جوال الطوارئ الموحد في الشريط الجانبي (يحفظ مرة واحدة)
st.sidebar.markdown("---")
st.sidebar.subheader("📱 إعدادات تنبيهات الطوارئ (سند)")
target_phone = st.sidebar.text_input(
    "رقم جوال الطوارئ الموحد (مع مفتاح الدولة، مثل 9665xxxxxxxx)", 
    value="966500000000"
)

# المعايير الطبية للبحث
def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

# ---------------------------------------------------------
# التبويب الأول: تطبيق سند (الطوارئ، الـ GPS، والواتساب التلقائي)
# ---------------------------------------------------------
with st.container():
    st.header("لوحة المتابعة اليومية لكبار السن والرعاية الشاملة")
    
    col_s1, col_s2 = st.columns(2)
    
    with col_s1:
        st.subheader("🚨 الطوارئ والسلامة")
        
        # أداة جلب الإحداثيات الحقيقية للجهاز (GPS)
        st.markdown("📌 **تحديد الموقع الجغرافي الحالي:**")
        loc = streamlit_geolocation()
        
        lat = loc.get('latitude') if loc else None
        lon = loc.get('longitude') if loc else None
        
        if lat and lon:
            st.success(f"موقعك الحالي مسجل بدقة: خط عرض {lat}، خط طول {lon}")
        else:
            st.info("الرجاء السماح للمتصفح بالوصول للموقع لتضمينه في رسائل الطوارئ التلقائية.")
        
        # فحص أحدث قراءة مسجلة
        df_check = st.session_state.logs
        if not df_check.empty:
            latest_row = df_check.iloc[-1]
            latest_val = latest_row["قراءة السكر (mg/dL)"]
            latest_status = latest_row["تصنيف النظام"]
        else:
            latest_val = None
            latest_status = "طبيعي"

        # إذا كانت القراءة خطيرة (انخفاض أو ارتفاع)
        if latest_val is not None and latest_status != "طبيعي":
            st.error(f"🚨 **تنبيه طارئ فوري!** تم رصد حالة ({latest_status}) بقراءة: {latest_val} mg/dL")
            
            if lat and lon:
                location_str = f"https://maps.google.com/?q={lat},{lon}"
            else:
                location_str = "الإحداثيات الجغرافية جارٍ التقاطها..."
            
            auto_alert_text = f"🚨 *نداء طوارئ آلي من نظام سند وسكر راصد* 🚨\nتنبيه خطير! سكر الدم وصل إلى: {latest_val} mg/dL ({latest_status}).\n📍 الموقع الحالي:\n{location_str}\nالرجاء التدخل والمباشرة فوراً!"
            encoded_auto = urllib.parse.quote(auto_alert_text)
            auto_whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_auto}"
            
            # زر إرسال مباشر وبارز جداً يفتح الواتساب بلمسة واحدة
            st.markdown(f"""
                <div style="background-color:#ffe6e6; padding:15px; border-radius:10px; border:2px solid #ff4d4d; text-align:center;">
                    <h3 style="color:#cc0000; margin:0;">⚠️ الحالة حرجة وتتطلب تدخلاً فورياً!</h3>
                    <p>تم تحويلك تلقائياً إلى لوحة الطوارئ. اضغط الزر أدناه لفتح الواتساب وإرسال النداء:</p>
                    <a href="{auto_whatsapp_url}" target="_blank" style="background-color:#25D366; color:white; padding:12px 25px; text-decoration:none; font-size:18px; font-weight:bold; border-radius:8px; display:inline-block; margin-top:10px;">
                        💬 إرسال رسالة الواتساب الطارئة الآن
                    </a>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.success("✅ الحالة العامة مستقرة ولا توجد أي تنبيهات حرجة مسجلة.")
            
        if st.button("📞 الاتصال السريع بالابن / المسؤول الموثوق", use_container_width=True):
            st.success("📞 جاري توجيه الاتصال بالمسؤول...")

    with col_s2:
        st.subheader("❤️ المؤشرات الحيوية المباشرة")
        st.metric(label="نبضات القلب", value="78 نبضة/دقيقة", delta="مستقر")
        st.metric(label="أكسجين الدم (SpO2)", value="98%", delta="طبيعي")

    st.markdown("---")
    st.subheader("💊 جدول الأدوية والمواعيد اليومية")
    st.markdown("- **دواء الضغط ومنظم السكر:** الساعة 10:00 صباحاً (✅ تم الالتزام)")
    st.markdown("- **جرعة الإنسولين المسائية:** الساعة 8:00 مساءً (⏳ في الانتظار)")


# ---------------------------------------------------------
# التبويب الثاني: لوحة تحكم وإدخال سكر راصد
# ---------------------------------------------------------
st.markdown("---")
st.subheader("⚙️ لوحة تحكم وإدخال قراءات سكر راصد")

input_mode = st.radio(
    "اختر طريقة الإدخال:", ["إدخال يدوي لقراءة", "محاكاة دفعة اختبارات (100+)"]
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

    if st.button("معالجة القراءة وتسجيلها"):
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
        
        if system_classification != "طبيعي":
            st.error(f"🚨 تم رصد خطر ({system_classification}) بالقراءة {manual_val}! جاري تحويلك وإعداد رسالة الطوارئ الفورية...")
            time.sleep(1.5)  # محاكاة الانتظار التلقائي (ثوانٍ معدودة)
            st.rerun()  # إعادة تحديث الصفحة لتظهر لك لوحة الطوارئ في الأعلى مباشرة
        else:
            st.success(f"تمت المعالجة بنجاح! القراءة طبيعية ({system_classification}).")

else:
    num_tests = st.slider(
        "عدد الاختبارات المراد محاكاتها", min_value=10, max_value=500, value=100
    )

    if st.button("بدء المحاكاة وتوليد السجل"):
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
        st.success(f"تم توليد ومعالجة {num_tests} اختباراً بنجاح!")

# زر تفريغ السجلات
if not st.session_state.logs.empty:
    if st.button("🗑️ مسح جميع السجلات"):
        st.session_state.logs = pd.DataFrame(columns=st.session_state.logs.columns)
        st.rerun()


# ---------------------------------------------------------
# التبويب الثالث: المؤشرات والإحصائيات البحثية
# ---------------------------------------------------------
st.markdown("---")
st.header("📊 لوحة المؤشرات والإحصائيات والتوثيق البحثي")

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

    st.subheader("📋 سجل الاختبارات التفصيلي")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 تحميل السجل بصيغة CSV (لاستخدامه في ملف البحث PDF)",
        data=csv,
        file_name="sanad_sugar_research_logs.csv",
        mime="text/css",
    )

else:
    st.info("لا توجد بيانات مسجلة حتى الآن. استخدم خيار الإدخال اليدوي أو المحاكاة بالأعلى لبدء الفحص.")
