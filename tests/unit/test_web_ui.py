"""
Tests for the web UI endpoints added to fix issue #423.

Covers:
- GET / renders the timeline HTML page
- GET /api/tags/suggestions returns an empty list when no orchestrator is set
- GET /api/tags/suggestions returns an empty list for empty query
- Static assets are mounted at /static
"""

import pytest
from fastapi.testclient import TestClient

from klabautermann.api.server import app, set_orchestrator


@pytest.fixture()
def client():
    """Return a synchronous TestClient with the app under test."""
    # Ensure no orchestrator is set so tests are isolated
    set_orchestrator(None)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    set_orchestrator(None)


class TestTimelinePage:
    def test_root_returns_html(self, client: TestClient) -> None:
        """GET / should render the timeline template and return HTML."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_root_contains_log_heading(self, client: TestClient) -> None:
        """Rendered page should include the Captain's Log heading."""
        resp = client.get("/")
        assert "Captain" in resp.text

    def test_root_links_stylesheet(self, client: TestClient) -> None:
        """Rendered page should reference the nautical CSS stylesheet."""
        resp = client.get("/")
        assert "/static/css/style.css" in resp.text

    def test_root_links_tags_js(self, client: TestClient) -> None:
        """Rendered page should reference the tags.js script."""
        resp = client.get("/")
        assert "/static/js/tags.js" in resp.text

    def test_root_contains_textarea(self, client: TestClient) -> None:
        """Rendered page should include the entry textarea for input."""
        resp = client.get("/")
        assert "entry-input" in resp.text

    def test_root_contains_autocomplete_div(self, client: TestClient) -> None:
        """Rendered page should include the tag-autocomplete container."""
        resp = client.get("/")
        assert "tag-autocomplete" in resp.text

    def test_root_autocomplete_starts_hidden(self, client: TestClient) -> None:
        """The autocomplete dropdown must start with the hidden attribute set."""
        resp = client.get("/")
        assert 'hidden' in resp.text


class TestTagSuggestionsEndpoint:
    def test_suggestions_without_orchestrator_returns_empty(
        self, client: TestClient
    ) -> None:
        """Without a configured orchestrator the endpoint degrades to empty list."""
        resp = client.get("/api/tags/suggestions", params={"q": "jo"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_suggestions_missing_query_param_returns_422(
        self, client: TestClient
    ) -> None:
        """Calling the endpoint without a query string should return 422."""
        resp = client.get("/api/tags/suggestions")
        assert resp.status_code == 422

    def test_suggestions_returns_json_list(self, client: TestClient) -> None:
        """The response body must be a JSON array."""
        resp = client.get("/api/tags/suggestions", params={"q": "abc"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_suggestions_content_type_is_json(self, client: TestClient) -> None:
        """Response content-type should be application/json."""
        resp = client.get("/api/tags/suggestions", params={"q": "test"})
        assert "application/json" in resp.headers["content-type"]
