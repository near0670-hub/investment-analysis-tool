import streamlit as st
st.set_page_config(page_title="Test")

try:
    from modules.data_loader import load_company_data
    st.success("data_loader OK")
except Exception as e:
    st.error(f"data_loader 실패: {e}")

try:
    from modules.growth_analysis import analyze_growth
    st.success("growth_analysis OK")
except Exception as e:
    st.error(f"growth_analysis 실패: {e}")

try:
    from modules.stability_analysis import render_tab
    st.success("stability_analysis OK")
except Exception as e:
    st.error(f"stability_analysis 실패: {e}")

st.write("진단 완료!")
