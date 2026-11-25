from voice.kitten_misaki import _nltk_tokens


class FakeToken:
    class Underscore:
        def __init__(self, **values):
            self.values = values

    def __init__(self, **values):
        self.__dict__.update(values)


class FakeTokenizer:
    def span_tokenize(self, text):
        return [(0, 5), (7, 12), (13, 18)]


class FakeNltk:
    @staticmethod
    def pos_tag(words):
        assert words == ["Hello", "world", "again"]
        return [(word, "NN") for word in words]


def test_nltk_misaki_tokens_keep_pos_tags_and_exact_whitespace():
    tokens = _nltk_tokens(
        "Hello  world\nagain",
        FakeNltk,
        FakeToken,
        FakeTokenizer(),
    )
    assert [token.text for token in tokens] == ["Hello", "world", "again"]
    assert [token.tag for token in tokens] == ["NN", "NN", "NN"]
    assert [token.whitespace for token in tokens] == ["  ", "\n", ""]
    assert all(token._.values == {
        "is_head": True, "num_flags": "", "prespace": False
    } for token in tokens)
