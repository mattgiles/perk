from perk._resources import shared_dir


def test_shared_dir_resolves():
    d = shared_dir()
    assert d.is_dir()
    # T1 ships a README probe; T2 adds the real contracts.
    assert (d / "README.md").is_file()
