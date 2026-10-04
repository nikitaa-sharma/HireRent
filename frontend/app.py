"""Hirent recruiter dashboard and read-only recruiter workflows."""

from __future__ import annotations

import sys
import math
from pathlib import Path

import streamlit as st

# Streamlit runs this file with the frontend directory first on sys.path.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from frontend.api_client import APIClient, APIClientError
from frontend.styles import apply_styles


BRAND_NAME = "Hirent"
BACKEND_ERROR_MESSAGE = "Unable to connect to Hirent backend."


def _format_date(value: object) -> str:
    if not value:
        return "Unknown date"
    return str(value).replace("T", " ").split(".")[0]


def _candidate_from_association(association: dict) -> dict:
    candidate = association.get("candidate")
    return candidate if isinstance(candidate, dict) else {}


def _load_dashboard_data(
    client: APIClient,
    *,
    include_reviews: bool = True,
) -> tuple[list[dict], list[dict], dict[int, list[dict]]]:
    jobs = client.list_jobs()
    candidates = client.list_candidates()
    reviews_by_job = (
        {
            int(job["id"]): client.get_job_reviews(int(job["id"]))
            for job in jobs
            if job.get("id") is not None
        }
        if include_reviews
        else {}
    )
    return jobs, candidates, reviews_by_job


def _job_options(jobs: list[dict]) -> dict[str, dict]:
    return {
        f"{job.get('title', 'Untitled job')} · #{job.get('id')}": job
        for job in jobs
    }


