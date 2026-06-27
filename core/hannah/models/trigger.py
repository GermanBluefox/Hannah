from hannah.models.base_module import BaseModel

class Trigger(BaseModel):
    __table__ = "triggers"
    __primary_key__ = "id"
    __slots__ = ("id", "when", "cancel_when", "on_response", "say", "ask", "rephrase", "room", "cooldown", "delay", "created_at")
    __json_fields__ = ("when", "cancel_when", "on_response")