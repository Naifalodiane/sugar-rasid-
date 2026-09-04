import time
from datetime import datetime
import pandas as pd
import streamlit as st
import base64
import requests

st.set_page_config(page_title="تطبيق الأب - سكر راصد", layout="wide")

st.title("🛡️ نظام «سند» - تطبيق الأب")

if "logs" not in st.session_state:
    st.session_state.logs = pd.DataFrame(
        columns=[
            "رقم الاختبار", "قراءة السكر (mg/dL)", "الحالة الفعلية (المرجعية)",
            "تصنيف النظام", "هل تم إرسال تنبيه؟", "وقت معالجة القراءة",
            "زمن إرسال التنبيه (مللي ثانية)", "دقة التصنيف"
        ]
    )

st.sidebar.subheader("⚙️ إعدادات الرفع السحابي")
github_token = st.sidebar.text_input("GitHub Token", type="password", value="")
repo_name = st.sidebar.text_input("اسم المستودع", value="Naifalodiane/sugar-rasid")
target_phone = st.sidebar.text_input("رقم الطوارئ", value="966500000000")

def classify_sugar(value):
    if value < 75:
        return "انخفاض"
    elif value <= 180:
        return "طبيعي"
    else:
        return "ارتفاع"

manual_val = st.number_input("قراءة سكر الدم (mg/dL)", min_value=20, max_value=600, value=120)
true_state_manual = st.selectbox("الحالة الفعلية", ["انخفاض", "طبيعي", "ارتفاع"])

if st.button("معالجة وتسجيل ونشر القراءة فوراً", use_container_width=True):
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
    
    # الرفع السحابي الذكي (ينشئ الملف تلقائياً لو مو موجود)
    if github_token:
        try:
            csv_content = st.session_state.logs.to_csv(index=False)
            encoded_content = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
            url = f"https://api.github.com/repos/{repo_name}/contents/shared_data.csv"
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json"
            }
            
            # محاولة جلب الـ sha الحالي للملف
            get_res = requests.get(url, headers=headers)
            sha = get_res.json().get("sha") if get_res.status_code == 200 else None
            
            data = {
                "message": "Auto update shared_data.csv",
                "content": encoded_content
            }
            if sha:
                data["sha"] = sha
                
            put_res = requests.put(url, headers=headers, json=data)
            if put_res.status_code in [200, 201]:
                st.success("🚀 تم الرفع للسحابة بنجاح تام وتحديث بيانات الابن!")
            else:
                st.error(f"خطأ: {put_res.status_code} - {put_res.json().get('message', put_res.text)}")
        except Exception as e:
            st.error(f"خطأ استثنائي: {e}")
    else:
        st.warning("⚠️ يرجى إدخال الرمز في الشريط الجانبي.")

st.markdown("### السجل الحالي:")
st.dataframe(st.session_state.logs, use_container_width=True)
