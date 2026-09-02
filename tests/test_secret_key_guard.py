"""C1: SECRET_KEY 기본값 제거 — 빈 값/개발 기본값으로는 기동·서명하지 않는다.

과거 config.py 가 `"default_super_secret_key_for_dev"` 로 폴백해, Render 에
SECRET_KEY 가 없으면 어드민 JWT(HS256)를 누구나 위조할 수 있었다.
"""
import pytest

from diag_project import config as cfg


def _with_key(monkeypatch, value):
    monkeypatch.setattr(cfg.settings, "SECRET_KEY", value)


def test_empty_secret_key_rejected(monkeypatch):
    _with_key(monkeypatch, "")
    with pytest.raises(RuntimeError):
        cfg.require_secret_key()


def test_legacy_dev_default_rejected(monkeypatch):
    _with_key(monkeypatch, "default_super_secret_key_for_dev")
    with pytest.raises(RuntimeError):
        cfg.require_secret_key()


def test_whitespace_only_rejected(monkeypatch):
    _with_key(monkeypatch, "   ")
    with pytest.raises(RuntimeError):
        cfg.require_secret_key()


def test_real_key_accepted(monkeypatch):
    _with_key(monkeypatch, "a" * 64)
    assert cfg.require_secret_key() == "a" * 64


def test_signing_key_fails_closed_as_500(monkeypatch):
    """startup 을 거치지 않는 경로에서도 위조 가능한 키로 서명하지 않는다."""
    from fastapi import HTTPException
    from diag_project.services import auth

    _with_key(monkeypatch, "default_super_secret_key_for_dev")
    with pytest.raises(HTTPException) as ei:
        auth._signing_key()
    assert ei.value.status_code == 500
