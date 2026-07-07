from perk._resources import prompts_dir, shared_dir


def test_shared_dir_resolves():
    d = shared_dir()
    assert d.is_dir()
    # The README is the durable bundling/resolution probe.
    assert (d / "README.md").is_file()


def test_prompts_dir_resolves():
    d = prompts_dir()
    assert d.is_dir()
    # The README is the durable bundling/resolution probe.
    assert (d / "README.md").is_file()
