"""Small visual layer for the Streamlit dashboard."""

import streamlit as st


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { max-width: 1180px; padding-top: 2rem; }
        [data-testid="stSidebar"] {
            background: #f7f9fc;
            border-right: 1px solid #e5eaf0;
        }
        [data-testid="stMetric"] {
            background: #f5f7fa;
            border: 1px solid #e1e6ec;
            border-radius: 10px;
            padding: 1rem;
        }
        .dashboard-kicker {
            color: #4e6174;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .job-description {
            background: #f8fafc;
            border-left: 3px solid #2f6fed;
            border-radius: 4px;
            padding: 1rem;
            white-space: pre-wrap;
        }
        .brand-name {
            color: #1f4f85;
            font-size: 1.45rem;
            font-weight: 750;
            letter-spacing: -0.02em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
