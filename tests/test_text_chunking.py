from voice.text_chunking import chunk_text


def test_replies_at_or_below_sixty_words_stay_whole():
    text = " ".join(f"word{i}" for i in range(60)) + "."
    assert len(text.split()) == 60
    assert chunk_text(text) == [text]


def test_replies_over_sixty_words_split_near_twenty_two_words():
    text = " ".join(f"word{i}" for i in range(61)) + "."
    chunks = chunk_text(text)
    assert [len(chunk.split()) for chunk in chunks] == [22, 22, 17]
    assert " ".join(chunks) == text


def test_two_short_sentences_remain_together_when_reply_is_under_threshold():
    first = " ".join(f"first{i}" for i in range(13)) + "."
    second = " ".join(f"second{i}" for i in range(17)) + "."
    text = first + " " + second
    assert len(text.split()) == 30
    assert chunk_text(text) == [text]


def test_long_reply_prefers_sentence_boundaries_near_twenty_two_words():
    first = " ".join(f"first{i}" for i in range(18)) + "."
    second = " ".join(f"second{i}" for i in range(19)) + "."
    third = " ".join(f"third{i}" for i in range(25)) + "."
    text = first + " " + second + " " + third
    chunks = chunk_text(text)
    assert " ".join(chunks) == text
    assert all(len(chunk.split()) <= 25 for chunk in chunks)


def test_commas_are_not_chunk_boundaries():
    words = [f"word{i}" for i in range(61)]
    words[21] += ","
    text = " ".join(words) + "."
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert not any(chunk.endswith(",") for chunk in chunks)
    assert sum(len(chunk.split()) for chunk in chunks) == 61
