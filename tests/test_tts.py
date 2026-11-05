import base64
import json

import pytest

from helpers_tts import SECRET, Server, make_wav  # noqa: F401

from clautele import tts
from clautele.tts import TtsConfig, TtsError, synthesize

@pytest.fixture
def srv():
    s = Server()
    yield s
    s.close()


def cfg_for(srv, **env):
    return TtsConfig.from_env({"TTS_BASE_URL": srv.url, "TTS_BASIC_AUTH": f"derry:{SECRET}", **env})


# ---------- konfigurasi ----------


def test_not_configured_returns_none():
    assert TtsConfig.from_env({}) is None


def test_defaults_and_basic_auth_header():
    c = TtsConfig.from_env({"TTS_BASE_URL": "https://x.example.com/", "TTS_BASIC_AUTH": "u:p"})
    assert c.base_url == "https://x.example.com" and (c.model, c.voice, c.response_format) == ("tts-1", "default", "wav")
    assert c.headers["Authorization"] == "Basic " + base64.b64encode(b"u:p").decode()
    assert c.headers["ngrok-skip-browser-warning"] == "1"


def test_bearer_and_extra_headers():
    c = TtsConfig.from_env({"TTS_BASE_URL": "https://x.example.com", "TTS_API_KEY": "k", "TTS_EXTRA_HEADERS": "X-A: 1; X-B: dua:titik"})
    assert c.headers["Authorization"] == "Bearer k" and c.headers["X-A"] == "1" and c.headers["X-B"] == "dua:titik"


@pytest.mark.parametrize(
    "env, msg",
    [
        ({"TTS_BASE_URL": "http://example.com"}, "https://"),
        ({"TTS_BASE_URL": "ftp://example.com"}, "valid"),
        ({"TTS_BASE_URL": "https://u:p@example.com"}, "user:password"),
        ({"TTS_BASE_URL": "https://e.com", "TTS_BASIC_AUTH": "u:p", "TTS_API_KEY": "k"}, "salah satu"),
        ({"TTS_BASE_URL": "https://e.com", "TTS_BASIC_AUTH": "tanpa-titik-dua"}, "user:password"),
        ({"TTS_BASE_URL": "https://e.com", "TTS_EXTRA_HEADERS": "rusak"}, "TTS_EXTRA_HEADERS"),
        ({"TTS_BASE_URL": "https://e.com", "TTS_TIMEOUT": "x"}, "TTS_TIMEOUT"),
    ],
)
def test_config_rejects_unsafe_or_invalid(env, msg):
    with pytest.raises(TtsError, match=msg):
        TtsConfig.from_env(env)


def test_http_allowed_only_on_loopback():
    assert TtsConfig.from_env({"TTS_BASE_URL": "http://127.0.0.1:3900"}).base_url == "http://127.0.0.1:3900"
    assert TtsConfig.from_env({"TTS_BASE_URL": "http://localhost:3900"})


def test_repr_never_contains_credentials():
    c = TtsConfig.from_env({"TTS_BASE_URL": "https://x.example.com", "TTS_BASIC_AUTH": f"u:{SECRET}"})
    assert SECRET not in repr(c) and "Authorization" not in repr(c)


# ---------- sintesis ----------


def test_synthesize_sends_expected_request(srv):
    audio = synthesize(cfg_for(srv, TTS_VOICE="adult", TTS_MODEL="omni", TTS_LANGUAGE="id"), "  Halo   dunia  ")
    assert audio.startswith(b"RIFF")
    r = srv.requests[-1]
    assert r["method"] == "POST" and r["path"] == "/v1/audio/speech"
    assert r["headers"]["authorization"] == "Basic " + base64.b64encode(f"derry:{SECRET}".encode()).decode()
    assert r["headers"]["ngrok-skip-browser-warning"] == "1"
    assert json.loads(r["body"]) == {"model": "omni", "voice": "adult", "input": "Halo dunia", "response_format": "wav", "language": "id"}


def test_language_omitted_when_unset(srv):
    synthesize(cfg_for(srv), "halo")
    assert "language" not in json.loads(srv.requests[-1]["body"])


def test_unauthorized_message_has_no_secret(srv):
    srv.mode = "401"
    with pytest.raises(TtsError) as e:
        synthesize(cfg_for(srv), "halo")
    assert "kredensial ditolak" in str(e.value) and SECRET not in str(e.value) and "derry" not in str(e.value)


def test_server_error_shows_snippet(srv):
    srv.mode = "500"
    with pytest.raises(TtsError, match="HTTP 500: boom"):
        synthesize(cfg_for(srv), "halo")


def test_redirect_refused_and_credentials_not_forwarded(srv):
    target = Server()
    try:
        srv.mode, srv.redirect_to = "redirect", target.url + "/curi"
        with pytest.raises(TtsError, match="redirect"):
            synthesize(cfg_for(srv), "halo")
        assert target.requests == []  # tidak ada permintaan (dan kredensial) yang sampai ke host lain
    finally:
        target.close()


@pytest.mark.parametrize("mode, msg", [("json", "bukan audio"), ("notaudio", "bukan audio")])
def test_non_audio_responses_rejected(srv, mode, msg):
    srv.mode = mode
    with pytest.raises(TtsError, match=msg):
        synthesize(cfg_for(srv), "halo")


def test_text_limits(srv):
    with pytest.raises(TtsError, match="kosong"):
        synthesize(cfg_for(srv), "   ")
    with pytest.raises(TtsError, match="terlalu panjang"):
        synthesize(cfg_for(srv), "x" * 601)
    assert srv.requests == []  # ditolak sebelum menghubungi server


def test_oversize_response_rejected(srv, monkeypatch):
    srv.mode = "big"
    monkeypatch.setattr(tts, "MAX_RESPONSE_BYTES", 1000)
    with pytest.raises(TtsError, match="terlalu besar"):
        synthesize(cfg_for(srv), "halo")


def test_timeout(srv):
    srv.mode = "slow"
    with pytest.raises(TtsError, match="timeout|tidak bisa menghubungi"):
        synthesize(cfg_for(srv, TTS_TIMEOUT="1"), "halo")


# ---------- health & probe ----------


def test_health_ok_and_unreachable(srv):
    assert tts.health(cfg_for(srv)) == (True, "HTTP 200")
    srv.close()
    ok, detail = tts.health(cfg_for(srv), timeout=2)
    assert not ok and SECRET not in detail


def test_probe_lists_voice_paths_and_masks_credentials(srv, monkeypatch):
    monkeypatch.setattr(tts, "audio_duration", lambda p: 0.5)
    lines: list[str] = []
    assert tts.probe(cfg_for(srv, TTS_VOICE="adult"), out=lines.append) == 0
    text = "\n".join(lines)
    assert "/v1/audio/speech" in text and "/voices/profiles" in text and "omni-tts" in text
    assert "sintesis: OK" in text
    assert SECRET not in text and "derry" not in text and "Basic " not in text
