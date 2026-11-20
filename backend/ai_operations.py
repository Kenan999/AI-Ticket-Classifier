"""Shared Streamlit navigation for the existing AI Operations dashboards."""
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="AI Operations", layout="wide")
page = st.navigation(
    [
        st.Page("evaluation/dashboard.py", title="Evaluation", default=True),
        st.Page("../Observation/dashboard.py", title="Observation", url_path="observation"),
    ],
    position="top",
)
page.run()
