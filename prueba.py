import random
import os
import threading
import asyncio
import atexit
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# --- Configuración de Base de Datos (local, archivo SQLite) ---
DB_NAME = "flowerland.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///./{DB_NAME}")

# SQLite necesita este flag porque el bot corre en un hilo aparte de FastAPI
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Configuración de Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8206009148:AAEEWSYAgxj3MRR8xGOe-s7V5COl5htsYnY")
ADMIN_ID = 6808824866
GRUPO_TELEGRAM_ID = int(os.getenv("GRUPO_TELEGRAM_ID", "-1001234567890"))
MINI_APP_URL = "https://aesthetic-chaja-a87a4e.netlify.app/" 

try:
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
except Exception as e:
    print(f"Error inicializando el bot de Telegram: {e}")
    bot = None

# --- Modelos de Base de Datos ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    lan_balance = Column(Float, default=0.0)
    telegram_id = Column(Integer, nullable=True)
    is_admin = Column(Boolean, default=False)

class Land(Base):
    __tablename__ = "lands"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    type = Column(String)
    slots_total = Column(Integer)
    is_free_land = Column(Boolean, default=False)

class Plant(Base):
    __tablename__ = "plants"
    id = Column(Integer, primary_key=True, index=True)
    land_id = Column(Integer, ForeignKey("lands.id"))
    name = Column(String)
    rarity = Column(String)
    total_time_hours = Column(Float)
    start_time = Column(DateTime, default=datetime.utcnow)
    is_harvested = Column(Boolean, default=False)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    type = Column(String)
    amount = Column(Float)
    status = Column(String, default="pendiente")
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(Integer, nullable=True)

try:
    print(f"Verificando tablas en la base de datos local '{DB_NAME}'...")
    Base.metadata.create_all(bind=engine)
    print("Base de datos local lista y conectada.")
except Exception as db_err:
    print(f"Tablas listas o error al conectar con la base de datos local: {db_err}")

PLANT_DEFINITIONS = {
    "Comun": {"min_time": 1, "max_time": 4, "price": 5, "lan_reward_min": 10, "lan_reward_max": 20},
    "PocoComun": {"min_time": 5, "max_time": 12, "price": 15, "lan_reward_min": 30, "lan_reward_max": 50},
    "Epica": {"min_time": 13, "max_time": 24, "price": 40, "lan_reward_min": 80, "lan_reward_max": 150},
    "Legendaria": {"min_time": 25, "max_time": 72, "price": 100, "lan_reward_min": 200, "lan_reward_max": 500}
}

LAND_PRICES = {"Comun": 10, "Rara": 30, "Legendaria": 80}

class PlantResponse(BaseModel):
    id: int
    name: str
    rarity: str
    total_time_hours: float
    progress_percent: float
    time_remaining_hours: float
    is_ready: bool

class BuyLandRequest(BaseModel):
    land_type: str

class PlantSeedRequest(BaseModel):
    land_id: int
    slot_index: int
    rarity: str

class LinkTelegramRequest(BaseModel):
    telegram_id: int

class TransactionRequest(BaseModel):
    type: str  
    amount: float

class ProcessTransactionRequest(BaseModel):
    transaction_id: int
    action: str  

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_admin(telegram_id: int, db: Session):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo administradores.")
    return user

# --- Instancia de FastAPI ---
app = FastAPI(title="GranjaP2P API")

# --- Controladores de Mensajes de Telegram ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        try:
            chat_id = message.chat.id
            first_name = message.from_user.first_name
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🌾 Jugar FlowerLand", web_app=WebAppInfo(url=MINI_APP_URL)))
            
            welcome_text = (
                f"¡Hola *{first_name}*! 👋\n\n"
                f"Bienvenido a *FlowerLand*, tu granja P2E.\n"
                f"Presiona el botón de abajo para empezar a jugar."
            )
            bot.send_message(chat_id, welcome_text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"Error en comando start: {e}")

    @bot.message_handler(commands=['help'])
    def send_help(message):
        help_text = "📌 *Comandos:*\n\n/start - Abrir app\n/help - Ayuda"
        bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

# --- Polling Asíncrono Correcto para Render ---
def run_bot():
    if bot:
        print("🤖 [Telegram] Iniciando polling del bot de forma segura...")
        try:
            bot.remove_webhook()
            bot.infinity_polling(timeout=30, long_polling_timeout=15, skip_pending=True, drop_pending_updates=True)
        except Exception as e:
            print(f"❌ [Telegram] Error crítico en polling: {e}")

# --- Evento de Inicio Seguro de FastAPI ---
@app.on_event("startup")
async def startup_event():
    # Esto arranca el bot de Telegram de fondo garantizando que Render no mate el proceso al encender Uvicorn
    thread = threading.Thread(target=run_bot)
    thread.daemon = True
    thread.start()
    print("🚀 [FastAPI] Hilo de Telegram lanzado en segundo plano.")

# Función para cerrar el bot correctamente
@atexit.register
def shutdown_handler():
    if bot:
        print("🛑 Cerrando bot de Telegram...")
        bot.stop_polling()

