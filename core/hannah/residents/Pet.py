from hannah.residents.Resident import Resident


class Pet(Resident):

    @property
    def id(self) -> str:
        return f"{self.roomie_id}_pet"