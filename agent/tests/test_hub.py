import asyncio
import json

import pytest
import websockets

from chibi_agent.server import Hub
from chibi_shared import protocol as p


@pytest.fixture
async def hub(tmp_path):
    h = Hub(run_file=tmp_path / "run.json")
    await h.start()
    yield h
    await h.stop()


async def connect(hub, token, role="voice", version=p.VERSION):
    ws = await websockets.connect(f"ws://127.0.0.1:{hub.port}")
    await ws.send(p.encode(p.Hello(role=role, token=token, version=version)))
    return ws


async def test_run_file_has_port_and_token(hub):
    info = json.loads(hub.run_file.read_text())
    assert info == {"port": hub.port, "token": hub.token}


async def test_good_token_gets_welcome(hub):
    ws = await connect(hub, hub.token)
    assert isinstance(p.decode(await ws.recv()), p.Welcome)
    await asyncio.wait_for(hub.connected["voice"].wait(), 1)
    await ws.close()


@pytest.mark.parametrize("token,version", [("wrong", p.VERSION), (None, p.VERSION + 1)])
async def test_bad_token_or_version_is_closed(hub, token, version):
    ws = await connect(hub, token or hub.token, version=version)
    with pytest.raises(websockets.ConnectionClosed) as e:
        await ws.recv()
    assert e.value.rcvd.code == 1008
    assert "voice" not in hub.clients


async def test_non_hello_first_frame_is_closed(hub):
    ws = await websockets.connect(f"ws://127.0.0.1:{hub.port}")
    await ws.send(p.encode(p.Stop()))
    with pytest.raises(websockets.ConnectionClosed):
        await ws.recv()


async def test_messages_reach_handlers_and_lip_is_relayed(hub):
    got = []

    async def handler(role, msg):
        got.append((role, msg.t))

    hub.on_message(handler)
    voice = await connect(hub, hub.token, "voice")
    overlay = await connect(hub, hub.token, "overlay")
    await voice.recv(), await overlay.recv()
    await voice.send(p.encode(p.Transcript(text="hi", ms=10)))
    await voice.send(p.encode(p.Lip(rms=0.5)))
    relayed = p.decode(await asyncio.wait_for(overlay.recv(), 1))
    assert isinstance(relayed, p.Lip) and relayed.rms == 0.5
    await asyncio.sleep(0.05)
    assert got == [("voice", "transcript")]  # lip goes straight to the overlay, not to handlers
    assert await hub.send("voice", p.Ptt(down=True))
    assert isinstance(p.decode(await voice.recv()), p.Ptt)
