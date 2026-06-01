from datetime import datetime, timedelta, timezone
from typing import Optional
from dotenv import load_dotenv
import os
from models import User, Task, TaskHistory, UserBase, TaskBase, TaskUpdate
# Remove the old class definitions (User, Task, etc.) from main.py
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, select, create_engine, func
import bcrypt
import jwt

# ==========================================
# 1. SECURITY & CONFIGURATION
# ==========================================
load_dotenv()

SECRET_KEY = "AIMaven_secure_enterprise_key_2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

# Replace the sqlite_url section with this:
DATABASE_URL = "postgresql://neondb_owner:npg_rxHIfh8Kl5uZ@ep-young-unit-apvpsslw.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require"
engine = create_engine(DATABASE_URL)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ==========================================
# 2. DATABASE MODELS
# ==========================================




class UserCreate(UserBase):
    password: str

class UserPublic(UserBase):
    id: int
    created_at: datetime




# ==========================================
# 3. UTILITIES & DEPENDENCIES
# ==========================================
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: 
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception
        
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None: 
        raise credentials_exception
    return user

def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

# ==========================================
# 4. APP INITIALIZATION & STARTUP
# ==========================================
app = FastAPI(title="AIMaven API")



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    with Session(engine) as session:
        admin_exists = session.exec(select(User).where(User.role == "admin")).first()
        if not admin_exists:
            admin = User(
                username="admin", 
                full_name="System Administrator", 
                department="Management", 
                role="admin", 
                hashed_password=get_password_hash("admin123")
            )
            session.add(admin)
            session.commit()

# ==========================================
# 5. AUTHENTICATION ROUTES
# ==========================================
@app.post("/auth/register", response_model=UserPublic, tags=["Auth"])
def register(user_data: UserCreate, session: Session = Depends(get_session)):
    if session.exec(select(User).where(User.username == user_data.username)).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user_data.role = "employee" 
    new_user = User(username=user_data.username, full_name=user_data.full_name, department=user_data.department, role=user_data.role, hashed_password=get_password_hash(user_data.password))
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return new_user

@app.post("/auth/login", tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect credentials")
    token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": token, "token_type": "bearer", "role": user.role, "full_name": user.full_name}

# ==========================================
# 6. EMPLOYEE ROUTES
# ==========================================
@app.post("/employee/tasks", response_model=Task, tags=["Employee"])
def create_task(task_in: TaskBase, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    task = Task(**task_in.model_dump(), owner_id=current_user.id)
    session.add(task)
    session.commit()
    session.refresh(task)
    session.add(TaskHistory(task_id=task.id, employee_id=current_user.id, action="Deployed new task"))
    session.commit()
    return task



class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Broadcast the message to all connected clients
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/employee/tasks", response_model=list[Task], tags=["Employee"])
def get_my_tasks(current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return session.exec(select(Task).where(Task.owner_id == current_user.id)).all()

@app.patch("/employee/tasks/{task_id}", response_model=Task, tags=["Employee"])
def update_task(task_id: int, update_data: TaskUpdate, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    task = session.exec(select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)).first()
    if not task: 
        raise HTTPException(status_code=404, detail="Task not found")
    
    data = update_data.model_dump(exclude_unset=True)
    if "status" in data and data["status"] == "completed" and task.status != "completed":
        task.completed_at = datetime.now(timezone.utc)
        
    for k, v in data.items():
        setattr(task, k, v)
        
    session.add(task)
    action_msg = f"Updated status to {data.get('status', task.status).upper()}" if "status" in data else "Updated task details"
    session.add(TaskHistory(task_id=task.id, employee_id=current_user.id, action=action_msg))
    session.commit()
    session.refresh(task)
    return task

@app.delete("/employee/tasks/{task_id}", tags=["Employee"])
def delete_task(task_id: int, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    task = session.exec(select(Task).where(Task.id == task_id, Task.owner_id == current_user.id)).first()
    if not task: 
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.add(TaskHistory(task_id=task_id, employee_id=current_user.id, action="Deleted task"))
    session.commit()
    return {"ok": True}

# ==========================================
# 7. ADMIN ROUTES
# ==========================================
@app.get("/admin/analytics", tags=["Admin"])
def get_analytics(admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    total_emps = session.exec(select(func.count(User.id)).where(User.role == "employee")).first()
    total_tasks = session.exec(select(func.count(Task.id))).first()
    completed = session.exec(select(func.count(Task.id)).where(Task.status == "completed")).first()
    pending = total_tasks - completed
    return {"employees": total_emps, "total_tasks": total_tasks, "completed": completed, "pending": pending}

@app.get("/admin/users", response_model=list[UserPublic], tags=["Admin"])
def get_all_users(admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    return session.exec(select(User).where(User.role == "employee")).all()

@app.get("/admin/tasks", tags=["Admin"])
def get_all_tasks(admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    tasks = session.exec(select(Task)).all()
    users = {u.id: u.full_name for u in session.exec(select(User)).all()}
    result = []
    for t in tasks:
        td = t.model_dump()
        td["owner_name"] = users.get(t.owner_id, "Unknown User")
        result.append(td)
    return result

@app.post("/admin/assign-task", tags=["Admin"])
def assign_task(title: str, description: str, priority: str, due_date: str, owner_id: int, admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    emp = session.exec(select(User).where(User.id == owner_id, User.role == "employee")).first()
    if not emp: 
        raise HTTPException(status_code=404, detail="Employee not found")
    task = Task(title=title, description=description, priority=priority, due_date=due_date, owner_id=owner_id, assigned_by_admin=True)
    session.add(task)
    session.commit()
    session.add(TaskHistory(task_id=task.id, employee_id=admin.id, action=f"Admin assigned task to {emp.full_name}"))
    session.commit()
    return {"message": "Task assigned successfully"}

@app.delete("/admin/tasks/{task_id}", tags=["Admin"])
def admin_delete_task(task_id: int, admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    task = session.exec(select(Task).where(Task.id == task_id)).first()
    if not task: 
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()
    return {"ok": True}

# --- NEW: SYSTEM AUDIT LOG ---
@app.get("/admin/history", tags=["Admin"])
def get_audit_log(admin: User = Depends(get_admin_user), session: Session = Depends(get_session)):
    # Fetch last 50 actions
    histories = session.exec(select(TaskHistory).order_by(TaskHistory.timestamp.desc()).limit(50)).all()
    users = {u.id: u.full_name for u in session.exec(select(User)).all()}
    tasks = {t.id: t.title for t in session.exec(select(Task)).all()}
    
    result = []
    for h in histories:
        result.append({
            "id": h.id,
            "action": h.action,
            "timestamp": h.timestamp.isoformat(),
            "employee_name": users.get(h.employee_id, "System / Deleted User"),
            "task_title": tasks.get(h.task_id, "Deleted Task")
        })
    return result
