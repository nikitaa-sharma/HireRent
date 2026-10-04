"""Small read-only HTTP client for the Hirent FastAPI backend."""

from __future__ import annotations

import json
import os
import uuid
from urllib import error, request
from urllib.parse import urlencode


class APIClientError(RuntimeError):
    """A user-safe backend communication or response error."""


class APIClient:
    """HTTP client for the recruiter dashboard workflows."""

    def __init__(self, base_url: str | None = None, timeout: float = 5.0) -> None:
        self.base_url = (
            base_url or os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> object:
        headers = {"Content-Type": content_type} if content_type else {}
        http_request = request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as api_error:
            detail = ""
            try:
                error_payload = json.loads(api_error.read().decode("utf-8"))
                if isinstance(error_payload, dict) and isinstance(
                    error_payload.get("detail"), str
                ):
                    detail = f": {error_payload['detail']}"
            except (AttributeError, json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
            raise APIClientError(
                f"Backend request failed with HTTP {api_error.code}{detail}"
            ) from api_error
        except (error.URLError, TimeoutError, OSError) as connection_error:
            raise APIClientError("Backend is unavailable") from connection_error
        try:
            return json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as response_error:
            raise APIClientError("Backend returned an invalid response") from response_error

    def _list(self, path: str) -> list[dict]:
        payload = self._request(path)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise APIClientError("Backend returned an unexpected list response")
        return payload

    def _object(self, path: str) -> dict:
        payload = self._request(path)
        if not isinstance(payload, dict):
            raise APIClientError("Backend returned an unexpected object response")
        return payload

    def _json_request(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        response = self._request(
            path, method="POST", body=body, content_type="application/json"
        )
        if not isinstance(response, dict):
            raise APIClientError("Backend returned an unexpected object response")
        return response

    def chat_with_recruiter(self, message: str, job_id: int | None = None) -> dict:
        payload: dict[str, object] = {"message": message}
        if job_id is not None:
            payload["job_id"] = job_id
        response = self._json_request("/api/recruiter/chat", payload)
        if not isinstance(response.get("answer"), str) or not response["answer"].strip():
            raise APIClientError("Backend returned an unexpected chat response")
        candidate_ids = response.get("candidate_ids", [])
        evidence = response.get("evidence", [])
        if not isinstance(candidate_ids, list) or not all(
            isinstance(candidate_id, int) and not isinstance(candidate_id, bool)
            for candidate_id in candidate_ids
        ):
            raise APIClientError("Backend returned an unexpected chat candidates response")
        if not isinstance(evidence, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("candidate_id"), int)
            and isinstance(item.get("candidate_name"), str)
            and isinstance(item.get("source"), str)
            and isinstance(item.get("text"), str)
            for item in evidence
        ):
            raise APIClientError("Backend returned an unexpected chat evidence response")
        return response

    def _post_object(self, path: str) -> dict:
        response = self._request(path, method="POST")
        if not isinstance(response, dict):
            raise APIClientError("Backend returned an unexpected object response")
        return response

    def health(self) -> dict:
        return self._object("/health")

    def list_jobs(self) -> list[dict]:
        return self._list("/api/jobs")

    def create_job(self, title: str, description: str) -> dict:
        return self._json_request(
            "/api/jobs", {"title": title, "description": description}
        )

    def get_job(self, job_id: int) -> dict:
        return self._object(f"/api/jobs/{job_id}")

    def list_candidates(self) -> list[dict]:
        return self._list("/api/candidates")

    def search_candidates(
        self,
        query: str,
        *,
        limit: int = 10,
        skills: list[str] | None = None,
        min_experience_years: float | None = None,
        location: str | None = None,
    ) -> list[dict]:
        params: list[tuple[str, str | int | float]] = [("q", query), ("limit", limit)]
        params.extend(("skills", skill) for skill in (skills or []) if skill)
        if min_experience_years is not None:
            params.append(("min_experience_years", min_experience_years))
        if location:
            params.append(("location", location))

        payload = self._request(
            f"/api/candidates/search?{urlencode(params, doseq=True)}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise APIClientError("Backend returned an unexpected search response")
        results = payload["results"]
        if not all(isinstance(result, dict) for result in results):
            raise APIClientError("Backend returned an unexpected search result")
        return results

    def get_candidate(self, candidate_id: int) -> dict:
        return self._object(f"/api/candidates/{candidate_id}")

    def get_job_candidates(self, job_id: int) -> list[dict]:
        return self._list(f"/api/jobs/{job_id}/candidates")

    def get_job_reviews(self, job_id: int) -> list[dict]:
        return self._list(f"/api/jobs/{job_id}/reviews")

    def get_candidate_review(self, job_id: int, candidate_id: int) -> dict:
        payload = self._object(
            f"/api/jobs/{job_id}/candidates/{candidate_id}/review"
        )
        if not {"job_id", "candidate_id", "status"}.issubset(payload):
            raise APIClientError("Backend returned an unexpected review response")
        return payload

    def update_candidate_review(
        self,
        job_id: int,
        candidate_id: int,
        *,
        status: str | None = None,
        recruiter_notes: str | None = None,
    ) -> dict:
        payload: dict[str, str] = {}
        if status is not None:
            payload["status"] = status
        if recruiter_notes is not None:
            payload["recruiter_notes"] = recruiter_notes
        body = json.dumps(payload).encode("utf-8")
        response = self._request(
            f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
            method="PATCH",
            body=body,
            content_type="application/json",
        )
        if not isinstance(response, dict) or not {
            "job_id",
            "candidate_id",
            "status",
        }.issubset(response):
            raise APIClientError("Backend returned an unexpected review response")
        return response

    def upload_resume(self, filename: str, content: bytes) -> dict:
        boundary = f"----HirentBoundary{uuid.uuid4().hex}"
        boundary_bytes = boundary.encode("ascii")
        multipart_body = b"".join(
            (
                b"--" + boundary_bytes + b"\r\n",
                (
                    f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                ).encode("utf-8"),
                b"Content-Type: application/pdf\r\n\r\n",
                content,
                b"\r\n--" + boundary_bytes + b"--\r\n",
            )
        )
        response = self._request(
            "/api/candidates/upload-resume",
            method="POST",
            body=multipart_body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        if not isinstance(response, dict):
            raise APIClientError("Backend returned an unexpected upload response")
        return response

    def associate_candidate(self, job_id: int, candidate_id: int) -> dict:
        return self._post_object(f"/api/jobs/{job_id}/candidates/{candidate_id}")

    def process_job(self, job_id: int) -> dict:
        return self._post_object(f"/api/jobs/{job_id}/process")

    def process_candidate(self, candidate_id: int) -> dict:
        return self._post_object(f"/api/candidates/{candidate_id}/process")

    def index_job(self, job_id: int) -> dict:
        return self._post_object(f"/api/jobs/{job_id}/index")

    def index_candidate(self, candidate_id: int) -> dict:
        return self._post_object(f"/api/candidates/{candidate_id}/index")

    def match_candidate(self, job_id: int, candidate_id: int) -> dict:
        return self._post_object(
            f"/api/jobs/{job_id}/candidates/{candidate_id}/match"
        )

    def match_all_candidates(self, job_id: int) -> list[dict]:
        response = self._request(f"/api/jobs/{job_id}/match-candidates", method="POST")
        if not isinstance(response, list) or not all(
            isinstance(item, dict) for item in response
        ):
            raise APIClientError("Backend returned an unexpected match list response")
        return response

    def get_match_result(self, job_id: int, candidate_id: int) -> dict:
        return self._object(f"/api/jobs/{job_id}/candidates/{candidate_id}/match")

    def get_match_explanations(self, job_id: int) -> list[dict]:
        return self._list(f"/api/jobs/{job_id}/match-explanations")

    def compare_candidates(self, job_id: int, candidate_ids: list[int]) -> dict:
        params = [("candidate_ids", candidate_id) for candidate_id in candidate_ids]
        payload = self._request(
            f"/api/jobs/{job_id}/compare?{urlencode(params, doseq=True)}"
        )
        if not isinstance(payload, dict):
            raise APIClientError("Backend returned an unexpected comparison response")
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not all(
            isinstance(candidate, dict) for candidate in candidates
        ):
            raise APIClientError("Backend returned an unexpected comparison result")
        return payload
