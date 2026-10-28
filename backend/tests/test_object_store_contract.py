"""Synthetic object-store contracts; no real network or application DB is used."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError

from app.adapters.storage.object_store import ObjectStore, _SETTINGS


def _fake_minio(monkeypatch, *, fail_at=None, bucket_exists=True):
    created = []

    class Client:
        def __init__(self, endpoint, **options):
            self.endpoint = endpoint
            self.options = options
            self.objects = {}
            self.calls = []
            self.responses = []
            created.append(self)
            if fail_at == "constructor":
                raise RuntimeError("synthetic constructor failure")

        def bucket_exists(self, bucket):
            self.calls.append(("bucket_exists", bucket))
            if fail_at == "bucket_exists":
                raise RuntimeError("synthetic unreachable object store")
            return bucket_exists

        def make_bucket(self, bucket):
            self.calls.append(("make_bucket", bucket))
            if fail_at == "make_bucket":
                raise RuntimeError("synthetic bucket creation failure")

        def put_object(self, bucket, key, data, *, length, content_type):
            content = data.read()
            assert len(content) == length
            self.objects[(bucket, key)] = content

        def get_object(self, bucket, key):
            self.calls.append(("get_object", bucket, key))
            state = SimpleNamespace(closed=False, released=False)

            def read():
                if fail_at == "read":
                    raise RuntimeError("synthetic streaming read failure")
                return self.objects[(bucket, key)]

            def close():
                state.closed = True

            def release_conn():
                state.released = True

            state.read, state.close, state.release_conn = read, close, release_conn
            self.responses.append(state)
            return state

        def remove_object(self, bucket, key):
            self.calls.append(("remove_object", bucket, key))
            self.objects.pop((bucket, key), None)

    # Real urllib3 pool creation is local configuration only. Any unexpected
    # network attempt fails the test instead of contacting an external service.
    def no_network(*args, **kwargs):
        raise AssertionError("Network calls are forbidden in this contract test")

    monkeypatch.setattr("minio.Minio", Client)
    monkeypatch.setattr("urllib3.PoolManager.request", no_network)
    monkeypatch.setattr("urllib3.PoolManager.urlopen", no_network)
    return created


def test_minio_http_configuration_has_bounded_timeout_retries_and_tls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "synthetic-ca.pem"))
    created = _fake_minio(monkeypatch)
    store = ObjectStore()
    assert store.backend == "minio"
    client = created[0]
    assert client.endpoint == _SETTINGS.MINIO_ENDPOINT
    assert client.options["access_key"] == _SETTINGS.MINIO_ACCESS_KEY
    assert client.options["secret_key"] == _SETTINGS.MINIO_SECRET_KEY
    assert client.options["secure"] == _SETTINGS.MINIO_SECURE
    config = client.options["http_client"].connection_pool_kw
    timeout = config["timeout"]
    assert timeout.connect_timeout == 2 and timeout.total == 7
    timeout.start_connect()
    assert 0 < timeout.read_timeout <= 5
    retries = config["retries"]
    assert (retries.total, retries.connect, retries.read, retries.status, retries.redirect) == (1, 1, 1, 1, 0)
    assert retries.respect_retry_after_header is False
    assert retries.get_backoff_time() == 0
    assert set(retries.status_forcelist) == {500, 502, 503, 504}
    retried = retries.increment("GET", "/", error=ConnectTimeoutError("synthetic timeout"))
    assert retried.total == 0
    with pytest.raises(MaxRetryError):
        retried.increment("GET", "/", error=ConnectTimeoutError("synthetic timeout"))
    assert config["cert_reqs"] == "CERT_REQUIRED"
    assert config["ca_certs"] == str(tmp_path / "synthetic-ca.pem")


@pytest.mark.parametrize("fail_at", ["constructor", "bucket_exists", "make_bucket"])
def test_bootstrap_failure_keeps_real_local_uri_roundtrip(monkeypatch, tmp_path, fail_at):
    monkeypatch.chdir(tmp_path)
    _fake_minio(monkeypatch, fail_at=fail_at, bucket_exists=False)
    store = ObjectStore()
    assert store.backend == "local"
    content = b"synthetic original bytes; not business evidence"
    uri = store.put_object("synthetic-original.txt", content, "text/plain")
    assert uri.startswith("local://")
    assert (tmp_path / "storage/synthetic-original.txt").read_bytes() == content
    assert store.get_object(uri) == content
    assert store.get_object("synthetic-original.txt") == content
    assert store.get_object("missing-original.txt") is None
    assert store.presign(uri) == "/api/v1/regulations/file/synthetic-original.txt"
    assert store.delete_object(uri) is True
    assert store.get_object(uri) is None
    assert store.delete_object(uri) is False


def test_successful_minio_keeps_uri_and_releases_stream(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    created = _fake_minio(monkeypatch, bucket_exists=False)
    store = ObjectStore()
    content = b"synthetic object bytes"
    uri = store.put_object("nested/synthetic-original.txt", content, "text/plain")
    assert uri == f"minio://{_SETTINGS.MINIO_BUCKET}/nested/synthetic-original.txt"
    assert store.get_object(uri) == content
    assert created[0].responses[0].closed and created[0].responses[0].released
    assert ("make_bucket", _SETTINGS.MINIO_BUCKET) in created[0].calls
    assert ("get_object", _SETTINGS.MINIO_BUCKET, "nested/synthetic-original.txt") in created[0].calls


def test_legacy_local_uri_stays_local_after_minio_recovers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _fake_minio(monkeypatch, fail_at="bucket_exists")
    local = ObjectStore()
    content = b"synthetic retained original"
    uri = local.put_object("retained-original.txt", content)
    created = _fake_minio(monkeypatch)
    recovered = ObjectStore()
    assert recovered.backend == "minio"
    assert recovered.get_object(uri) == content
    assert not any(call[0] == "get_object" for call in created[0].calls)


def test_failed_stream_returns_none_and_releases_connection(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    created = _fake_minio(monkeypatch, fail_at="read")
    store = ObjectStore()
    assert store.get_object("minio://synthetic-bucket/unavailable.txt") is None
    response = created[0].responses[0]
    assert response.closed and response.released
