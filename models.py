from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field

class UserBase(SQLModel):
    username: str = Field(unique=True, index=True)
    full_name: str
    department: str
    role: str = Field(default="employee")

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TaskBase(SQLModel):
    title: str
    description: Optional[str] = None
    status: str = Field(default="pending") 
    priority: str = Field(default="medium") 
    due_date: Optional[str] = None
    work_hours: float = Field(default=0.0)
    daily_update: Optional[str] = None

class Task(TaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    assigned_by_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

class TaskHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    employee_id: int = Field(foreign_key="user.id")
    action: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TaskUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    work_hours: Optional[float] = None
    daily_update: Optional[str] = None
