"""Tests for app/core/opa.py — the HTTP client that asks OPA (Open Policy
Agent) authorization decisions. No live OPA/docker in this sandbox (project
convention — see tests/test_default_seed.py's docstring for the same
constraint elsewhere): httpx.post is monkeypatched so `check_allow`'s
request/response handling and `authorize`'s fail-closed wrapping are both
exercised without a real network call. The Rego policy itself
(backend/policies/authz.rego) is verified separately via
backend/policies/authz_test.rego + `opa test`, which needs a real opa
binary this sandbox cannot download (see project memory).
"""
import uuid

import httpx
import pytest

from app.core import opa


class _FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        if isinstance(self._json_body, Exception):
            raise self._json_body
        return self._json_body


class _FakeUser:
    def __init__(self, role, tenant_id):
        self.id = uuid.uuid4()
        self.role = role
        self.tenant_id = tenant_id


# --- check_allow -------------------------------------------------------


def test_check_allow_true(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"result": True}))
    assert opa.check_allow({"subject": {}, "action": "read", "resource": {}}) is True


def test_check_allow_false(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"result": False}))
    assert opa.check_allow({}) is False


def test_check_allow_missing_result_key_is_deny(monkeypatch):
    # OPA omits "result" when the queried path is undefined (e.g. bundle
    # failed to load) — must be treated as deny, not an error.
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}))
    assert opa.check_allow({}) is False


def test_check_allow_non_dict_body_is_deny(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse([1, 2, 3]))
    assert opa.check_allow({}) is False


def test_check_allow_network_error_raises_opa_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    with pytest.raises(opa.OpaUnavailableError):
        opa.check_allow({})


def test_check_allow_bad_json_raises_opa_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(ValueError("bad json")))
    with pytest.raises(opa.OpaUnavailableError):
        opa.check_allow({})


def test_check_allow_http_status_error_raises_opa_unavailable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"result": True}, status_code=500))
    with pytest.raises(opa.OpaUnavailableError):
        opa.check_allow({})


def test_check_allow_posts_to_configured_url_and_path(monkeypatch):
    captured = {}

    def _fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"result": True})

    monkeypatch.setattr(httpx, "post", _fake_post)
    opa.check_allow({"subject": {"role": "admin"}})
    assert captured["url"] == f"{opa.settings.opa_url}/v1/data/agentic/authz/allow"
    assert captured["json"] == {"input": {"subject": {"role": "admin"}}}
    assert captured["timeout"] == opa.settings.opa_timeout_s


# --- authorize (fail-closed wrapper + input doc construction) ----------


def test_authorize_returns_true_on_allow(monkeypatch):
    monkeypatch.setattr(opa, "check_allow", lambda doc: True)
    user = _FakeUser("admin", uuid.uuid4())
    assert opa.authorize(user, "skill", "create", tenant_id=user.tenant_id) is True


def test_authorize_returns_false_on_deny(monkeypatch):
    monkeypatch.setattr(opa, "check_allow", lambda doc: False)
    user = _FakeUser("user", uuid.uuid4())
    assert opa.authorize(user, "skill", "create", tenant_id=user.tenant_id) is False


def test_authorize_fails_closed_when_opa_unavailable(monkeypatch):
    def _raise(doc):
        raise opa.OpaUnavailableError("down")

    monkeypatch.setattr(opa, "check_allow", _raise)
    user = _FakeUser("super_admin", None)
    # Even a super_admin — whose policy branch would unconditionally allow
    # — must be denied if OPA itself can't be reached. Fail-closed, no
    # exceptions to the rule.
    assert opa.authorize(user, "tenant", "create", tenant_id=None) is False


def test_authorize_builds_subject_doc_with_stringified_ids(monkeypatch):
    captured = {}

    def _capture(doc):
        captured.update(doc)
        return True

    monkeypatch.setattr(opa, "check_allow", _capture)
    tenant_id = uuid.uuid4()
    user = _FakeUser("admin", tenant_id)
    opa.authorize(user, "project", "read", tenant_id=tenant_id)

    assert captured["subject"] == {"id": str(user.id), "role": "admin", "tenant_id": str(tenant_id)}
    assert captured["resource"] == {"type": "project", "tenant_id": str(tenant_id)}
    assert captured["action"] == "read"


def test_authorize_super_admin_subject_tenant_id_is_none(monkeypatch):
    captured = {}
    monkeypatch.setattr(opa, "check_allow", lambda doc: captured.update(doc) or True)
    user = _FakeUser("super_admin", None)
    opa.authorize(user, "tenant", "list", tenant_id=None)
    assert captured["subject"]["tenant_id"] is None
    assert captured["resource"]["tenant_id"] is None


def test_authorize_includes_target_role_only_when_given(monkeypatch):
    captured = {}
    monkeypatch.setattr(opa, "check_allow", lambda doc: captured.update(doc) or True)
    user = _FakeUser("admin", uuid.uuid4())

    opa.authorize(user, "user", "create", tenant_id=user.tenant_id)
    assert "target_role" not in captured["resource"]

    opa.authorize(user, "user", "update", tenant_id=user.tenant_id, target_role="admin")
    assert captured["resource"]["target_role"] == "admin"
