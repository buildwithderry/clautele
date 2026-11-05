import pytest

from clautele.grants import bash_rules, options_for


def d(cmd, tool="Bash"):
    return {"tool_name": tool, "tool_input": {"command": cmd}}


def test_simple_command():
    assert bash_rules("ffmpeg -i a.mp4 -c:v libx264 out.mp4") == ("Bash(ffmpeg *)",)
    assert bash_rules("/usr/bin/ffmpeg -version") == ("Bash(/usr/bin/ffmpeg *)",)


def test_chained_commands_need_every_segment():
    assert bash_rules("ffmpeg -i a b; ffprobe b") == ("Bash(ffmpeg *)", "Bash(ffprobe *)")
    assert bash_rules("ffmpeg x && ffmpeg y") == ("Bash(ffmpeg *)",)  # duplikat digabung
    assert bash_rules("ffprobe x | head -1") == ("Bash(ffprobe *)", "Bash(head *)")


@pytest.mark.parametrize(
    "cmd",
    ["", "   ", "echo $(cat ~/.ssh/id_rsa)", "echo `id`", "A=1 ffmpeg x", "ffmpeg x;", "ls\nrm -rf /", "diff <(a) <(b)", "'tak tertutup"],
)
def test_unsafe_or_unparseable_returns_none(cmd):
    assert bash_rules(cmd) is None


def test_options_simple_bash_offers_narrow_and_broad():
    opts = options_for([d("ffmpeg -i a.mp4 b.mp4")])
    assert opts[0].rules == ("Bash(ffmpeg *)",) and not opts[0].broad and "ffmpeg" in opts[0].label
    assert opts[-1].rules == ("Bash",) and opts[-1].broad  # pilihan lebar selalu terakhir


def test_options_powerful_executables_flagged():
    for exe in ("python3", "bash", "sudo", "curl", "git", "rm"):
        opt = options_for([d(f"{exe} arg")])[0]
        assert opt.broad and opt.label.startswith("⚠️"), exe


def test_options_compound_grants_all_segments_in_one_button():
    opts = options_for([d("ffmpeg -i a b; ffprobe b")])
    assert opts[0].rules == ("Bash(ffmpeg *)", "Bash(ffprobe *)")


def test_options_non_bash_and_dedupe():
    opts = options_for([{"tool_name": "WebFetch"}, {"tool_name": "WebFetch"}, {"tool_name": "Edit"}])
    assert [o.rules for o in opts] == [("WebFetch",), ("Edit",)]


def test_options_unparseable_bash_only_offers_all():
    opts = options_for([d("echo $(whoami)")])
    assert [o.rules for o in opts] == [("Bash",)]


def test_options_ignore_garbage_and_cap():
    assert options_for([None, "x", {}, {"tool_name": ""}]) == []
    many = [{"tool_name": f"T{i}"} for i in range(20)]
    assert len(options_for(many)) == 6
