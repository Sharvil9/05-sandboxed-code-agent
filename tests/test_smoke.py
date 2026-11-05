"""Bootstrap smoke test for the installable package."""


def test_package_imports():
    import sandbox_agent

    assert sandbox_agent.__doc__ == "Sandboxed local-model code execution agent."
