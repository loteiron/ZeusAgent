"""Public security-tool downloads carry no ambient credentials or project data."""
import io

import pytest

from agent import secret_scope
from tools import tirith_security


@pytest.mark.parametrize("asset", ["checksums.txt", "tirith-x86_64-unknown-linux-gnu.tar.gz"])
def test_public_release_download_has_no_credentials_or_request_body(monkeypatch, tmp_path, asset):
    monkeypatch.setattr(secret_scope, "get_secret", lambda name: "test-only-ambient-token")
    requests = []

    def receive(request, *, timeout):
        requests.append(request)
        return io.BytesIO(b"test release bytes")

    monkeypatch.setattr(tirith_security.urllib.request, "urlopen", receive)
    url = f"https://github.com/sheeki03/tirith/releases/latest/download/{asset}"
    destination = tmp_path / asset
    tirith_security._download_file(url, str(destination))
    assert destination.read_bytes() == b"test release bytes"
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == url
    assert request.get_method() == "GET"
    assert request.data is None
    assert not {key.lower() for key, _ in request.header_items()} & {
        "authorization", "proxy-authorization", "cookie",
    }
