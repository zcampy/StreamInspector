from streaminspector.system_proxy import SystemProxySnapshot, system_proxy_supported


def test_system_proxy_snapshot_preserves_previous_values() -> None:
    snapshot = SystemProxySnapshot(
        enabled=1,
        server="proxy.example:3128",
        bypass="<local>",
    )

    assert snapshot.enabled == 1
    assert snapshot.server == "proxy.example:3128"
    assert snapshot.bypass == "<local>"


def test_system_proxy_support_matches_platform() -> None:
    assert isinstance(system_proxy_supported(), bool)
