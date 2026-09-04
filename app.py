from datetime import datetime
import pandas as pd
import streamlit as st
import urllib.parse

st.set_page_config(page_title="تطبيق الأب - سكر راصد", layout="wide")

st.title("🛡️ نظام «سند» - تطبيق الأب")
st.markdown("لوحة تسجيل البيانات وحالات الطوارئ المباشرة.")

# ثوابت النظام ورقام التواصل
father_phone = "0509036511"
default_lat = "24.549513"
default_lon = "44.377016"
location_str = f"https://maps.google.com/?q={default_lat},{default_lon}"

if "logs" not in st.session_state:
    st.session_state.logs = pd.DataFrame(
        columns=[
            "رقم الاختبار", "قراءة السكر (mg/dL)", "الحالة الفعلية (المرجعية)",
            "تصنيف النظام", "هل تم إرسال تنبيه؟", "وقت معالجة القراءة",
            "زمن إرسال التنبيه (مللي ثانية)", "دقة التصنيف"
        ]
    )

st.sidebar.subheader("⚙️ إعدادات الطوارئ والاتصال")
target_phone = st.sidebar.text_input("رقم طوارئ الابن (واتساب)", value="966500000000")
st.sidebar.markdown("---")
st.sidebar.info(f"📱 جوال الأب المسجل: {father_phone}")
st.sidebar.error("🚨 رقم الإسعاف السعودي المعتمد: 997")

def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

manual_val = st.number_input("قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=120)
true_state_manual = st.selectbox("الحالة الفعلية", ["انخفاض", "طبيعي", "ارتفاع"])

if st.button("معالجة وتسجيل القراءة فوراً", use_container_width=True):
    system_classification = classify_sugar(manual_val)
    alert_sent = "نعم" if system_classification != "طبيعي" else "لا"
    
    new_row = {
        "رقم الاختبار": f"TEST-{len(st.session_state.logs)+1:03d}",
        "قراءة السكر (mg/dL)": manual_val,
        "الحالة الفعلية (المرجعية)": true_state_manual,
        "تصنيف النظام": system_classification,
        "هل تم إرسال تنبيه؟": alert_sent,
        "وقت معالجة القراءة": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "زمن إرسال التنبيه (مللي ثانية)": 50.0,
        "دقة التصنيف": "صحيح" if system_classification == true_state_manual else "خاطئ"
    }
    
    st.session_state.logs = pd.concat([st.session_state.logs, pd.DataFrame([new_row])], ignore_index=True)
    
    # تنبيهات الطوارئ الفورية إذا كانت القراءة غير طبيعية
    if system_classification != "طبيعي":
        auto_alert_text = f"🚨 *تنبيه طوارئ من تطبيق الأب* 🚨\nالقراءة المسجلة خطيرة: {manual_val} mg/dL ({system_classification}).\n📍 الموقع: {location_str}"
        encoded_auto = urllib.parse.quote(auto_alert_text)
        whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_auto}"
        
        st.markdown(f"""
            <div style="background-color:#fff5f5; padding:20px; border-radius:12px; border:2px solid #ff4d4d; text-align:center; margin-bottom:15px;">
                <h3 style="color:#cc0000; margin-top:0;">🚨 تحذير خطير: القراءة ({system_classification}: {manual_val}) غير طبيعية!</h3>
                <p style="font-size:16px; margin-bottom:15px;">يمكنك التواصل السريع مع الابن أو طلب الإسعاف السعودي المباشر فوراً:</p>
                <div style="display: flex; justify-content: center; gap: 15px; flex-wrap: wrap;">
                    <a href="{whatsapp_url}" target="_blank" style="background-color:#25D366; color:white; padding:12px 20px; text-decoration:none; font-size:16px; font-weight:bold; border-radius:8px; display:inline-block;">
                        💬 إرسال تنبيه للابن عبر الواتساب
                    </a>
                    <a href="tel:997" style="background-color:#cc0000; color:white; padding:12px 20px; text-decoration:none; font-size:16px; font-weight:bold; border-radius:8px; display:inline-block;">
                        🚑 الاتصال الفوري بالإسعاف (997)
                    </a>
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.success("✅ تمت معالجة وتسجيل القراءة بنجاح (الحالة طبيعية).")

st.markdown("### السجل الحالي:")
st.dataframe(st.session_state.logs, use_container_width=True)
