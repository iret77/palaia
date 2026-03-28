"""Tests for Unicode and special character handling."""


from palaia.store import Store

# ── Emoji content ─────────────────────────────────────────────


def test_write_read_emoji_content(palaia_root):
    store = Store(palaia_root)
    body = "Great progress today! 🚀🎉 The deployment went smooth 💯"
    entry_id = store.write(body, scope="team", agent="test")
    result = store.read(entry_id)
    assert result is not None
    meta, read_body = result
    assert "🚀🎉" in read_body
    assert "💯" in read_body


def test_write_emoji_tags(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write(
        "Tagged with emoji",
        scope="team",
        tags=["🏷️tag", "fire🔥", "✅done"],
    )
    result = store.read(entry_id)
    assert result is not None
    meta, _ = result
    assert "🏷️tag" in meta["tags"]
    assert "fire🔥" in meta["tags"]
    assert "✅done" in meta["tags"]


def test_write_emoji_title(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write(
        "Content body here",
        scope="team",
        title="🎯 Sprint Goal 🏁",
    )
    result = store.read(entry_id)
    assert result is not None
    meta, _ = result
    assert meta["title"] == "🎯 Sprint Goal 🏁"


# ── CJK characters ───────────────────────────────────────────


def test_write_read_cjk(palaia_root):
    store = Store(palaia_root)
    body = "这是一个测试条目。日本語のテスト。한국어 테스트입니다."
    entry_id = store.write(body, scope="team", agent="test")
    result = store.read(entry_id)
    assert result is not None
    _, read_body = result
    assert "这是一个测试条目" in read_body
    assert "日本語のテスト" in read_body
    assert "한국어 테스트" in read_body


def test_cjk_tags_and_title(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write(
        "CJK metadata test",
        scope="team",
        tags=["标签", "タグ", "태그"],
        title="中文标题 / 日本語タイトル",
    )
    result = store.read(entry_id)
    assert result is not None
    meta, _ = result
    assert "标签" in meta["tags"]
    assert "タグ" in meta["tags"]
    assert "태그" in meta["tags"]
    assert "中文标题" in meta["title"]


# ── RTL text ──────────────────────────────────────────────────


def test_write_read_rtl(palaia_root):
    store = Store(palaia_root)
    body = "هذا اختبار للنص العربي. עברית בדיקה."
    entry_id = store.write(body, scope="team", agent="test")
    result = store.read(entry_id)
    assert result is not None
    _, read_body = result
    assert "هذا اختبار" in read_body
    assert "עברית בדיקה" in read_body


# ── Zero-width characters ────────────────────────────────────


def test_write_read_zero_width(palaia_root):
    store = Store(palaia_root)
    # Zero-width space (U+200B), zero-width joiner (U+200D), zero-width non-joiner (U+200C)
    body = "Text\u200bwith\u200dzero\u200cwidth characters"
    entry_id = store.write(body, scope="team", agent="test")
    result = store.read(entry_id)
    assert result is not None
    _, read_body = result
    assert "\u200b" in read_body
    assert "\u200d" in read_body
    assert "\u200c" in read_body


# ── List with Unicode ─────────────────────────────────────────


def test_list_unicode_entries(palaia_root):
    store = Store(palaia_root)
    store.write("Emoji entry 🌟", scope="team")
    store.write("CJK entry 漢字", scope="team")
    store.write("RTL entry مرحبا", scope="team")

    entries = store.list_entries("hot")
    assert len(entries) == 3
    bodies = [body for _, body in entries]
    assert any("🌟" in b for b in bodies)
    assert any("漢字" in b for b in bodies)
    assert any("مرحبا" in b for b in bodies)


# ── Dedup with Unicode ────────────────────────────────────────


def test_dedup_unicode(palaia_root):
    store = Store(palaia_root)
    id1 = store.write("同じ内容 🎯")
    id2 = store.write("同じ内容 🎯")
    assert id1 == id2  # Deduplicated


# ── Mixed scripts ─────────────────────────────────────────────


def test_mixed_scripts(palaia_root):
    store = Store(palaia_root)
    body = "English mixed with 中文 and العربية and emoji 🎉 and Кириллица"
    entry_id = store.write(body, scope="team", tags=["mixed", "テスト"])
    result = store.read(entry_id)
    assert result is not None
    meta, read_body = result
    assert "中文" in read_body
    assert "العربية" in read_body
    assert "Кириллица" in read_body
    assert "テスト" in meta["tags"]
