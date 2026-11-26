"""The public address short links are shown (and copied) with."""

from urllib.parse import urlsplit

from flask import current_app, request


def normalise_base_url(value: str) -> str:
    """BASE_URL is the public address short links are shown (and copied) with, e.g. https://s.example.com"""
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise RuntimeError("BASE_URL must look like https://s.example.com (no path, query or fragment)")
    return f"{parts.scheme}://{parts.netloc}/"


def base_url() -> str:
    return current_app.config["BASE_URL"] or request.host_url
