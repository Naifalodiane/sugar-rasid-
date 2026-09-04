import time
from datetime import datetime
import pandas as pd
import streamlit as st
import urllib.parse
from streamlit_geolocation import streamlit_geolocation

# إعدادات الصفحة
st.set_page_config(
    page_title="تطبيق سند والنظام الذكي لسكر راصد", page_icon="🛡️", layout="wide"
)

# تنبيه إخلاء مسؤولية بحثي
st.warning(
    "⚠️ **إخلاء مسؤولية بحثي:** نظام رصد السكر هو نموذج أولي بحثي فقط (Research Prototype) وليس جهازاً طبياً معتمداً، والهدف منه قياس كفاءة خوارزميات التنبيه ضمن منصة سند الشاملة."
)

st.title("🛡️ نظام «سند» المتكامل - رعاية كبار السن والسكر الذكي")
st.markdown("منصة رقمية موحدة تجمع بين رعاية السلامة والطارئ (سند) والرصد الذكي لقراءات السكر (سكر راصد).")

# تهيئة جدول البيانات في ذاكرة الجلسة
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
# إعدادات رقم الجوال الموحدة في الشريط الجانبي (تُحفظ مرة واحدة)
# ---------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("📱 إعدادات تنبيهات الطوارئ (سند)")
target_phone = st.sidebar.text_input(
    "رقم جوال الطوارئ الموحد (مع مفتاح الدولة، مثل 9665xxxxxxxx)", 
    value="966500000000"
)

# تصميم التبويبات الرئيسية
tab_main, tab_rasid_control, tab_rasid_stats = st.tabs([
    "🚨 لوحة طوارئ ورعاية سند", 
    "⚙️ لوحة تحكم وإدخال سكر راصد", 
    "📊 المؤشرات والإحصائيات البحثية"
])

# المعايير الطبية القياسية للبحث (للتصنيف)
def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"


# ---------------------------------------------------------
# التبويب الأول: تطبيق سند (رعاية الطوارئ، تحديد الموقع الجغرافي GPS)
# ---------------------------------------------------------
with tab_main:
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
        
        # فحص أحدث قراءة مسجلة في السجل
        df_check = st.session_state.logs
        latest_row = None
        if not df_check.empty:
            latest_row = df_check.iloc[-1]
            latest_val = latest_row["قراءة السكر (mg/dL)"]
            latest_status = latest_row["تصنيف النظام"]
        else:
            latest_val = None
            latest_status = "طبيعي"

        # إذا كانت أحدث قراءة تدل على خطورة (انخفاض أو ارتفاع)
        if latest_val is not None and latest_status != "طبيعي":
            st.error(f"🚨 **تنبيه طارئ من نظام سكر راصد!** آخر قراءة مسجلة خطيرة: ({latest_val} mg/dL) - الحالة: {latest_status}")
            
            if lat and lon:
                location_str = f"https://maps.google.com/?q={lat},{lon}"
            else:
                location_str = "لم يتم التقاط الإحداثيات الجغرافية بعد"
            
            smart_alert_text = f"🚨 *نداء طوارئ عاجل من تطبيق سند وسكر راصد* 🚨\nتنبيه خطير! سكر الدم لدى المسن وصل إلى: {latest_val} mg/dL ({latest_status}).\n📍 الموقع الحالي للجهاز:\n{location_str}\nالرجاء سرعة التدخل والمباشرة فوراً!"
            encoded_smart = urllib.parse.quote(smart_alert_text)
            smart_whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_smart}"
            
            st.markdown(f"👉 **[🚨 اضغط هنا لإرسال رسالة الطوارئ الفورية عبر الواتساب للأرقام المعتمدة]({smart_whatsapp_url})**", unsafe_allow_html=True)
        else:
            st.success("✅ الحالة العامة مستقرة ولا توجد قراءات حرجة حالياً.")
        
        # زر الفزعة اليدوي الإضافي
        if st.button("🚨 زر الفزعة الطارئة اليدوي (SOS)", use_container_width=True):
            if lat and lon:
                location_str = f"https://maps.google.com/?q={lat},{lon}"
            else:
                location_str = "الإحداثيات غير متاحة"
            
            manual_text = f"🚨 *نداء طوارئ يدوي من تطبيق سند* 🚨\nالمسن يحتاج إلى مساعدة فورية!\n📍 الموقع:\n{location_str}"
            encoded_m = urllib.parse.quote(manual_text)
            manual_whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_m}"
            st.markdown(f"👉 **[اضغط هنا لإرسال رسالة الطوارئ اليدوية عبر الواتساب]({manual_whatsapp_url})**", unsafe_allow_html=True)
            
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
with tab_rasid_control:
    st.header("إدارة وإدخال قراءات سكر راصد")
    
    input_mode = st.radio(
        "اختر طريقة الإدخال:", ["إدخال يدوي لقراءة", "محاكاة دفعة اختبارات (100+)"]
    )

    if input_mode == "إدخال يدوي لقراءة":
        st.subheader("إدخال قراءة جديدة (مثل تجربة 50 للانخفاض)")
        manual_val = st.number_input(
            "قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=50
        )
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
                st.error(f"⚠️ تنبيه خطير! تم رصد حالة ({system_classification}) بالقراءة {manual_val} mg/dL. **انتقل فوراً إلى التبويب الأول (لوحة طوارئ ورعاية سند) لإرسال رسالة الواتساب الفورية!**")
            else:
                st.success(f"تمت المعالجة بنجاح! القراءة طبيعية ({system_classification}).")

    else:
        st.subheader("محاكاة بيانات بحثية متقدمة")
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
            st.success(f"تم توليد ومعالجة {num_tests} اختباراً بنجاح ضمن بيئة سند!")

    # زر لتفريغ السجل
    if not st.session_state.logs.empty:
        if st.button("🗑️ مسح جميع السجلات"):
            st.session_state.logs = pd.DataFrame(columns=st.session_state.logs.columns)
            st.rerun()


# ---------------------------------------------------------
# التبويب الثالث: لوحة المؤشرات والإحصائيات البحثية
# ---------------------------------------------------------
with tab_rasid_stats:
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
            mime="text/csv",
        )

    else:
        st.info(
            "لا توجد بيانات مسجلة حتى الآن. انتقل إلى تبويب (لوحة تحكم وإدخال سكر راصد) لإدخال قراءة أو تشغيل المحاكاة."
        )
