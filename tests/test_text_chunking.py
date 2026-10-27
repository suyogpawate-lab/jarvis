from voice.text_chunking import chunk_text


def test_short_replies_at_or_below_twenty_words_stay_whole():
    text = "This reply has exactly enough words to remain intact without introducing any awkward pause during normal speech playback."
    assert len(text.split()) <= 20
    assert chunk_text(text) == [text]


def test_long_single_sentence_is_split_near_fifteen_words():
    text = " ".join(f"word{i}" for i in range(29)) + "."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert [len(chunk.split()) for chunk in chunks] == [15, 14]
    assert " ".join(chunks).replace(" .", ".") == text


def test_long_reply_uses_sentence_boundaries_and_keeps_thirteen_and_seventeen_word_chunks():
    first = " ".join(f"first{i}" for i in range(13)) + "."
    second = " ".join(f"second{i}" for i in range(17)) + "."
    chunks = chunk_text(first + " " + second)
    assert [len(chunk.split()) for chunk in chunks] == [13, 17]
    assert chunks == [first, second]


def test_commas_are_not_chunk_boundaries():
    words = [f"word{i}" for i in range(28)]
    words[14] += ","
    text = " ".join(words) + "."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert not any(chunk.endswith(",") for chunk in chunks)
    assert sum(len(chunk.split()) for chunk in chunks) == 29
