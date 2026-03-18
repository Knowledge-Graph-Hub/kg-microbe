"""Mock functions for testing download utilities."""


def mocked_requests_get(*args, **kwargs):
    """Mock the requests.get method."""

    class MockResponse:

        """Mock HTTP response object for testing."""

        def __init__(self, json_data, status_code):
            """Initialize mock response with JSON data and status code."""
            self.json_data = json_data
            self.status_code = status_code

        def json(self):
            """Return mock JSON data."""
            return self.json_data

    if args[0] == "https://test_url.org/test_1234.pdf":
        return MockResponse({}, 200)

    return MockResponse(None, 404)
