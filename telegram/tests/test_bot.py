import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from hannah_telegram.bot import (
    HannahBot,
    _UNKNOWN_USER,
    _WELCOME,
    _car_proto_to_message,
    _cb_device,
    _cb_room,
    _cb_rooms,
    _cb_ctrl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user(trust_level: int = 5, display_name: str = "Test", roomie_id: str = "test"):
    user = MagicMock()
    user.trust_level = trust_level
    user.display_name = display_name
    user.roomie_id = roomie_id
    user.linked_accounts = {}
    return user


def _make_hannah(
    *,
    known: bool = False,
    user=None,
    submit_answer: str = "Alles klar.",
    submit_intent: str = "",
):
    """Minimal HannahClient mock."""
    hannah = MagicMock()
    _user = user or (_make_user() if known else None)
    hannah.get_user_by_telegram = AsyncMock(return_value=(known, _user))
    hannah.get_user_by_roomie = AsyncMock(return_value=(False, None, None))
    hannah.link_account = AsyncMock(return_value=(True, "ok"))
    hannah.get_all_car_states = AsyncMock(return_value=[])
    resp = MagicMock()
    resp.answer = submit_answer
    resp.intent_name = submit_intent
    hannah.submit_text_full = AsyncMock(return_value=resp)
    return hannah


def _make_update(chat_id: int = 12345, text: str = "Hallo", args: list | None = None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    ctx = MagicMock()
    ctx.args = args or []
    return update, ctx


def _make_bot(hannah=None) -> HannahBot:
    return HannahBot(token="test-token", hannah=hannah or _make_hannah())


def _make_car_state(**kwargs) -> SimpleNamespace:
    defaults = dict(
        display_name="Golf",
        plate="MYK-LG 1",
        is_moving=False,
        address="Musterstraße 1, 56841 Traben-Trarbach",
        home_address="Musterstraße 1, 56841",
        latitude=49.95,
        longitude=7.12,
        is_car_locked=True,
        door_lock_status="locked",
        doors={},
        windows={},
        odometer=42000,
        total_range=350,
        position_date=0,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestIsPrivateChat:
    def test_positive_id_is_private(self):
        from hannah_telegram.bot import HannahBot
        assert HannahBot._is_private_chat("12345") is True

    def test_negative_id_is_group(self):
        assert HannahBot._is_private_chat("-100123456") is False

    def test_zero_is_not_private(self):
        assert HannahBot._is_private_chat("0") is False

    def test_invalid_string(self):
        assert HannahBot._is_private_chat("not-a-number") is False


class TestCbHelpers:
    def test_cb_rooms(self):
        assert _cb_rooms() == "haus:rooms"

    def test_cb_room(self):
        assert _cb_room(3) == "haus:r:3"

    def test_cb_device(self):
        assert _cb_device(1, 2) == "haus:d:1:2"

    def test_cb_ctrl(self):
        assert _cb_ctrl(0, 1, "on", "true") == "haus:c:0:1:on:true"

    def test_cb_ctrl_color(self):
        assert _cb_ctrl(0, 0, "color", "#FF0000") == "haus:c:0:0:color:#FF0000"


class TestCarProtoToMessage:
    def test_parked_at_home(self):
        state = _make_car_state()
        msg = _car_proto_to_message(state)
        assert "zu Hause" in msg
        assert "Golf" in msg

    def test_moving(self):
        state = _make_car_state(is_moving=True)
        msg = _car_proto_to_message(state)
        assert "fährt" in msg

    def test_parked_elsewhere(self):
        state = _make_car_state(home_address="Zuhause", address="Bahnhofstr. 1, Köln")
        msg = _car_proto_to_message(state)
        assert "steht an" in msg

    def test_unlocked_shows_warning(self):
        state = _make_car_state(is_car_locked=False, door_lock_status="unlocked")
        msg = _car_proto_to_message(state)
        assert "nicht abgeschlossen" in msg

    def test_locked_shows_ok(self):
        state = _make_car_state()
        msg = _car_proto_to_message(state)
        assert "abgeschlossen" in msg

    def test_open_door_shows_warning(self):
        state = _make_car_state(doors={"frontLeft": False})
        msg = _car_proto_to_message(state)
        assert "Fahrerseite" in msg

    def test_odometer_shown(self):
        state = _make_car_state(odometer=12345)
        msg = _car_proto_to_message(state)
        assert "12345" in msg


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------

class TestOnText:
    @pytest.mark.asyncio
    async def test_unknown_user_gets_link_hint(self):
        bot = _make_bot(_make_hannah(known=False))
        update, ctx = _make_update()
        await bot._on_text(update, ctx)
        update.message.reply_text.assert_called_once_with(_UNKNOWN_USER)

    @pytest.mark.asyncio
    async def test_known_user_calls_submit_text(self):
        hannah = _make_hannah(known=True, submit_answer="Licht an.")
        bot = _make_bot(hannah)
        update, ctx = _make_update(text="Mach das Licht an")
        await bot._on_text(update, ctx)
        hannah.submit_text_full.assert_called_once_with("Mach das Licht an", "12345")

    @pytest.mark.asyncio
    async def test_known_user_answer_is_sent(self):
        bot = _make_bot(_make_hannah(known=True, submit_answer="Licht an."))
        update, ctx = _make_update(text="Mach das Licht an")
        await bot._on_text(update, ctx)
        update.message.reply_text.assert_called_once()
        assert "Licht an." in update.message.reply_text.call_args[0][0]


class TestCmdStart:
    @pytest.mark.asyncio
    async def test_unknown_user_gets_welcome(self):
        bot = _make_bot(_make_hannah(known=False))
        update, ctx = _make_update()
        await bot._cmd_start(update, ctx)
        update.message.reply_text.assert_called_once_with(_WELCOME)

    @pytest.mark.asyncio
    async def test_known_user_gets_greeting(self):
        bot = _make_bot(_make_hannah(known=True))
        update, ctx = _make_update()
        await bot._cmd_start(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert text != _WELCOME


class TestCmdLink:
    @pytest.mark.asyncio
    async def test_no_args_prompts_for_roomie_id(self):
        bot = _make_bot()
        update, ctx = _make_update(args=[])
        await bot._cmd_link(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "roomie" in text.lower() or "Roomie" in text

    @pytest.mark.asyncio
    async def test_unknown_roomie_id_reports_error(self):
        bot = _make_bot(_make_hannah(known=False))
        update, ctx = _make_update(args=["unbekannt"])
        await bot._cmd_link(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "nicht gefunden" in text

    @pytest.mark.asyncio
    async def test_valid_roomie_id_calls_link_account(self):
        user = _make_user(trust_level=5)
        hannah = _make_hannah(known=False)
        hannah.get_user_by_roomie = AsyncMock(return_value=(True, user, None))
        hannah.link_account = AsyncMock(return_value=(True, "ok"))
        bot = _make_bot(hannah)
        update, ctx = _make_update(chat_id=99999, args=["leonie"])
        await bot._cmd_link(update, ctx)
        hannah.link_account.assert_called_once_with("leonie", "99999", None)

    @pytest.mark.asyncio
    async def test_group_chat_rejected(self):
        bot = _make_bot()
        update, ctx = _make_update(chat_id=-100123456, args=["leonie"])
        await bot._cmd_link(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "privaten Chat" in text


class TestHasTrust:
    @pytest.mark.asyncio
    async def test_unknown_user_has_no_trust(self):
        bot = _make_bot(_make_hannah(known=False))
        ok, user = await bot._has_trust("12345", 5)
        assert ok is False
        assert user is None

    @pytest.mark.asyncio
    async def test_sufficient_trust_level(self):
        user = _make_user(trust_level=8)
        bot = _make_bot(_make_hannah(known=True, user=user))
        ok, _ = await bot._has_trust("12345", 7)
        assert ok is True

    @pytest.mark.asyncio
    async def test_insufficient_trust_level(self):
        user = _make_user(trust_level=3)
        bot = _make_bot(_make_hannah(known=True, user=user))
        ok, _ = await bot._has_trust("12345", 7)
        assert ok is False
