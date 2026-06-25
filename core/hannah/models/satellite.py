from hannah.models.base_module import BaseModel

class Satellite(BaseModel):
    __table__ = "satellites"
    __primary_key__ = "device_id"
    __slots__ = (
        "device_id", "seed", "display_name", "room_id", "last_seen", "paired_at", "created_at"
    )