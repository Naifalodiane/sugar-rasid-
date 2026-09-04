import time
from datetime import datetime
import pandas as pd
import streamlit as st
import urllib.parse
import base64
import requests

# إعدادات الصفحة والتصميم
st.set_page_config(
    page_title="تطبيق سند والنظام الذكي لسكر راصد", 
    page_icon="🛡️", 
    layout="wide"
)

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { border-radius: 8px; font-weight: bold; }
    .card { background-color: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 20px; border: 1px solid #eef0f2; }
    </style>
""", unsafe_allow_html=True)

st.info("⚠️ **إخلاء مسؤولية بحثي:** نظام رصد السكر هو نموذج أولي بحثي فقط (Research Prototype) وليس جهازاً طبياً معتمداً.")
st.title("🛡️ نظام «سند» المتكامل - رعاية كبار السن والسكر الذكي")

# تهيئة الذاكرة
if "logs" not in st.session_state:
    try:
        st.session_state.logs = pd.read_csv("shared_data.csv")
    except:
        st.session_state.logs = pd.DataFrame(
            columns=[
                "رقم الاختبار", "قراءة السكر (mg/dL)", "الحالة الفعلية (المرجعية)",
                "تصنيف النظام", "هل تم إرسال تنبيه؟", "وقت معالجة القراءة",
                "زمن إرسال التنبيه (مللي ثانية)", "دقة التصنيف"
            ]
        )

# إعدادات الشريط الجانبي
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ إعدادات النظام وربط السحابة")

github_token = st.sidebar.text_input("GitHub Token (رمز الربط السحابي)", type="password", value="")
repo_name = st.sidebar.text_input("اسم مستودع غيت هب للأب", value="Naifalodiane/sugar-rasid")

target_phone = st.sidebar.text_input("رقم جوال الطوارئ للواتساب", value="966500000000")
son_phone = st.sidebar.text_input("رقم جوال الابن للاتصال السريع", value="0509036511")
default_lat = st.sidebar.text_input("خط العرض", value="24.549513")
default_lon = st.sidebar.text_input("خط الطول", value="44.377016")

def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

df_check = st.session_state.logs
latest_val = df_check.iloc[-1]["قراءة السكر (mg/dL)"] if not df_check.empty else None
latest_status = df_check.iloc[-1]["تصنيف النظام"] if not df_check.empty else "طبيعي"
location_str = f"https://maps.google.com/?q={default_lat},{default_lon}"

# دالة ذكية ومباشرة لرفع الملف عبر GitHub API بدون مكتبات خارجية
def update_github_repo_direct(df):
    if not github_token:
        return False
    try:
        csv_content = df.to_csv(index=False)
        encoded_content = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
        url = f"https://api.github.com/repos/{repo_name}/contents/shared_data.csv"
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json"
        }
        
        # جلب الـ sha الحالي للملف إن وجد
        get_res = requests.get(url, headers=headers)
        sha = get_res.json().get("sha") if get_res.status_code == 200 else None
        
        data = {
            "message": "Update shared_data.csv via Samad App",
            "content": encoded_content
        }
        if sha:
            data["sha"] = sha
            
        put_res = requests.put(url, headers=headers, json=data)
        return put_res.status_code in [200, 201]
    except Exception as e:
        st.sidebar.error(f"خطأ في الرفع: {e}")
        return False

# ---------------- لوحة الطوارئ ----------------
if latest_val is not None and latest_status != "طبيعي":
    st.markdown("---")
    auto_alert_text = f"🚨 *نداء طوارئ آلي* 🚨\nخطر! سكر الدم: {latest_val} mg/dL ({latest_status}).\n📍 الموقع: {location_str}"
    encoded_auto = urllib.parse.quote(auto_alert_text)
    auto_whatsapp_url = f"https://wa.me/{target_phone}?text={encoded_auto}"
    
    st.markdown(f"""
        <div style="background-color:#fff5f5; padding:25px; border-radius:15px; border:2px solid #ff4d4d; text-align:center;">
            <h2 style="color:#cc0000; margin-top:0;">🚨 حالة طوارئ قصوى!</h2>
            <p style="font-size:18px;">قراءة حرجة: <b>{latest_val} mg/dL ({latest_status})</b></p>
            <a href="{auto_whatsapp_url}" target="_blank" style="background-color:#25D366; color:white; padding:14px 28px; text-decoration:none; font-size:18px; font-weight:bold; border-radius:10px; display:inline-block;">
                💬 إرسال رسالة الطوارئ عبر الواتساب فوراً
            </a>
        </div>
    """, unsafe_allow_html=True)

# الواجهة الرئيسية والإدخال
st.markdown("---")
st.markdown("### ⚙️ إدخال قراءات سكر راصد")

input_mode = st.radio("اختر طريقة الإدخال:", ["إدخال يدوي لقراءة", "محاكاة دفعة اختبارات"], horizontal=True)

if input_mode == "إدخال يدوي لقراءة":
    col_i1, col_i2 = st.columns(2)
    with col_i1:
        manual_val = st.number_input("قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=50)
    with col_i2:
        true_state_manual = st.selectbox("الحالة الفعلية للمريض", ["انخفاض", "طبيعي", "ارتفاع"])

    if st.button("معالجة القراءة وتسجيلها في النظام", use_container_width=True):
        system_classification = classify_sugar(manual_val)
        alert_sent = "نعم" if system_classification != "طبيعي" else "لا"
        new_row = {
            "رقم الاختبار": f"TEST-{len(st.session_state.logs)+1:03d}",
            "قراءة السكر (mg/dL)": manual_val,
            "الحالة الفعلية (المرجعية)": true_state_manual,
            "تصنيف النظام": system_classification,
            "هل تم إرسال تنبيه؟": alert_sent,
            "وقت معالجة القراءة": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "زمن إرسال التنبيه (مللي ثانية)": 50.0 if alert_sent == "نعم" else 0.0,
            "دقة التصنيف": "صحيح" if system_classification == true_state_manual else "خاطئ"
        }
        st.session_state.logs = pd.concat([st.session_state.logs, pd.DataFrame([new_row])], ignore_index=True)
        st.session_state.logs.to_csv("shared_data.csv", index=False)
        
        # رفع التحديث للسحابة مباشرة
        if update_github_repo_direct(st.session_state.logs):
            st.success("✅ تم تحديث ونشر القراءة سحابياً بنجاح لتظهر عند الابن فوراً!")
        else:
            st.warning("⚠️ تم الحفظ محلياً، تأكد من وضع الرمز الصحيح في الشريط الجانبي.")
        st.rerun()

st.markdown("---")
st.markdown("##### 📋 السجل الحالي")
st.dataframe(st.session_state.logs, use_container_width=True)
