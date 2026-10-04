import json
from unittest.mock import MagicMock, patch
from urllib import error

import pytest

from frontend.api_client import APIClient, APIClientError


def mocked_response(payload: object) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return response


def test_successful_api_response() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response([{"id": 1, "title": "Backend Engineer"}]),
    ):
        jobs = APIClient("http://backend.test").list_jobs()

    assert jobs == [{"id": 1, "title": "Backend Engineer"}]


def test_http_error_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/api/jobs", 500, "Server Error", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 500"):
            APIClient().list_jobs()


def test_connection_error_is_safe() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        side_effect=error.URLError("connection refused"),
    ):
        with pytest.raises(APIClientError, match="Backend is unavailable"):
            APIClient().list_candidates()


def test_basic_recruiter_chat_request() -> None:
    payload = {"answer": "Asha has Python experience.", "candidate_ids": [7], "evidence": []}
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ) as urlopen:
        assert APIClient("http://backend.test").chat_with_recruiter(
            "Who has Python experience?"
        ) == payload

    sent_request = urlopen.call_args.args[0]
    assert sent_request.method == "POST"
    assert sent_request.full_url == "http://backend.test/api/recruiter/chat"
    assert json.loads(sent_request.data) == {"message": "Who has Python experience?"}


def test_recruiter_chat_with_job_and_evidence() -> None:
    payload = {
        "answer": "The match is supported by FastAPI experience.",
        "candidate_ids": [7],
        "evidence": [
            {
                "candidate_id": 7,
                "candidate_name": "Asha Rao",
                "source": "resume",
                "text": "Built FastAPI services",
            }
        ],
    }
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ) as urlopen:
        assert APIClient().chat_with_recruiter("Why this score?", job_id=4) == payload

    assert json.loads(urlopen.call_args.args[0].data) == {
        "message": "Why this score?",
        "job_id": 4,
    }


def test_recruiter_chat_connection_failure_is_safe() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        side_effect=error.URLError("connection refused"),
    ):
        with pytest.raises(APIClientError, match="Backend is unavailable"):
            APIClient().chat_with_recruiter("Who is shortlisted?")


def test_recruiter_chat_http_503_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/api/recruiter/chat", 503, "Unavailable", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 503"):
            APIClient().chat_with_recruiter("Summarize candidates")


def test_recruiter_chat_malformed_json_is_safe() -> None:
    response = mocked_response({})
    response.read.return_value = b"{invalid"
    with patch("frontend.api_client.request.urlopen", return_value=response):
        with pytest.raises(APIClientError, match="invalid response"):
            APIClient().chat_with_recruiter("Summarize candidates")


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "unexpected chat response"),
        ({"answer": "Answer", "candidate_ids": ["7"], "evidence": []}, "chat candidates"),
        (
            {
                "answer": "Answer",
                "candidate_ids": [],
                "evidence": [{"candidate_id": 7}],
            },
            "chat evidence",
        ),
    ],
)
def test_recruiter_chat_unexpected_response_shape_is_safe(
    payload: object, message: str
) -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        with pytest.raises(APIClientError, match=message):
            APIClient().chat_with_recruiter("Summarize candidates")


def test_malformed_response_is_rejected() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"unexpected": "object"}),
    ):
        with pytest.raises(APIClientError, match="unexpected list response"):
            APIClient().list_jobs()


def test_invalid_json_is_rejected() -> None:
    response = mocked_response({})
    response.read.return_value = b"{not-json"
    with patch("frontend.api_client.request.urlopen", return_value=response):
        with pytest.raises(APIClientError, match="invalid response"):
            APIClient().list_jobs()


def test_create_job() -> None:
    response = mocked_response({"id": 3, "title": "Data Engineer"})
    with patch("frontend.api_client.request.urlopen", return_value=response) as urlopen:
        job = APIClient("http://backend.test").create_job(
            "Data Engineer", "Build reliable data systems"
        )

    assert job["id"] == 3
    sent_request = urlopen.call_args.args[0]
    assert sent_request.method == "POST"
    assert json.loads(sent_request.data) == {
        "title": "Data Engineer",
        "description": "Build reliable data systems",
    }


def test_upload_resume() -> None:
    response = mocked_response({"id": 8, "name": "Asha Rao"})
    with patch("frontend.api_client.request.urlopen", return_value=response) as urlopen:
        candidate = APIClient("http://backend.test").upload_resume(
            "asha.pdf", b"%PDF-resume"
        )

    assert candidate["id"] == 8
    sent_request = urlopen.call_args.args[0]
    assert sent_request.method == "POST"
    assert sent_request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="asha.pdf"' in sent_request.data
    assert b"%PDF-resume" in sent_request.data


