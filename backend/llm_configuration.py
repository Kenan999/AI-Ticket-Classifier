"""Central LLM selection in the native, collapsible Streamlit sidebar."""
import streamlit as st
from backend.llms.registry import model_configuration
from backend.evaluation.evaluate import load_env

models = model_configuration(load_env())["llms"]
ids = [item["id"] for item in models]
labels = {item["id"]: f'{item["provider"]} · {item["model"]}' for item in models}
with st.sidebar:
    st.header("LLM Configuration")
    selected = st.selectbox("LLM auswählen", options=ids,
                            format_func=lambda key: labels[key], key="llm_config_selected")
    st.caption("Modellauswahl für diese Streamlit-Sitzung.")
st.title("LLM Configuration")
st.info(f"Ausgewähltes LLM: {labels[selected]}")
st.caption("Die Auswahl ist noch nicht mit dem Evaluation- oder Chat-Backend verbunden.")
