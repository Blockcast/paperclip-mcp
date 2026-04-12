def test_import() -> None:
    import paperclip_mcp
    assert paperclip_mcp is not None


def test_entrypoint_exists() -> None:
    from paperclip_mcp import server
    assert hasattr(server, "main")