def test_associate_candidate() -> None:
    response = mocked_response({"job_id": 3, "candidate_id": 8, "status": "new"})
    with patch("frontend.api_client.request.urlopen", return_value=response) as urlopen:
        association = APIClient("http://backend.test").associate_candidate(3, 8)

    assert association["status"] == "new"
    sent_request = urlopen.call_args.args[0]
    assert sent_request.method == "POST"
    assert sent_request.full_url.endswith("/api/jobs/3/candidates/8")


def test_create_job_http_failure_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/api/jobs", 422, "Validation Error", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 422"):
            APIClient().create_job("", "")


def test_upload_failure_is_safe() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        side_effect=error.URLError("connection refused"),
    ):
        with pytest.raises(APIClientError, match="Backend is unavailable"):
            APIClient().upload_resume("resume.pdf", b"pdf")


def test_process_job() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"job_title": "Engineer", "required_skills": ["Python"]}),
    ) as urlopen:
        result = APIClient().process_job(4)
    assert result["job_title"] == "Engineer"
    assert urlopen.call_args.args[0].full_url.endswith("/api/jobs/4/process")


def test_process_candidate() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"candidate_id": 9, "name": "Asha"}),
    ) as urlopen:
        result = APIClient().process_candidate(9)
    assert result["candidate_id"] == 9
    assert urlopen.call_args.args[0].full_url.endswith("/api/candidates/9/process")


def test_index_job_and_candidate() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        side_effect=[
            mocked_response({"job_id": 4, "status": "indexed"}),
            mocked_response({"candidate_id": 9, "status": "indexed"}),
        ],
    ) as urlopen:
        assert APIClient().index_job(4)["status"] == "indexed"
        assert APIClient().index_candidate(9)["status"] == "indexed"
    assert urlopen.call_count == 2


def test_match_one_candidate() -> None:
    payload = {"job_id": 4, "candidate_id": 9, "match_score": 82}
    with patch("frontend.api_client.request.urlopen", return_value=mocked_response(payload)):
        assert APIClient().match_candidate(4, 9)["match_score"] == 82


def test_match_all_candidates() -> None:
    payload = [{"job_id": 4, "candidate_id": 9, "match_score": 82}]
    with patch("frontend.api_client.request.urlopen", return_value=mocked_response(payload)):
        assert APIClient().match_all_candidates(4) == payload


def test_get_match_result_and_explanations() -> None:
    explanation = {"job_id": 4, "candidate_id": 9, "match_score": 82}
    with patch(
        "frontend.api_client.request.urlopen",
        side_effect=[
            mocked_response(explanation),
            mocked_response([explanation]),
        ],
    ):
        assert APIClient().get_match_result(4, 9) == explanation
        assert APIClient().get_match_explanations(4) == [explanation]


def test_match_list_shape_failure_is_safe() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"unexpected": "object"}),
    ):
        with pytest.raises(APIClientError, match="unexpected match list response"):
            APIClient().match_all_candidates(4)


def test_basic_candidate_search() -> None:
    payload = {
        "results": [
            {
                "candidate_id": 7,
                "name": "Asha Rao",
                "similarity_score": 91.2,
                "evidence": "FastAPI experience",
            }
        ]
    }
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ) as urlopen:
        results = APIClient("http://backend.test").search_candidates(
            "Python backend developer"
        )

    assert results == payload["results"]
    assert (
        urlopen.call_args.args[0].full_url
        == "http://backend.test/api/candidates/search?q=Python+backend+developer&limit=10"
    )


def test_candidate_search_with_all_filters() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"results": []}),
    ) as urlopen:
        assert APIClient().search_candidates(
            "backend developer",
            limit=25,
            skills=["Python", "FastAPI"],
            min_experience_years=3.5,
            location="New York",
        ) == []

    query = urlopen.call_args.args[0].full_url
    assert "q=backend+developer" in query
    assert "limit=25" in query
    assert "skills=Python" in query
    assert "skills=FastAPI" in query
    assert "min_experience_years=3.5" in query
    assert "location=New+York" in query


def test_candidate_search_omits_empty_optional_filters() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"results": []}),
    ) as urlopen:
        APIClient().search_candidates(
            "python", skills=[], min_experience_years=None, location=""
        )

    query = urlopen.call_args.args[0].full_url
    assert query.endswith("?q=python&limit=10")
    assert "skills=" not in query
    assert "min_experience_years" not in query
    assert "location=" not in query


def test_candidate_search_empty_results() -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response({"results": []}),
    ):
        assert APIClient().search_candidates("unmatched candidate") == []


def test_candidate_search_http_failure_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/api/candidates/search", 422, "Validation Error", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 422"):
            APIClient().search_candidates("")


def test_candidate_search_malformed_response_is_safe() -> None:
    response = mocked_response({})
    response.read.return_value = b"{invalid"
    with patch("frontend.api_client.request.urlopen", return_value=response):
        with pytest.raises(APIClientError, match="invalid response"):
            APIClient().search_candidates("python")


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "unexpected search response"),
        ({"results": {}}, "unexpected search response"),
        ({"results": ["not an object"]}, "unexpected search result"),
    ],
)
def test_candidate_search_unexpected_response_shape_is_safe(
    payload: object, message: str
) -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        with pytest.raises(APIClientError, match=message):
            APIClient().search_candidates("python")


