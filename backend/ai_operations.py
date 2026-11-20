"""Shared Streamlit navigation for the existing AI Operations dashboards."""
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="AI Operations", layout="wide")
# Anchor only the navigation to the viewport. The native header and sidebar
# keep their original layout, full height, collapse control, and resize behavior.
# Use semantic hooks instead of generated Streamlit class names.
st.html("""<style>
@media screen {
    [data-testid="stTopNav"] {
        position: fixed;
        top: 1.875rem;
        left: 50%;
        transform: translate(-50%, -50%);
        width: max-content;
        max-width: calc(100% - 8rem);
        margin: 0;
    }
    [data-testid="stToolbar"] > div > div:last-child {
        margin-left: auto;
    }
}
</style>""")

page = st.navigation(
    [
        st.Page("evaluation/dashboard.py", title="Evaluation", default=True),
        st.Page("observation/dashboard.py", title="Observation", url_path="observation"),
    ],
    position="top",
)
page.run()
