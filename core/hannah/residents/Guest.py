from hannah.residents.Resident import Resident


class Guest(Resident):

    @property
    def id(self) -> str:
        return f"{self.roomie_id}_guest"