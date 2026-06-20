import pytest
from hannah.iobroker import _camel_to_words, _iaq_label, IoBrokerClient, Device


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


class TestIaqLabel:
    def test_good(self):
        assert _iaq_label(50) == "gut"

    def test_okay(self):
        assert _iaq_label(75) == "okay"
        assert _iaq_label(100) == "okay"

    def test_slightly_polluted(self):
        assert _iaq_label(101) == "leicht belastet"
        assert _iaq_label(150) == "leicht belastet"

    def test_bad(self):
        assert _iaq_label(151) == "schlecht"
        assert _iaq_label(286) == "schlecht"


class TestDescribeCategoryAirQuality:
    @pytest.fixture
    def client(self):
        return IoBrokerClient({"host": "localhost", "port": 8093})

    def _device(self, **current):
        return Device(
            id="hannah.0.satellites.sensors.kueche-esp",
            name="Kueche",
            key="kueche",
            room="kueche",
            room_display_name="Küche",
            floor="EG",
            category="air_quality_sensor",
            current=current,
        )

    def test_full_reading(self, client):
        dev = self._device(iaq=286.0, co2_equiv=1654.0, voc_equiv=6.85)
        result = client._describe_category("air_quality_sensor", [dev], "Küche")
        assert "schlecht" in result
        assert "1654.0 ppm" in result
        assert "6.8 ppm" in result or "6.9 ppm" in result

    def test_uncalibrated_defaults(self, client):
        dev = self._device(iaq=50.0, co2_equiv=500.0, voc_equiv=0.5)
        result = client._describe_category("air_quality_sensor", [dev], "Küche")
        assert "gut" in result

    def test_unknown_category_returns_none(self, client):
        assert client._describe_category("does_not_exist", [], "Küche") is None


class TestDescribeCategoryHumidity:
    @pytest.fixture
    def client(self):
        return IoBrokerClient({"host": "localhost", "port": 8093})

    def _device(self, **current):
        return Device(
            id="javascript.0.virtualDevice.Luftfeuchtigkeit.OG.Schlafzimmer.Raumfeuchte",
            name="Raumfeuchte",
            key="raumfeuchte",
            room="schlafzimmer",
            room_display_name="Schlafzimmer",
            floor="OG",
            category="humidity_sensor",
            current=current,
        )

    def test_reading(self, client):
        dev = self._device(current=54.3)
        result = client._describe_category("humidity_sensor", [dev], "Schlafzimmer")
        assert "54.3 %" in result


class TestHandleStateUpdate:
    """Regression: live updates go through state_names reverse-lookup, the initial
    gRPC snapshot does not — a suffix missing from state_names freezes that field
    forever after the first snapshot (Refs #21 follow-up bug)."""

    @pytest.fixture
    def client(self):
        return IoBrokerClient({
            "host": "localhost",
            "port": 8093,
            "state_names": {"iaq": "iaq", "co2_equiv": "co2_equiv", "on": "on"},
        })

    def _device(self, device_id):
        dev = Device(
            id=device_id, name="Sofaecke", key="sofaecke",
            room="wohnzimmer", room_display_name="Wohnzimmer", floor="EG",
            category="air_quality_sensor",
        )
        return dev

    def test_mapped_suffix_updates_cache(self, client):
        device_id = "javascript.0.virtualDevice.AirQuality.EG.Wohnzimmer.Sofaecke"
        dev = self._device(device_id)
        client._devices_by_id[device_id] = dev

        client.handle_state_update(f"{device_id}.iaq", "98")

        assert dev.current["iaq"] == 98

    def test_unmapped_suffix_is_silently_dropped(self, client):
        device_id = "javascript.0.virtualDevice.AirQuality.EG.Wohnzimmer.Sofaecke"
        dev = self._device(device_id)
        dev.current["voc_equiv"] = 0.5  # value from the initial snapshot
        client._devices_by_id[device_id] = dev

        client.handle_state_update(f"{device_id}.voc_equiv", "0.95")

        # "voc_equiv" is missing from state_names in this client's config —
        # the live update never reaches the cache, snapshot value stays frozen.
        assert dev.current["voc_equiv"] == 0.5


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
            room="wohnzimmer", room_display_name="Wohnzimmer", floor="EG", category="Licht",
        )
        dev.current["on"] = True
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.on") == "True"

    def test_device_state_missing_suffix_returns_none(self, client):
        dev = Device(
            id="virtualDevice.Licht.EG.Wohnzimmer.Decke",
            name="Decke", key="decke",
            room="wohnzimmer", room_display_name="Wohnzimmer", floor="EG", category="Licht",
        )
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.level") is None

    def test_state_cache_takes_priority_over_device(self, client):
        client._state_cache["virtualDevice.Licht.EG.Wohnzimmer.Decke.on"] = False
        dev = Device(
            id="virtualDevice.Licht.EG.Wohnzimmer.Decke",
            name="Decke", key="decke",
            room="wohnzimmer", room_display_name="Wohnzimmer", floor="EG", category="Licht",
        )
        dev.current["on"] = True
        client._devices_by_id["virtualDevice.Licht.EG.Wohnzimmer.Decke"] = dev
        assert client.get_state_raw("virtualDevice.Licht.EG.Wohnzimmer.Decke.on") == "False"
