import raphael


def test_setup_runs_until_every_venv_and_the_versions_marker_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    (tmp_path / "VERSION").write_text("9.9.9\n")
    assert raphael.version(tmp_path) == "9.9.9"
    assert raphael.needs_setup(tmp_path)
    for p in raphael.PACKAGES:
        (tmp_path / p / ".venv" / "Scripts").mkdir(parents=True)
        (tmp_path / p / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    assert raphael.needs_setup(tmp_path)  # venvs, but this version's setup never finished
    m = raphael.marker("9.9.9")
    m.parent.mkdir(parents=True)
    m.write_text("")
    assert not raphael.needs_setup(tmp_path)
