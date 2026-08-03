from types import SimpleNamespace

from streaminspector.capture_policy import CapturePolicy, normalize_domains


def _flow(host: str, path: str = "/api", content_type: str = "application/json"):
    return SimpleNamespace(host=host, path=path, content_type=content_type)


def test_normalize_domains_removes_wildcards_duplicates_and_spaces() -> None:
    assert normalize_domains(" *.Example.com\nexample.com, api.local ") == (
        "example.com",
        "api.local",
    )


def test_policy_excludes_domain_and_subdomains() -> None:
    policy = CapturePolicy(excluded_domains=("example.com",))
    assert not policy.accepts(_flow("example.com"))
    assert not policy.accepts(_flow("api.example.com"))
    assert policy.accepts(_flow("example.org"))


def test_policy_pauses_all_traffic() -> None:
    policy = CapturePolicy(paused=True)
    assert not policy.accepts(_flow("example.org"))


def test_policy_omits_static_resources_by_type_or_extension() -> None:
    policy = CapturePolicy(omit_static=True)
    assert not policy.accepts(_flow("site.local", content_type="image/png"))
    assert not policy.accepts(_flow("site.local", path="/assets/app.js"))
    assert policy.accepts(_flow("site.local", path="/api/users"))
