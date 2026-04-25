from typing import Optional, List
from pydantic import BaseModel


class PlayerSlot(BaseModel):
    """Модель одного игрока за столом"""
    # Основные данные
    slot_num: int = 0
    user_id: Optional[int] = None
    full_name: Optional[str] = None
    nickname: str = ""
    username: Optional[str] = None

    # Игровые статусы
    alive: bool = True
    status_reason: str = "Жив"
    fouls: int = 0

    # Роли и команды
    role: str = "Не задана"
    team: Optional[str] = None  # "Красные" или "Чёрные"

    # Очки
    base_points: float = 0.0
    bonus_points: float = 0.0
    lh_points: float = 0.0
    will_protocol_points: float = 0.0
    will_opinion_points: float = 0.0
    dc_points: float = 0.0

    # Флаги наказаний
    kicked: bool = False
    ppk: bool = False
    technical_fouls: List[str] = []  # "small" или "big"
    pu_mark: bool = False

    # Дневные механики
    nominated: bool = False
    votes: int = 0
    night_suspects: List[int] = []  # ID подозреваемых ночью

    # Текстовые поля
    will_protocol_raw: str = ""
    will_opinion: str = ""

    class Config:
        # Позволяет использовать слоты как словари для обратной совместимости
        arbitrary_types_allowed = True

    def to_dict(self) -> dict:
        """Обратная совместимость со старым кодом (словари)"""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerSlot":
        """Создаёт модель из словаря"""
        return cls(**data)


def create_empty_slot(nickname: str = "") -> PlayerSlot:
    """Создаёт пустой слот игрока"""
    return PlayerSlot(nickname=nickname or "Новый игрок")


def slots_to_dict(slots: dict[int, PlayerSlot]) -> dict[int, dict]:
    """Конвертирует слоты в словари для сохранения в БД"""
    return {num: slot.to_dict() for num, slot in slots.items()}


def dict_to_slots(data: dict[int, dict]) -> dict[int, PlayerSlot]:
    """Конвертирует словари из БД обратно в модели"""
    return {int(num): PlayerSlot.from_dict(slot) for num, slot in data.items()}