def test_compare_two_candidates_preserves_order() -> None:
    payload = {
        "job_id": 4,
        "job_title": "Backend Engineer",
        "candidates": [
            {"candidate_id": 9, "candidate_name": "Asha", "match_score": 80},
            {"candidate_id": 7, "candidate_name": "Ravi", "match_score": 75},
        ],
    }
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ) as urlopen:
        result = APIClient("http://backend.test").compare_candidates(4, [9, 7])

    assert [item["candidate_id"] for item in result["candidates"]] == [9, 7]
    assert (
        urlopen.call_args.args[0].full_url
        == "http://backend.test/api/jobs/4/compare?candidate_ids=9&candidate_ids=7"
    )


def test_compare_five_candidates() -> None:
    candidate_ids = [1, 2, 3, 4, 5]
    payload = {"job_id": 4, "job_title": "Engineer", "candidates": []}
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ) as urlopen:
        assert APIClient().compare_candidates(4, candidate_ids) == payload

    assert urlopen.call_args.args[0].full_url.count("candidate_ids=") == 5


def test_compare_http_failure_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/api/jobs/4/compare", 422, "Validation Error", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 422"):
            APIClient().compare_candidates(4, [1, 2])


def test_compare_malformed_json_is_safe() -> None:
    response = mocked_response({})
    response.read.return_value = b"{invalid"
    with patch("frontend.api_client.request.urlopen", return_value=response):
        with pytest.raises(APIClientError, match="invalid response"):
            APIClient().compare_candidates(4, [1, 2])


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "unexpected comparison response"),
        ({"candidates": {}}, "unexpected comparison result"),
        ({"candidates": ["invalid"]}, "unexpected comparison result"),
        ({"candidates": []}, None),
    ],
)
def test_compare_response_shape_is_safe(payload: object, message: str | None) -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        if message:
            with pytest.raises(APIClientError, match=message):
                APIClient().compare_candidates(4, [1, 2])
        else:
            assert APIClient().compare_candidates(4, [1, 2]) == payload


def test_get_candidate_review() -> None:
    payload = {
        "job_id": 4,
        "candidate_id": 9,
        "status": "reviewing",
        "recruiter_notes": "Follow up",
    }
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        assert APIClient().get_candidate_review(4, 9) == payload


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"status": "shortlisted"}, {"status": "shortlisted"}),
        ({"recruiter_notes": "Call next week"}, {"recruiter_notes": "Call next week"}),
        (
            {"status": "interview", "recruiter_notes": "Panel review"},
            {"status": "interview", "recruiter_notes": "Panel review"},
        ),
    ],
)
def test_update_candidate_review_partial_payload(
    kwargs: dict[str, str], expected: dict[str, str]
) -> None:
    response_payload = {
        "job_id": 4,
        "candidate_id": 9,
        "status": kwargs.get("status", "reviewing"),
        "recruiter_notes": kwargs.get("recruiter_notes"),
    }
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(response_payload),
    ) as urlopen:
        assert APIClient().update_candidate_review(4, 9, **kwargs) == response_payload

    sent_request = urlopen.call_args.args[0]
    assert sent_request.method == "PATCH"
    assert json.loads(sent_request.data) == expected


def test_get_job_reviews() -> None:
    payload = [
        {
            "job_id": 4,
            "candidate_id": 9,
            "candidate_name": "Asha",
            "status": "new",
            "recruiter_notes": None,
            "match_score": 80,
        }
    ]
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        assert APIClient().get_job_reviews(4) == payload


def test_review_http_failure_is_safe() -> None:
    http_error = error.HTTPError(
        "http://backend.test/review", 404, "Not Found", {}, None
    )
    with patch("frontend.api_client.request.urlopen", side_effect=http_error):
        with pytest.raises(APIClientError, match="HTTP 404"):
            APIClient().get_candidate_review(4, 9)


def test_review_malformed_json_is_safe() -> None:
    response = mocked_response({})
    response.read.return_value = b"{invalid"
    with patch("frontend.api_client.request.urlopen", return_value=response):
        with pytest.raises(APIClientError, match="invalid response"):
            APIClient().update_candidate_review(4, 9, status="reviewing")


@pytest.mark.parametrize("payload", [[], {"job_id": 4, "candidate_id": 9}])
def test_review_unexpected_response_shape_is_safe(payload: object) -> None:
    with patch(
        "frontend.api_client.request.urlopen",
        return_value=mocked_response(payload),
    ):
        with pytest.raises(APIClientError, match="unexpected .* response"):
            APIClient().get_candidate_review(4, 9)
