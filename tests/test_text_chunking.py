from voice.text_chunking import chunk_text


def test_replies_at_or_below_fifty_words_stay_whole():
    text = " ".join(f"word{i}" for i in range(50)) + "."
    assert len(text.split()) == 50
    assert chunk_text(text) == [text]


def test_replies_over_fifty_words_split_near_twenty_words():
    text = " ".join(f"word{i}" for i in range(51)) + "."
    chunks = chunk_text(text)
    assert [len(chunk.split()) for chunk in chunks] == [20, 20, 11]
    assert " ".join(chunks) == text


def test_two_short_sentences_remain_together_when_reply_is_under_threshold():
    first = " ".join(f"first{i}" for i in range(13)) + "."
    second = " ".join(f"second{i}" for i in range(17)) + "."
    text = first + " " + second
    assert len(text.split()) == 30
    assert chunk_text(text) == [text]


def test_long_reply_prefers_sentence_boundaries_near_twenty_words():
    first = " ".join(f"first{i}" for i in range(18)) + "."
    second = " ".join(f"second{i}" for i in range(19)) + "."
    third = " ".join(f"third{i}" for i in range(15)) + "."
    chunks = chunk_text(first + " " + second + " " + third)
    assert [len(chunk.split()) for chunk in chunks] == [18, 19, 15]


def test_commas_are_not_chunk_boundaries():
    words = [f"word{i}" for i in range(51)]
    words[19] += ","
    text = " ".join(words) + "."
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert not any(chunk.endswith(",") for chunk in chunks)
    assert sum(len(chunk.split()) for chunk in chunks) == 51
