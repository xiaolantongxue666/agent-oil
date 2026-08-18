"""安全句段流式输出测试。"""

from app.safety.streaming import SafeSentenceStreamer


def test_streamer_releases_only_complete_sentences():
    streamer = SafeSentenceStreamer()

    assert streamer.feed("根据资料，应先").chunks == []
    first = streamer.feed("完成风险辨识。下一步").chunks
    tail = streamer.finish().chunks

    assert first == ["根据资料，应先完成风险辨识。"]
    assert tail == ["下一步"]
    assert streamer.accepted_text == "根据资料，应先完成风险辨识。下一步"


def test_streamer_blocks_unsafe_sentence_before_releasing_it():
    streamer = SafeSentenceStreamer()

    assert streamer.feed("请立即开").chunks == []
    decision = streamer.feed("阀进行排放。")

    assert decision.chunks == []
    assert decision.violation is not None
    assert decision.violation.category == "output_control"
    assert streamer.accepted_text == ""


def test_streamer_keeps_safe_prefix_but_rejects_following_unsafe_sentence():
    streamer = SafeSentenceStreamer()

    safe = streamer.feed("这是教学场景说明。")
    blocked = streamer.feed("应当立即启泵以保证输送。")

    assert safe.chunks == ["这是教学场景说明。"]
    assert blocked.chunks == []
    assert blocked.violation is not None
    assert streamer.accepted_text == "这是教学场景说明。"


def test_streamer_suppresses_model_generated_citation_section_across_chunks():
    streamer = SafeSentenceStreamer()

    body = streamer.feed("回答正文。")
    heading_part = streamer.feed("\n\n**专业依")
    heading_end = streamer.feed("据**\n来源：教学模拟资料\n")
    ignored = streamer.feed("更多模型自造来源。")

    visible = "".join(body.chunks + heading_part.chunks + heading_end.chunks + ignored.chunks)
    assert visible == "回答正文。\n\n"
    assert "专业依据" not in visible
    assert "教学模拟资料" not in visible