# --- Funciones de Notificaciones ---
def send_telegram_notification(chat_id: int, message: str):
    if bot and chat_id:
        try: bot.send_message(chat_id, message, parse_mode="Markdown")
        except Exception as e: print(f"Error notificación: {e}")

def notify_admin(message: str): send_telegram_notification(ADMIN_ID, f"🔔 *Admin Alert*\n{message}")
def notify_user(user_id: int, message: str): send_telegram_notification(user_id, message)

def calculate_progress(plant: Plant):
    elapsed = datetime.utcnow() - plant.start_time
    elapsed_hours = elapsed.total_seconds() / 3600
    progress = min(100, (elapsed_hours / plant.total_time_hours) * 100)
    remaining = max(0, plant.total_time_hours - elapsed_hours)
    return round(progress, 2), round(remaining, 2), progress >= 99.9

def get_random_plant_name(rarity: str):
    names = {
        "Comun": ["Tomate", "Lechuga", "Zanahoria"],
        "PocoComun": ["Fresa", "Pimiento", "Cebolla"],
        "Epica": ["Orquídea", "Girasol Gigante", "Cactus Dorado"],
        "Legendaria": ["Árbol Eterno", "Flor Lunar", "Raíz Ancestral"]
    }
    return random.choice(names.get(rarity, ["Planta Desconocida"]))

# --- Endpoints Públicos ---
@app.post("/register/{username}")
def register_user(username: str, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == username).first()
    if existing: raise HTTPException(status_code=400, detail="Usuario ya existe")
    new_user = User(username=username, lan_balance=0.0)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Usuario registrado", "username": username}

@app.get("/user/{username}")
def get_user_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(status_code=404, detail="Usuario no encontrado")
    lands = db.query(Land).filter(Land.user_id == user.id).all()
    return {
        "username": user.username, "lan_balance": user.lan_balance, "telegram_id": user.telegram_id,
        "lands": [{"id": l.id, "type": l.type, "slots": l.slots_total} for l in lands]
    }

@app.post("/link-telegram/{username}")
def link_telegram(username: str, request: LinkTelegramRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.telegram_id = request.telegram_id
    db.commit()
    notify_user(request.telegram_id, f"✅ ¡Hola {username}! Tu cuenta ha sido vinculada.")
    return {"message": "Telegram vinculado correctamente"}

@app.post("/buy-land")
def buy_land(request: BuyLandRequest, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    price = LAND_PRICES.get(request.land_type)
    if not price or user.lan_balance < price: raise HTTPException(status_code=400, detail="Saldo insuficiente")
    slots_map = {"Comun": 4, "Rara": 8, "Legendaria": 12}
    user.lan_balance -= price
    new_land = Land(user_id=user.id, type=request.land_type, slots_total=slots_map[request.land_type])
    db.add(new_land)
    db.commit()
    return {"message": "Tierra comprada", "new_balance": user.lan_balance}

@app.post("/plant-seed")
def plant_seed(request: PlantSeedRequest, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    land = db.query(Land).filter(Land.id == request.land_id, Land.user_id == user.id).first()
    rarity_config = PLANT_DEFINITIONS.get(request.rarity)
    if not land or not rarity_config or user.lan_balance < rarity_config["price"]:
        raise HTTPException(status_code=400, detail="Error de requisitos")
    random_time = random.uniform(rarity_config["min_time"], rarity_config["max_time"])
    new_plant = Plant(land_id=request.land_id, name=get_random_plant_name(request.rarity), rarity=request.rarity, total_time_hours=random_time)
    user.lan_balance -= rarity_config["price"]
    db.add(new_plant)
    db.commit()
    return {"message": "Planta sembrada"}

@app.get("/my-plants/{username}", response_model=List[PlantResponse])
def get_my_plants(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    user_lands = db.query(Land).filter(Land.user_id == user.id).all()
    plants = db.query(Plant).filter(Plant.land_id.in_([l.id for l in user_lands]), Plant.is_harvested == False).all()
    result = []
    for p in plants:
        progress, remaining, is_ready = calculate_progress(p)
        result.append(PlantResponse(id=p.id, name=p.name, rarity=p.rarity, total_time_hours=p.total_time_hours, progress_percent=progress, time_remaining_hours=remaining, is_ready=is_ready))
    return result

@app.post("/harvest/{plant_id}")
def harvest_plant(plant_id: int, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    progress, remaining, is_ready = calculate_progress(plant)
    if not is_ready: raise HTTPException(status_code=400, detail="Cultivo no listo")
    reward = random.uniform(PLANT_DEFINITIONS[plant.rarity]["lan_reward_min"], PLANT_DEFINITIONS[plant.rarity]["lan_reward_max"])
    user.lan_balance += reward
    plant.is_harvested = True
    db.commit()
    return {"message": "Cosechado", "reward": round(reward, 2)}

@app.get("/grupo/info")
def get_grupo_info(): return {"grupo_id": GRUPO_TELEGRAM_ID}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
