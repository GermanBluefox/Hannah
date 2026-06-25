from hannah.residents.Resident import Resident


class Roomie(Resident):

    @property
    def id(self) -> str:
        return f"{self.roomie_id}_roomie"