import pytest
from hannah.iobroker import _camel_to_words, IoBrokerClient, Device


class TestCamelToWords:
    def test_camel_case(self):
        assert _camel_to_words("DeckeSeite") == "decke seite"

    def test_underscore(self):
        assert _camel_to_words("Zimmer_Sued") == "zimmer süd"

    def test_number_suffix(self):
        assert _camel_to_words("Deckenlampe_Spot1") == "deckenlampe spot 1"

    def test_umlaut_ae(self):
        assert _camel_to_words("BueroRene") == "büro rene"

    def test_single_word(self):
        assert _camel_to_words("Wohnzimmer") == "wohnzimmer"

    def test_sued_to_sued(self):
        assert _camel_to_words("Sued") == "süd"

    def test_multiple_uppercase(self):
        assert _camel_to_words("EG") == "e g"


class TestParsePayload:
    def test_true(self):
        assert IoBrokerClient._parse_payload("true") is True

    def test_true_mixed_case(self):
        assert IoBrokerClient._parse_payload("True") is True

    def test_false(self):
        assert IoBrokerClient._parse_payload("false") is False

    def test_integer(self):
        result = IoBrokerClient._parse_payload("42")
        assert result == 42
        assert isinstance(result, int)

    def test_negative_integer(self):
        assert IoBrokerClient._parse_payload("-5") == -5

    def test_float(self):
        assert IoBrokerClient._parse_payload("3.14") == pytest.approx(3.14)

    def test_string(self):
        assert IoBrokerClient._parse_payload("hello") == "hello"

    def test_whitespace_stripped(self):
        assert IoBrokerClient._parse_payload("  42  ") == 42

    def test_empty_string(self):
        assert IoBrokerClient._parse_payload("") == ""


class TestGetStateRaw:
    @pytest.fixture
    def client(self):
        return IoBrokerClient({"host": "localhost", "port": 8093})

    def test_state_cache_hit(self, client):
        client._state_cache["openweathermap.0.current.temperature"] = 21.5
        assert client.get_state_raw("openweathermap.0.current.temperature") == "21.5"

    def test_state_cache_none_value(self, client):
        client._state_cache["some.state"] = None
        assert client.get_state_raw("some.state") is None

    def test_unknown_state_returns_none(self, client):
        assert client.get_state_raw("nonexistent.0.state") is None

    def test_device_state_hit(self, client):
        dev = Device(
            id="virtualDevice.Licht.EG.Wohnzimmer.Decke",
            name="Decke", key="decke",
            room="Wohnzimmer", floor="EG", category="Licht",
        )
        dev.current["on"] = True
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.on") == "True"

    def test_device_state_missing_suffix_returns_none(self, client):
        dev = Device(
            id="virtualDevice.Licht.EG.Wohnzimmer.Decke",
            name="Decke", key="decke",
            room="Wohnzimmer", floor="EG", category="Licht",
        )
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.level") is None

    def test_state_cache_takes_priority_over_device(self, client):
        client._state_cache["virtualDevice.Licht.EG.Wohnzimmer.Decke.on"] = False
        dev = Device(
            id="virtualDevice.Licht.EG.Wohnzimmer.Decke",
            name="Decke", key="decke",
            room="Wohnzimmer", floor="EG", category="Licht",
        )
        dev.current["on"] = True
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.on") == "False"
