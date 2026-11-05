from clautele.asks import extract_question
from clautele.textutil import describe_tool_use, format_denials, split_message


def test_marker_extracted_and_stripped():
    text = 'Ada dua cara.\n<<ASK>>{"question": "Pilih DB?", "options": ["Postgres", "SQLite"]}<<END>>'
    body, q = extract_question(text)
    assert body == "Ada dua cara."
    assert q.question == "Pilih DB?"
    assert q.options == ("Postgres", "SQLite")


def test_marker_limits_options():
    opts = ", ".join(f'"o{i}"' for i in range(20))
    _, q = extract_question(f'<<ASK>>{{"question": "x", "options": [{opts}]}}<<END>>')
    assert len(q.options) == 8


def test_bad_json_marker_is_dropped_not_crashing():
    body, q = extract_question("halo <<ASK>>{rusak<<END>>")
    assert q is None and body == "halo"


def test_fallback_numbered_list_after_question():
    body, q = extract_question("Mau yang mana?\n1. Merah\n2. Biru\n3. Hijau")
    assert q is not None and q.options == ("Merah", "Biru", "Hijau")
    assert "Merah" in body  # teks asli tidak dibuang


def test_numbered_list_without_question_is_not_a_question():
    _, q = extract_question("Langkah:\n1. Install\n2. Jalankan")
    assert q is None


def test_plain_text_no_question():
    assert extract_question("Selesai.")[1] is None


def test_split_short_is_single_chunk():
    assert split_message("halo") == ["halo"]


def test_split_long_respects_limit_and_numbers_parts():
    text = "\n\n".join("p" * 1000 for _ in range(10))
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)
    assert chunks[0].endswith(f"(1/{len(chunks)})")


def test_split_without_whitespace_hard_cuts():
    chunks = split_message("x" * 9000)
    assert all(len(c) <= 4096 for c in chunks)


def test_empty_text():
    assert split_message("   ") == ["(kosong)"]


def test_describe_tool_use():
    assert describe_tool_use("Bash", {"command": "ls   -la"}) == "🔧 Bash: ls -la"
    assert describe_tool_use("Read", {"file_path": "/a/b"}) == "🔧 Read: /a/b"
    assert describe_tool_use("X", None) == "🔧 X"
    assert len(describe_tool_use("Bash", {"command": "a" * 500})) < 100


def test_format_denials():
    assert format_denials([]) == ""
    out = format_denials([{"tool_name": "Bash"}, {"tool_name": "Bash"}, {"tool_name": "Edit"}])
    assert "Bash, Edit" in out
