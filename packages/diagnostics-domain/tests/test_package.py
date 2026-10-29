import diagnostics_domain


def test_version_is_exposed() -> None:
    assert diagnostics_domain.__version__ == "0.1.0"
