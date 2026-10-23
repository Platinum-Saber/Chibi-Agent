from collections import namedtuple
from pathlib import Path

import psutil
import pytest

from chibi_agent import tools
from chibi_agent.tools import files, network, recycle_bin, shell

REG = tools.load_all()


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "ALLOWED_ROOTS", [tmp_path.resolve()])
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.py").write_text("import os\nprint('Hello Raphael')\n", encoding="utf-8")
    (tmp_path / "proj" / "notes.txt").write_text("hello again\nnothing here\n", encoding="utf-8")
    (tmp_path / "proj" / "blob.bin").write_bytes(b"hello\0\0binary")
    (tmp_path / "proj" / "sub").mkdir()
    (tmp_path / "proj" / "sub" / "big.txt").write_text("x" * 5000, encoding="utf-8")
    return tmp_path.resolve()


def test_grep_finds_text_and_skips_binaries(root):
    r = files.grep_files("hello", str(root / "proj"))
    assert "a.py:2:" in r.text and "notes.txt:1:" in r.text and "blob.bin" not in r.text
    assert r.untrusted
    assert "a.py" in files.grep_files("hello", str(root / "proj"), "*.py").text
    assert "notes.txt" not in files.grep_files("hello", str(root / "proj"), "*.py").text
    assert "not found" in files.grep_files("zebra", str(root / "proj")).text


def test_grep_skips_files_over_the_size_limit(root, monkeypatch):
    monkeypatch.setattr(files, "GREP_MAX_BYTES", 100)
    assert "big.txt" not in files.grep_files("x", str(root / "proj")).text


