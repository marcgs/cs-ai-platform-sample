import cs_platform


def test_version_is_exposed() -> None:
    assert cs_platform.__version__ == "0.1.0"
