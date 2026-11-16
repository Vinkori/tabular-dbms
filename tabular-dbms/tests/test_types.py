"""Перевірки правил ТЗ для шести типів і JSON-перетворень."""

from dataclasses import FrozenInstanceError
import json

import pytest

from backend.domain.colors import Color, ColorInterval
from backend.domain.data_types import DataType, TYPE_REGISTRY, get_data_type
from backend.domain.errors import DomainValidationError


VALID_CASES = [
    ("integer", 10**100, 10**100),
    ("integer", " +003 ", 3),
    ("integer", "-12", -12),
    ("real", 3, 3.0),
    ("real", " -1.25e2 ", -125.0),
    ("real", ".5", 0.5),
    ("real", "3.", 3.0),
    ("real", "3", 3.0),
    ("char", " ", " "),
    ("char", "ї", "ї"),
    ("char", "😀", "😀"),
    ("string", "", ""),
    ("string", " Anna ", " Anna "),
    ("color", {"red": 0, "green": 128, "blue": 255}, Color(0, 128, 255)),
    ("color", Color(1, 2, 3), Color(1, 2, 3)),
    (
        "colorInvl",
        {"start": {"red": 0, "green": 1, "blue": 2},
         "end": {"red": 100, "green": 150, "blue": 200}},
        ColorInterval(Color(0, 1, 2), Color(100, 150, 200)),
    ),
    ("colorInvl", ColorInterval(Color(5, 5, 5), Color(5, 5, 5)),
     ColorInterval(Color(5, 5, 5), Color(5, 5, 5))),
]


@pytest.mark.parametrize("name,raw,expected", VALID_CASES)
def test_normalization_and_json_round_trip(name, raw, expected):
    data_type = get_data_type(name)
    assert data_type.validate(raw) is True
    value = data_type.normalize(raw)
    assert value == expected
    assert type(value) is type(expected)
    assert data_type.normalize(value) == value
    encoded = json.dumps(data_type.to_json(value), ensure_ascii=False, allow_nan=False)
    restored = data_type.from_json(json.loads(encoded))
    assert restored == expected
    assert type(restored) is type(expected)
    assert data_type.canonicalize(restored) == data_type.canonicalize(value)
    hash(data_type.canonicalize(value))


INVALID_CASES = [
    ("integer", value)
    for value in [True, False, 3.0, 3.5, "3.0", "3.5", "1e2", "", "+", "1_000", "１２", "abc"]
] + [
    ("real", value)
    for value in [True, False, "", "1,5", "1_000", "１２", "NaN", "Infinity",
                  float("nan"), float("inf"), float("-inf"), "1e9999", 10**1000, []]
] + [
    ("char", value) for value in ["", "AB", "e\u0301", 1, True]
] + [
    ("string", value) for value in [1, 1.5, True, [], {}]
] + [(name, None) for name in TYPE_REGISTRY]


@pytest.mark.parametrize("name,raw", INVALID_CASES)
def test_invalid_values_are_rejected(name, raw):
    data_type = get_data_type(name)
    assert data_type.validate(raw) is False
    for operation in (data_type.normalize, data_type.from_json, data_type.to_json):
        with pytest.raises(DomainValidationError):
            operation(raw)


@pytest.mark.parametrize("channel", ["red", "green", "blue"])
@pytest.mark.parametrize("bad", [-1, 256, True, 1.0, "1", None])
def test_invalid_rgb_channels(channel, bad):
    raw = {"red": 0, "green": 0, "blue": 0}
    raw[channel] = bad
    test_invalid_values_are_rejected("color", raw)
    with pytest.raises(DomainValidationError) as error:
        Color(**raw)
    assert error.value.field == channel


@pytest.mark.parametrize("name,raw", [
    ("color", {}),
    ("color", {"red": 0, "green": 0}),
    ("color", {"red": 0, "green": 0, "blue": 0, "alpha": 255}),
    ("color", "#FF0000"),
    ("color", [0, 0, 0]),
    ("colorInvl", {}),
    ("colorInvl", {"start": {"red": 0, "green": 0, "blue": 0}}),
    ("colorInvl", {"start": None, "end": None}),
    ("colorInvl", {"start": {}, "end": {}}),
    ("colorInvl", {"start": {}, "end": {}, "extra": 1}),
])
def test_invalid_object_shapes(name, raw):
    test_invalid_values_are_rejected(name, raw)


@pytest.mark.parametrize("channel", ["red", "green", "blue"])
def test_reversed_interval_channel(channel):
    start = {"red": 0, "green": 0, "blue": 0}
    end = {"red": 1, "green": 1, "blue": 1}
    start[channel] = 2
    test_invalid_values_are_rejected("colorInvl", {"start": start, "end": end})
    with pytest.raises(DomainValidationError):
        ColorInterval(Color(**start), Color(**end))


def test_immutable_objects_and_invalid_direct_interval():
    color = Color(0, 0, 0)
    interval = ColorInterval(color, color)
    with pytest.raises(FrozenInstanceError):
        color.red = 100
    with pytest.raises(FrozenInstanceError):
        interval.start = Color(1, 1, 1)
    with pytest.raises(DomainValidationError):
        ColorInterval({}, color)


def test_exact_canonical_keys_and_json_shape():
    color_type = get_data_type("color")
    interval_type = get_data_type("colorInvl")
    start, end = Color(0, 1, 2), Color(100, 150, 200)
    interval = ColorInterval(start, end)
    assert color_type.canonicalize(start) == (0, 1, 2)
    assert interval_type.canonicalize(interval) == ((0, 1, 2), (100, 150, 200))
    assert interval_type.to_json(interval) == {
        "start": {"red": 0, "green": 1, "blue": 2},
        "end": {"red": 100, "green": 150, "blue": 200},
    }
    real_type = get_data_type("real")
    assert real_type.canonicalize(-0.0) == real_type.canonicalize(0.0)
    assert real_type.canonicalize(0.1 + 0.2) != real_type.canonicalize(0.3)
    text_type = get_data_type("string")
    assert len({text_type.canonicalize(s) for s in ["Anna", "anna", "Anna "]}) == 3


@pytest.mark.parametrize("name", ["unknown", "Integer", "colorinvl", " integer ", "", None, []])
def test_unknown_type(name):
    with pytest.raises(DomainValidationError):
        get_data_type(name)


def test_registry_and_abstract_base():
    assert set(TYPE_REGISTRY) == {"integer", "real", "char", "string", "color", "colorInvl"}
    for name, type_class in TYPE_REGISTRY.items():
        assert type(get_data_type(name)) is type_class
        assert isinstance(get_data_type(name), DataType)
    with pytest.raises(TypeError):
        DataType()


def test_validate_does_not_hide_programming_errors():
    class BrokenType(DataType):
        def normalize(self, raw):
            raise RuntimeError("Помилка реалізації")

    with pytest.raises(RuntimeError):
        BrokenType().validate("value")