def _render_dashboard(
    client: APIClient,
    jobs: list[dict],
    candidates: list[dict],
    reviews_by_job: dict[int, list[dict]],
) -> None:
    st.markdown(
        '<div class="dashboard-kicker">Recruitment Intelligence</div>',
        unsafe_allow_html=True,
    )
    st.title("Recruiter Dashboard")
    st.write(
        "Search, compare, and evaluate candidates with evidence-backed AI decision support."
    )

    under_review_count = sum(
        1
        for reviews in reviews_by_job.values()
        for review in reviews
        if review.get("status") == "reviewing"
    )
    metric_columns = st.columns(3)
    metric_columns[0].metric("Total Jobs", len(jobs))
    metric_columns[1].metric("Total Candidates", len(candidates))
    metric_columns[2].metric("Candidates Under Review", under_review_count)

    st.subheader("Recent Jobs")
    if not jobs:
        st.info("No jobs have been created yet.")
    else:
        st.dataframe(
            [
                {
                    "Job": job.get("title", "Untitled job"),
                    "Created": _format_date(job.get("created_at")),
                    "Candidates": len(reviews_by_job.get(int(job["id"]), [])),
                }
                for job in jobs[:5]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Jobs")
    if not jobs:
        st.info("No jobs have been created yet.")
        return

    selected_label = st.selectbox("Select a job", list(_job_options(jobs)))
    selected_job_id = int(_job_options(jobs)[selected_label]["id"])
    try:
        selected_job = client.get_job(selected_job_id)
        associated_candidates = client.get_job_candidates(selected_job_id)
    except APIClientError:
        st.error(BACKEND_ERROR_MESSAGE)
        return

    st.markdown(f"### {selected_job.get('title', 'Untitled job')}")
    st.markdown(
        f'<div class="job-description">{selected_job.get("description", "No description available.")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Candidate count: {len(associated_candidates)}")
    if not associated_candidates:
        st.info("No candidates are associated with this job.")
        return

    st.dataframe(
        [
            {
                "Candidate": _candidate_from_association(item).get(
                    "name", "Unknown candidate"
                ),
                "Location": _candidate_from_association(item).get("location")
                or "Not provided",
                "Match Score": item.get("match_score"),
                "Status": item.get("status", "new"),
            }
            for item in associated_candidates
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_jobs(client: APIClient, jobs: list[dict]) -> None:
    st.title("Jobs")
    st.write("Create a job opening for recruiters to review candidates against.")
    with st.form("create_job_form", clear_on_submit=True):
        title = st.text_input("Job Title")
        description = st.text_area("Job Description", height=180)
        submitted = st.form_submit_button("Create Job", type="primary")

    if not submitted:
        return
    if not title.strip():
        st.error("Job title cannot be empty.")
        return
    if not description.strip():
        st.error("Job description cannot be empty.")
        return

    try:
        created_job = client.create_job(title.strip(), description.strip())
        jobs[:] = client.list_jobs()
    except APIClientError as error:
        st.error(str(error))
        return
    st.success(f'Job "{created_job.get("title", title.strip())}" created successfully.')
    st.info("The job is ready for candidate uploads. Matching has not been run.")
    st.subheader("Available Jobs")
    st.dataframe(
        [
            {"Job": job.get("title", "Untitled job"), "Created": _format_date(job.get("created_at"))}
            for job in jobs
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_upload_candidates(client: APIClient, jobs: list[dict]) -> None:
    st.title("Upload Candidates")
    st.write("Upload PDF resumes and add the resulting candidates to an existing job.")
    if not jobs:
        st.info("Create a job before uploading candidates.")
        return

    options = _job_options(jobs)
    selected_label = st.selectbox("Select a job", list(options), key="upload_job")
    selected_job_id = int(options[selected_label]["id"])
    files = st.file_uploader(
        "PDF resumes",
        type=["pdf"],
        accept_multiple_files=True,
        help="Only PDF resumes are accepted. Backend upload size limits still apply.",
    )
    if not files or not st.button("Upload Candidates", type="primary"):
        return

    results: list[dict[str, object]] = []
    with st.spinner("Uploading and associating resumes..."):
        for uploaded_file in files:
            filename = uploaded_file.name
            result: dict[str, object] = {"Filename": filename, "Candidate": "—", "Status": "Failed"}
            if not filename.lower().endswith(".pdf"):
                result["Error"] = "Only PDF resumes are accepted."
                results.append(result)
                continue
            try:
                candidate = client.upload_resume(filename, uploaded_file.getvalue())
                candidate_id = candidate.get("id")
                result["Candidate"] = candidate.get("name", "Unnamed Candidate")
                result["Candidate ID"] = candidate_id or "—"
                result["Status"] = "Uploaded"
                if not isinstance(candidate_id, int):
                    raise APIClientError("Backend returned no candidate ID for the upload")
                client.associate_candidate(selected_job_id, candidate_id)
                result["Status"] = "Added to job"
            except APIClientError as error:
                result["Error"] = str(error)
            results.append(result)

    # Refresh the same read models used by the dashboard without touching the database.
    client.list_candidates()
    client.get_job_candidates(selected_job_id)
    st.subheader("Upload Results")
    st.dataframe(results, use_container_width=True, hide_index=True)
    if any(result["Status"] == "Added to job" for result in results):
        st.success("Successful uploads have been added to the selected job.")
        st.info("Matching and AI analysis have not been run.")


def _render_search_results(results: list[dict]) -> None:
    if not results:
        st.info("No candidates matched your search.")
        return

    st.dataframe(
        [
            {
                "Candidate": result.get("name", "Unknown candidate"),
                "Candidate ID": result.get("candidate_id", "Unavailable"),
                "Location": result.get("location") or "Not provided",
                "Similarity Score": result.get("similarity_score", "Unavailable"),
            }
            for result in results
        ],
        use_container_width=True,
        hide_index=True,
    )
    for index, result in enumerate(results):
        name = result.get("name", "Unknown candidate")
        candidate_id = result.get("candidate_id", "Unavailable")
        with st.expander(f"{name} · Candidate ID {candidate_id}", expanded=index == 0):
            st.caption(
                f"Location: {result.get('location') or 'Not provided'} | "
                f"Similarity score: {result.get('similarity_score', 'Unavailable')}"
            )
            for field, label in (
                ("experience", "Experience"),
                ("experience_years", "Experience (years)"),
                ("skills", "Relevant skills"),
            ):
                value = result.get(field)
                if value not in (None, "", []):
                    st.markdown(f"**{label}:** {value}")
            evidence = result.get("evidence")
            if evidence:
                st.markdown("**Resume evidence**")
                st.write(evidence)
            else:
                st.caption("No resume evidence was returned for this result.")


def _render_candidate_search(
    client: APIClient, candidates: list[dict]
) -> None:
    st.title("Candidate Search")
    st.write(
        "Search candidates with natural-language queries using backend semantic search."
    )
    st.caption(
        "Similarity scores and resume evidence are generated by the backend. "
        "Search results are decision support, not an automatic hiring decision."
    )

    if not candidates:
        st.info("No candidates are available yet. Upload candidates before searching.")
        return

    if "candidate_search_results" not in st.session_state:
        st.session_state.candidate_search_results = None
    if "candidate_search_query" not in st.session_state:
        st.session_state.candidate_search_query = ""

    with st.form("candidate_search_form"):
        query = st.text_input(
            "Search candidates",
            placeholder="Python backend developer with FastAPI and 3+ years experience",
        )
        skills_text = st.text_input(
            "Skills (optional)",
            placeholder="Python, FastAPI",
        )
        location = st.text_input(
            "Location (optional)",
            placeholder="Mumbai",
        )
        minimum_experience_text = st.text_input(
            "Minimum experience in years (optional)",
            placeholder="3",
        )
        result_limit = st.number_input(
            "Result limit",
            min_value=1,
            max_value=100,
            value=10,
            step=1,
        )
        search_clicked = st.form_submit_button("Search Candidates", type="primary")
        clear_clicked = st.form_submit_button("Clear Search")

    if clear_clicked:
        st.session_state.candidate_search_results = None
        st.session_state.candidate_search_query = ""
        st.rerun()

    if search_clicked:
        cleaned_query = query.strip()
        if not cleaned_query:
            st.error("Enter a search query to find candidates.")
        else:
            minimum_experience: float | None = None
            if minimum_experience_text.strip():
                try:
                    minimum_experience = float(minimum_experience_text.strip())
                except ValueError:
                    st.error("Minimum experience must be a valid number.")
            if minimum_experience is not None and (
                minimum_experience < 0 or not math.isfinite(minimum_experience)
            ):
                st.error("Minimum experience must be a finite non-negative number.")

            if (
                cleaned_query
                and (
                    not minimum_experience_text.strip()
                    or (
                        minimum_experience is not None
                        and minimum_experience >= 0
                    )
                )
            ):
                skills = [
                    skill.strip()
                    for skill in skills_text.split(",")
                    if skill.strip()
                ]
                try:
                    with st.spinner("Searching backend candidate records..."):
                        st.session_state.candidate_search_results = client.search_candidates(
                            cleaned_query,
                            limit=int(result_limit),
                            skills=skills,
                            min_experience_years=minimum_experience,
                            location=location.strip() or None,
                        )
                    st.session_state.candidate_search_query = cleaned_query
                except APIClientError as error:
                    st.error(str(error))

    results = st.session_state.candidate_search_results
    if results is not None:
        st.subheader("Search Results")
        st.caption(f'Backend results for: "{st.session_state.candidate_search_query}"')
        _render_search_results(results)


def _render_comparison_evidence(entry: dict, field: str, heading: str) -> None:
    items = entry.get(field)
    if not isinstance(items, list) or not items:
        st.caption(f"No {heading.lower()} returned.")
        return
    st.markdown(f"**{heading}**")
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not text:
            continue
        source = item.get("source")
        evidence_type = item.get("type")
        metadata = " · ".join(
            value for value in (evidence_type, source) if isinstance(value, str) and value
        )
        st.markdown(f"- {text}" + (f" ({metadata})" if metadata else ""))


def _render_comparison_result(comparison: dict) -> None:
    candidates = comparison.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        st.info("The backend returned no comparison results.")
        return

    st.caption(
        "Comparison results are backend-generated decision support. "
        "Candidates remain in the order you selected them; no winner or recommendation is shown."
    )
    st.dataframe(
        [
            {
                "Candidate": entry.get("candidate_name", "Unknown candidate"),
                "Candidate ID": entry.get("candidate_id", "Unavailable"),
                "Match Score": entry.get("match_score", "Unavailable"),
                "Education Match": entry.get("education_match", "Unavailable"),
                "Experience Gap (years)": entry.get(
                    "experience_gap_years", "Unavailable"
                ),
            }
            for entry in candidates
            if isinstance(entry, dict)
        ],
        use_container_width=True,
        hide_index=True,
    )

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        name = entry.get("candidate_name", "Unknown candidate")
        candidate_id = entry.get("candidate_id", "Unavailable")
        with st.expander(f"{name} · Candidate ID {candidate_id}"):
            st.markdown(f"**Backend match score:** {entry.get('match_score', 'Unavailable')}")
            component_scores = entry.get("component_scores")
            if isinstance(component_scores, dict) and component_scores:
                st.markdown("**Backend component scores**")
                st.dataframe(
                    [
                        {"Component": key, "Score": value}
                        for key, value in component_scores.items()
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            for field, heading in (
                ("matched_required_skills", "Matched required skills"),
                ("missing_required_skills", "Missing required skills"),
                ("matched_preferred_skills", "Matched preferred skills"),
            ):
                values = entry.get(field)
                if isinstance(values, list):
                    st.markdown(f"**{heading}:** {', '.join(map(str, values)) or 'None returned'}")
            st.markdown(
                f"**Experience gap (years):** {entry.get('experience_gap_years', 'Unavailable')}"
            )
            st.markdown(
                f"**Education match:** {entry.get('education_match', 'Unavailable')}"
            )
            _render_comparison_evidence(entry, "strengths", "Strengths")
            _render_comparison_evidence(entry, "gaps", "Match gaps")
            _render_comparison_evidence(entry, "evidence", "Supporting evidence")


def _render_candidate_comparison(client: APIClient, jobs: list[dict]) -> None:
    st.title("Compare Candidates")
    st.write(
        "Compare 2 to 5 candidates associated with a job using backend-generated match evidence."
    )
    st.caption(
        "Comparison is decision support only. Hirent does not select a winner or recommend "
        "who should be hired."
    )
    if not jobs:
        st.info("No jobs have been created yet.")
        return

    options = _job_options(jobs)
    selected_label = st.selectbox("Select a job", list(options), key="comparison_job")
    selected_job_id = int(options[selected_label]["id"])
    if st.session_state.get("comparison_job_id") != selected_job_id:
        st.session_state.comparison_job_id = selected_job_id
        st.session_state.comparison_result = None

    try:
        associated_candidates = client.get_job_candidates(selected_job_id)
    except APIClientError:
        st.error(BACKEND_ERROR_MESSAGE)
        return
    if not associated_candidates:
        st.info("No candidates are associated with this job.")
        return

    candidate_options: dict[str, int] = {}
    for association in associated_candidates:
        candidate_id = association.get("candidate_id")
        if not isinstance(candidate_id, int):
            continue
        candidate = _candidate_from_association(association)
        label = (
            f"{candidate.get('name', 'Unknown candidate')} · "
            f"#{candidate_id} · {candidate.get('location') or 'Location unavailable'}"
        )
        candidate_options[label] = candidate_id

    if len(candidate_options) < 2:
        st.info("At least 2 candidates associated with this job are required for comparison.")
        return

    selected_labels = st.multiselect(
        "Select 2 to 5 candidates",
        list(candidate_options),
        max_selections=5,
        key=f"comparison_candidates_{selected_job_id}",
    )
    selected_candidate_ids = [candidate_options[label] for label in selected_labels]
    if st.button("Compare Candidates", type="primary"):
        if len(selected_candidate_ids) < 2:
            st.error("Select at least 2 candidates to compare.")
        elif len(selected_candidate_ids) > 5:
            st.error("Select no more than 5 candidates to compare.")
        else:
            try:
                with st.spinner("Comparing candidates using backend evidence..."):
                    st.session_state.comparison_result = client.compare_candidates(
                        selected_job_id, selected_candidate_ids
                    )
            except APIClientError as error:
                st.error(str(error))

    comparison_result = st.session_state.get("comparison_result")
    if isinstance(comparison_result, dict):
        st.subheader(comparison_result.get("job_title", "Comparison results"))
        _render_comparison_result(comparison_result)


REVIEW_STATUSES = [
    "new",
    "reviewing",
    "shortlisted",
    "interview",
    "rejected",
    "hired",
]


def _render_review_overview(reviews: list[dict]) -> None:
    if not reviews:
        st.info("No candidates are associated with this job.")
        return
    st.dataframe(
        [
            {
                "Candidate": review.get("candidate_name", "Unknown candidate"),
                "Candidate ID": review.get("candidate_id", "Unavailable"),
                "Match Score": review.get("match_score", "Unavailable"),
                "Status": review.get("status", "new"),
                "Recruiter Notes": "Yes" if review.get("recruiter_notes") else "No",
            }
            for review in reviews
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_review_candidates(client: APIClient, jobs: list[dict]) -> None:
    st.title("Review Candidates")
    st.write(
        "Update job-specific candidate workflow status and private recruiter notes."
    )
    st.caption(
        "Statuses are recruiter-controlled workflow labels. Hirent does not make hiring "
        "recommendations or automatically change review status."
    )
    if not jobs:
        st.info("No jobs have been created yet.")
        return

    options = _job_options(jobs)
    selected_label = st.selectbox("Select a job", list(options), key="review_job")
    selected_job_id = int(options[selected_label]["id"])
    if st.session_state.get("review_job_id") != selected_job_id:
        st.session_state.review_job_id = selected_job_id
        st.session_state.review_candidate_id = None
        st.session_state.review_data = None

    try:
        associated_candidates = client.get_job_candidates(selected_job_id)
        job_reviews = client.get_job_reviews(selected_job_id)
    except APIClientError:
        st.error(BACKEND_ERROR_MESSAGE)
        return

    st.subheader("Job Review Overview")
    _render_review_overview(job_reviews)
    if not associated_candidates:
        return

    candidate_options: dict[str, int] = {}
    for association in associated_candidates:
        candidate_id = association.get("candidate_id")
        if not isinstance(candidate_id, int):
            continue
        candidate = _candidate_from_association(association)
        candidate_options[
            f"{candidate.get('name', 'Unknown candidate')} · "
            f"#{candidate_id} · {candidate.get('location') or 'Location unavailable'}"
        ] = candidate_id
    if not candidate_options:
        st.info("No valid candidate associations are available for this job.")
        return

    selected_candidate_label = st.selectbox(
        "Select a candidate",
        list(candidate_options),
        key=f"review_candidate_{selected_job_id}",
    )
    selected_candidate_id = candidate_options[selected_candidate_label]
    if st.session_state.get("review_candidate_id") != selected_candidate_id:
        st.session_state.review_candidate_id = selected_candidate_id
        try:
            st.session_state.review_data = client.get_candidate_review(
                selected_job_id, selected_candidate_id
            )
        except APIClientError as error:
            st.session_state.review_data = None
            st.error(str(error))
            return

    review_data = st.session_state.get("review_data")
    if not isinstance(review_data, dict):
        st.error("Unable to load the selected candidate review.")
        return
    candidate = next(
        (
            _candidate_from_association(association)
            for association in associated_candidates
            if association.get("candidate_id") == selected_candidate_id
        ),
        {},
    )
    match_score = next(
        (
            item.get("match_score")
            for item in associated_candidates
            if item.get("candidate_id") == selected_candidate_id
        ),
        "Unavailable",
    )
    st.subheader(candidate.get("name", "Unknown candidate"))
    st.caption(
        f"Candidate ID: {selected_candidate_id} | "
        f"Location: {candidate.get('location') or 'Not provided'} | "
        f"Match score: {match_score}"
    )

    with st.form(f"review_form_{selected_job_id}_{selected_candidate_id}"):
        current_status = review_data.get("status", "new")
        status = st.selectbox(
            "Status",
            REVIEW_STATUSES,
            index=(
                REVIEW_STATUSES.index(current_status)
                if current_status in REVIEW_STATUSES
                else 0
            ),
        )
        notes = st.text_area(
            "Recruiter Notes",
            value=review_data.get("recruiter_notes") or "",
            height=160,
            help="Private notes stored on this job-candidate review.",
        )
        save_review = st.form_submit_button("Save Review", type="primary")

    if save_review:
        try:
            updated_review = client.update_candidate_review(
                selected_job_id,
                selected_candidate_id,
                status=status,
                recruiter_notes=notes,
            )
            st.session_state.review_data = updated_review
            st.success("Review saved successfully.")
            st.session_state.review_job_reviews = client.get_job_reviews(selected_job_id)
            st.rerun()
        except APIClientError as error:
            st.error(str(error))


def _render_chat_evidence(evidence: object) -> None:
    if not isinstance(evidence, list) or not evidence:
        return
    st.caption("Supporting backend evidence")
    for item in evidence:
        if not isinstance(item, dict):
            continue
        candidate_name = item.get("candidate_name", "Unknown candidate")
        candidate_id = item.get("candidate_id", "Unavailable")
        source = item.get("source", "Backend source")
        text = item.get("text")
        if text:
            st.markdown(f"- **{candidate_name}** (ID {candidate_id}) · {source}: {text}")


def _render_recruiter_chat(client: APIClient, jobs: list[dict]) -> None:
    st.title("Recruiter Chat")
    st.write(
        "Ask grounded questions about candidates, jobs, matches, evidence, and reviews."
    )
    st.caption(
        "Hirent AI is recruiter decision support grounded in backend data. "
        "It does not make final hiring decisions or change candidate reviews."
    )

    if "recruiter_chat_history" not in st.session_state:
        st.session_state.recruiter_chat_history = []

    if st.button("Clear Chat", key="clear_recruiter_chat"):
        st.session_state.recruiter_chat_history = []
        st.rerun()

    job_options = {"General recruiter questions": None, **_job_options(jobs)}
    selected_job_label = st.selectbox(
        "Optional job context",
        list(job_options),
        key="recruiter_chat_job",
    )
    selected_job_id = job_options[selected_job_label]
    if "recruiter_chat_context" not in st.session_state:
        st.session_state.recruiter_chat_context = selected_job_id
    elif st.session_state.recruiter_chat_context != selected_job_id:
        st.session_state.recruiter_chat_context = selected_job_id
        st.session_state.recruiter_chat_history = []
        st.info("Chat history was cleared because the job context changed.")
    if selected_job_id is not None:
        st.info(f"Chat is scoped to: {selected_job_label}")
    else:
        st.info("Chat is using general recruiter context.")

    for message in st.session_state.recruiter_chat_history:
        role = message.get("role")
        with st.chat_message("user" if role == "recruiter" else "assistant"):
            st.markdown(message.get("content", ""))
            if role == "assistant":
                _render_chat_evidence(message.get("evidence"))

    with st.form("recruiter_chat_form", clear_on_submit=True):
        message = st.text_area(
            "Question",
            placeholder=(
                "Ask about candidates, matches, skills, evidence, or reviews..."
            ),
            height=100,
        )
        submitted = st.form_submit_button("Send", type="primary")

    if not submitted:
        return
    if not message.strip():
        st.error("Enter a question for the recruiter AI.")
        return

    st.session_state.recruiter_chat_history.append(
        {"role": "recruiter", "content": message.strip()}
    )
    try:
        with st.spinner("Hirent AI is reviewing grounded backend data..."):
            response = client.chat_with_recruiter(
                message.strip(), job_id=selected_job_id
            )
    except APIClientError:
        st.session_state.recruiter_chat_history.append(
            {
                "role": "assistant",
                "content": "The recruiter AI is currently unavailable. Please try again.",
                "evidence": [],
            }
        )
        st.error("The recruiter AI is currently unavailable. Please try again.")
        return

    answer = response.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        st.session_state.recruiter_chat_history.append(
            {
                "role": "assistant",
                "content": "No response was returned. Please try again.",
                "evidence": [],
            }
        )
        st.error("No response was returned. Please try again.")
        return
    st.session_state.recruiter_chat_history.append(
        {
            "role": "assistant",
            "content": answer,
            "evidence": response.get("evidence", []),
        }
    )
    st.rerun()


def _render_match_explanation(explanation: dict) -> None:
    st.markdown(f"**Backend match score:** {explanation.get('match_score', 'Unavailable')}")
    if explanation.get("summary"):
        st.write(explanation["summary"])

    component_scores = explanation.get("component_scores")
    if isinstance(component_scores, dict) and component_scores:
        st.caption("Backend component scores")
        st.dataframe(
            [{"Component": key, "Score": value} for key, value in component_scores.items()],
            use_container_width=True,
            hide_index=True,
        )

    for heading, field in (
        ("Strengths", "strengths"),
        ("Gaps", "gaps"),
        ("Evidence", "evidence"),
    ):
        items = explanation.get(field)
        if not isinstance(items, list) or not items:
            continue
        st.markdown(f"**{heading}**")
        for item in items:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if text:
                source = item.get("source")
                suffix = f" ({source})" if source else ""
                st.markdown(f"- {text}{suffix}")


def _render_matching(client: APIClient, jobs: list[dict]) -> None:
    st.title("Matching")
    st.write(
        "Process profiles, index records, and run backend-generated candidate-job matches."
    )
    if not jobs:
        st.info("No jobs have been created yet.")
        return

    options = _job_options(jobs)
    selected_label = st.selectbox("Select a job", list(options), key="matching_job")
    selected_job_id = int(options[selected_label]["id"])
    try:
        selected_job = client.get_job(selected_job_id)
        associated_candidates = client.get_job_candidates(selected_job_id)
    except APIClientError:
        st.error(BACKEND_ERROR_MESSAGE)
        return

    st.subheader(selected_job.get("title", "Untitled job"))
    st.caption(f"Candidates associated with this job: {len(associated_candidates)}")
    st.caption(
        "Scores and explanations below are generated by the backend matching system. "
        "They are decision support only; the recruiter remains the final decision maker."
    )

    job_actions = st.columns(2)
    if job_actions[0].button("Process Job", key=f"process_job_{selected_job_id}"):
        try:
            with st.spinner("Processing job requirements..."):
                client.process_job(selected_job_id)
            client.get_job(selected_job_id)
            st.success("Job processed successfully.")
        except APIClientError as error:
            st.error(str(error))
    if job_actions[1].button("Index Job", key=f"index_job_{selected_job_id}"):
        try:
            with st.spinner("Indexing job for search and matching..."):
                client.index_job(selected_job_id)
            client.get_job(selected_job_id)
            st.success("Job indexed successfully.")
        except APIClientError as error:
            st.error(str(error))

    if not associated_candidates:
        st.info("No candidates are associated with this job.")
        return

    st.subheader("Associated Candidates")
    for association in associated_candidates:
        candidate = _candidate_from_association(association)
        candidate_id = association.get("candidate_id")
        if not isinstance(candidate_id, int):
            st.warning("A candidate association is missing a valid candidate ID.")
            continue
        candidate_name = candidate.get("name", "Unknown candidate")
        with st.container(border=True):
            st.markdown(f"**{candidate_name}** · Candidate ID: `{candidate_id}`")
            st.caption(
                f"Location: {candidate.get('location') or 'Not provided'} | "
                f"Current score: {association.get('match_score', 'Not matched')} | "
                f"Status: {association.get('status', 'new')}"
            )
            actions = st.columns(4)
            if actions[0].button("Process", key=f"process_candidate_{candidate_id}"):
                try:
                    with st.spinner(f"Processing {candidate_name}..."):
                        client.process_candidate(candidate_id)
                    client.list_candidates()
                    client.get_job_candidates(selected_job_id)
                    st.success(f"{candidate_name} processed.")
                except APIClientError as error:
                    st.error(str(error))
            if actions[1].button("Index", key=f"index_candidate_{candidate_id}"):
                try:
                    with st.spinner(f"Indexing {candidate_name}..."):
                        client.index_candidate(candidate_id)
                    client.list_candidates()
                    client.get_job_candidates(selected_job_id)
                    st.success(f"{candidate_name} indexed.")
                except APIClientError as error:
                    st.error(str(error))
            if actions[2].button("Match", key=f"match_candidate_{selected_job_id}_{candidate_id}"):
                try:
                    with st.spinner(f"Matching {candidate_name}..."):
                        client.match_candidate(selected_job_id, candidate_id)
                    client.get_job_candidates(selected_job_id)
                    explanation = client.get_match_result(selected_job_id, candidate_id)
                    st.success(f"Match completed for {candidate_name}.")
                    _render_match_explanation(explanation)
                except APIClientError as error:
                    st.error(str(error))
            if actions[3].button(
                "Explain", key=f"explain_candidate_{selected_job_id}_{candidate_id}"
            ):
                try:
                    explanation = client.get_match_result(selected_job_id, candidate_id)
                    _render_match_explanation(explanation)
                except APIClientError as error:
                    st.error(str(error))

    st.subheader("Match All Candidates")
    if st.button("Run Matching for All Candidates", type="primary"):
        try:
            with st.status("Running backend matching...", expanded=False) as status:
                results = client.match_all_candidates(selected_job_id)
                client.get_job_candidates(selected_job_id)
                status.update(label="Batch matching complete", state="complete")
            st.success(f"Backend matching completed for {len(results)} candidate(s).")
            st.info("No ranking, recommendation, or hiring decision was made in the frontend.")
            explanations = client.get_match_explanations(selected_job_id)
            if explanations:
                st.subheader("Backend Match Explanations")
                for explanation in explanations:
                    candidate_id = explanation.get("candidate_id")
                    candidate_name = next(
                        (
                            _candidate_from_association(item).get("name", "Unknown candidate")
                            for item in associated_candidates
                            if item.get("candidate_id") == candidate_id
                        ),
                        "Unknown candidate",
                    )
                    with st.expander(f"{candidate_name} · Candidate ID {candidate_id}"):
                        _render_match_explanation(explanation)
        except APIClientError as error:
            st.error(str(error))


def main() -> None:
    st.set_page_config(page_title="Recruiter Dashboard | Hirent", page_icon="H", layout="wide")
    apply_styles()
    client = APIClient()

    st.sidebar.markdown(
        f'<div class="brand-name">{BRAND_NAME}</div>', unsafe_allow_html=True
    )
    st.sidebar.caption("Recruitment Intelligence")
    st.sidebar.divider()
    page = st.sidebar.radio(
        "Navigation",
        [
            "Dashboard",
            "Jobs",
            "Upload Candidates",
            "Matching",
            "Candidate Search",
            "Compare Candidates",
            "Review Candidates",
            "Recruiter Chat",
            "Candidates",
        ],
    )

    try:
        jobs, candidates, reviews_by_job = _load_dashboard_data(
            client, include_reviews=page == "Dashboard"
        )
    except APIClientError:
        st.error(BACKEND_ERROR_MESSAGE)
        return

    if page == "Dashboard":
        _render_dashboard(client, jobs, candidates, reviews_by_job)
    elif page == "Jobs":
        _render_jobs(client, jobs)
    elif page == "Upload Candidates":
        _render_upload_candidates(client, jobs)
    elif page == "Matching":
        _render_matching(client, jobs)
    elif page == "Candidate Search":
        _render_candidate_search(client, candidates)
    elif page == "Compare Candidates":
        _render_candidate_comparison(client, jobs)
    elif page == "Review Candidates":
        _render_review_candidates(client, jobs)
    elif page == "Recruiter Chat":
        _render_recruiter_chat(client, jobs)
    else:
        st.title("Candidates")
        st.write("Candidate records are available through the dashboard job views.")
        if candidates:
            st.dataframe(
                [
                    {
                        "Candidate": candidate.get("name", "Unnamed Candidate"),
                        "Location": candidate.get("location") or "Not provided",
                        "Created": _format_date(candidate.get("created_at")),
                    }
                    for candidate in candidates
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No candidates have been uploaded yet.")


if __name__ == "__main__":
    main()
