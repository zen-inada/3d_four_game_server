from pydantic import BaseModel
from typing import List

class MoveRequest(BaseModel):
    x: int
    y: int

class MoveResponse(BaseModel):
    status: str
    board: List[List[List[int]]]
    current_player: int | None = None
    player: int | None = None
    message: str | None = None

class BoardState(BaseModel):
    board: List[List[List[int]]]
    current_player: int
    game_over: bool
