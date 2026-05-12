# schema/task.py
from pydantic import BaseModel
from typing import List, Literal

class SubTask(BaseModel):
    id: int
    description: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    file_path: str
    error_log: str = ""