def test_everything_outside_the_allowed_roots_is_refused(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    for call in (lambda: files.grep_files("a", str(outside)), lambda: files.list_folder(str(outside)),
                 lambda: files.read_file(str(outside / "x.txt")), lambda: files.create_folder(str(outside / "n")),
                 lambda: files.create_file(str(outside / "n.txt"), "x")):
        with pytest.raises(PermissionError):
            call()


def test_list_folder_sorts_and_totals_folder_sizes(root):
    by_name = files.list_folder(str(root / "proj")).text.splitlines()
    assert by_name[1].startswith("[folder] sub")  # folders first
    by_size = files.list_folder(str(root / "proj"), "size").text.splitlines()
    assert by_size[1].startswith("[folder] sub") and "4.9 KB" in by_size[1]  # 5000 bytes inside


def test_read_file_truncates_and_refuses_binaries(root):
    (root / "long.txt").write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    text = files.read_file(str(root / "long.txt"), "5").text
    assert "line 4" in text and "line 5" not in text and text.endswith("...")
    assert "not a text file" in files.read_file(str(root / "proj" / "blob.bin")).text


def test_create_folder_and_file_never_overwrite(root):
    assert "Created" in files.create_folder(str(root / "new" / "deep")).text
    assert (root / "new" / "deep").is_dir()
    assert "already exists" in files.create_folder(str(root / "new")).text
    assert "Created" in files.create_file(str(root / "new" / "a.txt"), "hi").text
    assert "will not overwrite" in files.create_file(str(root / "new" / "a.txt"), "bye").text
    assert (root / "new" / "a.txt").read_text(encoding="utf-8") == "hi"


class FakeItem:
    def __init__(self, name, size, frm, deleted, verbs=("&Restore", "Cu&t", "&Delete")):
        self.Name, self.Size, self._d = name, size, {1: frm, 2: deleted, 3: f"{size // 1024} KB"}
        self.verbs = [type("V", (), {"Name": v, "DoIt": staticmethod(lambda it=self, v=v: it.done.append(v))})() for v in verbs]
        self.done = []

    def Verbs(self):  # noqa: N802 (COM)
        return self.verbs


class FakeShell:
    def __init__(self, items):
        self.items = items

    def Namespace(self, n):  # noqa: N802 (COM)
        assert n == recycle_bin.BIN
        shell = self
        return type("NS", (), {"Items": lambda s: shell.items,
                               "GetDetailsOf": lambda s, it, col: it._d[col]})()


def test_recycle_bin_lists_items_and_total():
    sh = FakeShell([FakeItem("ANIYA", 84 * 1024 * 1024, "D:\\Rigs", "23/10/2026 10:00"),
                    FakeItem("notes.txt", 2048, "C:\\Users\\Kryo", "22/10/2026 09:00")])
    r = recycle_bin.recycle_bin(shell=sh)
    assert r.text.startswith("2 items, 84.0 MB in all") and "ANIYA" in r.text and "from D:\\Rigs" in r.text
    assert "emptying it is for Kryo" in r.text
    assert recycle_bin.recycle_bin(shell=FakeShell([])).text == "The Recycle Bin is empty."


def test_recycle_bin_restores_by_name_and_never_empties():
    item = FakeItem("ANIYA", 1, "D:\\Rigs", "today")
    sh = FakeShell([item, FakeItem("Fern", 1, "D:\\Rigs", "today")])
    assert "Restored ANIYA" in recycle_bin.recycle_bin_action("restore", "aniya", shell=sh).text
    assert item.done == ["&Restore"]  # only the Restore verb, never Delete
    assert "Nothing called" in recycle_bin.recycle_bin_action("restore", "zzz", shell=sh).text
    assert "Emptying the bin is for Kryo" in recycle_bin.recycle_bin_action("empty", shell=sh).text
    assert REG["recycle_bin_action"].confirm and not REG["recycle_bin"].side_effect


Addr = namedtuple("Addr", "ip port")
Conn = namedtuple("Conn", "pid status laddr raddr")
IO = namedtuple("IO", "bytes_sent bytes_recv")


def test_network_connections_by_process():
    conns = [Conn(1, psutil.CONN_ESTABLISHED, Addr("10.0.0.2", 5000), Addr("1.2.3.4", 443)),
             Conn(1, psutil.CONN_ESTABLISHED, Addr("10.0.0.2", 5001), Addr("5.6.7.8", 443)),
             Conn(2, psutil.CONN_LISTEN, Addr("0.0.0.0", 8080), ()),
             Conn(3, psutil.CONN_ESTABLISHED, Addr("10.0.0.2", 5002), Addr("9.9.9.9", 80))]
    names = {1: "Spotify.exe", 2: "python.exe", 3: "msedge.exe"}
    out = network.connections("", conns, names)
    assert out.startswith("3 open connections (2 Spotify.exe, 1 msedge.exe)")
    assert "python.exe listening on port 8080" in out
    only = network.connections("spotify", conns, names)
    assert "msedge" not in only and only.startswith("2 open connections")


def test_network_traffic_rates():
    samples = iter([{"Wi-Fi": IO(1000, 10_000), "Loopback Pseudo-Interface 1": IO(0, 0)},
                    {"Wi-Fi": IO(3048, 2_107_152), "Loopback Pseudo-Interface 1": IO(9, 9)}])
    out = network.traffic(2.0, counters=lambda: next(samples), sleep=lambda s: None)
    assert out.startswith("Wi-Fi: down 1.0 MB/s, up 1.0 KB/s") and "Loopback" not in out


def test_ping_and_wifi_parse_their_output(monkeypatch):
    monkeypatch.setattr(network.socket, "gethostbyname", lambda h: "1.1.1.1")
    ok = type("P", (), {"stdout": "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),\n"
                                  "Minimum = 9ms, Maximum = 14ms, Average = 11ms"})()
    assert "answers: average 11 ms, 0% lost" in network.ping("1.1.1.1", run=lambda *a, **k: ok)
    assert "not a host name" in network.ping("a; rm -rf", run=lambda *a, **k: ok)
    wifi = type("P", (), {"stdout": "    State                  : connected\n    SSID                   : Home\n"
                                    "    Signal                 : 87%\n    Band                   : 5 GHz\n"})()
    assert network.wifi(run=lambda *a, **k: wifi) == "State: connected, SSID: Home, Signal: 87%, Band: 5 GHz"


def test_shell_guard_blocks_emptying_the_bin():
    for cmd in ("Clear-RecycleBin -Force", "clear-recyclebin -DriveLetter C"):
        assert "has not been granted" in shell.run_shell(cmd).text
