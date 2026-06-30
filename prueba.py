import random
import os
import threading
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Configuración de Base de Datos ---
DATABASE_URL = "sqlite:///./granja_p2p.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Configuración de Telegram ---
TELEGRAM_BOT_TOKEN = "8206009148:AAFN8kiDJZ9yIxeIL3JWC00DBeWRHRjMMOw"
ADMIN_ID = 6808824866

# --- ESPACIOS PARA CONFIGURAR DESPUÉS ---
# Reemplaza el ID ficticio por el ID real de tu grupo de Telegram (debe empezar con -100)
GRUPO_TELEGRAM_ID = int(os.getenv("GRUPO_TELEGRAM_ID", "-1001234567890"))  
# Reemplaza esta URL por el enlace directo a tu Mini App / Web App de Telegram
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
    type = Column(String)  # "recarga" o "retiro"
    amount = Column(Float)
    status = Column(String, default="pendiente")  # pendiente, aprobado, rechazado
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(Integer, nullable=True)  # ID del admin que procesó

Base.metadata.create_all(bind=engine)

# --- Definiciones ---
PLANT_DEFINITIONS = {
    "Comun": {"min_time": 1, "max_time": 4, "price": 5, "lan_reward_min": 10, "lan_reward_max": 20},
    "PocoComun": {"min_time": 5, "max_time": 12, "price": 15, "lan_reward_min": 30, "lan_reward_max": 50},
    "Epica": {"min_time": 13, "max_time": 24, "price": 40, "lan_reward_min": 80, "lan_reward_max": 150},
    "Legendaria": {"min_time": 25, "max_time": 72, "price": 100, "lan_reward_min": 200, "lan_reward_max": 500}
}

LAND_PRICES = {
    "Comun": 10,
    "Rara": 30,
    "Legendaria": 80
}

# --- Esquemas Pydantic ---
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

# --- Dependencias ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_admin(telegram_id: int, db: Session):
    """Verifica si el usuario es administrador"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Acceso denegado. Solo administradores.")
    return user

app = FastAPI(title="GranjaP2P API")

# --- LÓGICA DE ESCUCHA DE TELEGRAM (COMANDOS Y BOTONES) ---
if bot:
    @bot.message_handler(commands=['start'])
    def handle_start_command(message):
        chat_id = message.chat.id
        first_name = message.from_user.first_name
        
        # Estructura del menú con botones integrados
        markup = InlineKeyboardMarkup(row_width=2)
        btn_play = InlineKeyboardButton(text="🎮 Jugar Ahora", url=MINI_APP_URL)
        btn_group = InlineKeyboardButton(text="📢 Grupo Oficial", url=f"https://t.me/TuGrupoLink") 
        btn_profile = InlineKeyboardButton(text="👤 Mi Perfil", callback_data="view_profile")
        
        markup.add(btn_play)
        markup.add(btn_group, btn_profile)
        
        texto_bienvenida = (
            f"¡Hola *{first_name}*! 🌾 Bienvenido a *FlowerLand*.\n\n"
            "Gestiona tus tierras, siembra semillas y cosecha recompensas directamente desde nuestra app.\n"
            "Selecciona una opción del menú interactivo:"
        )
        bot.send_message(chat_id, texto_bienvenida, reply_markup=markup, parse_mode="Markdown")

    @bot.callback_query_handler(func=lambda call: True)
    def handle_buttons_callback(call):
        if call.data == "view_profile":
            texto_perfil = (
                f"👤 *Tu Perfil de Usuario*\n\n"
                f"ID de Telegram: `{call.from_user.id}`\n"
                "Para ver tu balance actual y tus tierras, abre la MiniApp usando el botón principal."
            )
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, texto_perfil, parse_mode="Markdown")

# --- Funciones de Telegram (Notificaciones) ---
def send_telegram_notification(chat_id: int, message: str):
    if bot and chat_id:
        try:
            bot.send_message(chat_id, message, parse_mode="Markdown")
        except Exception as e:
            print(f"Error enviando mensaje a Telegram: {e}")

def notify_admin(message: str):
    send_telegram_notification(ADMIN_ID, f"🔔 *Admin Alert*\n{message}")

def notify_user(user_id: int, message: str):
    send_telegram_notification(user_id, message)

# --- Funciones Auxiliares ---
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
    if existing:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    
    new_user = User(username=username, lan_balance=0.0)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Usuario registrado", "username": username}

@app.get("/user/{username}")
def get_user_profile(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    lands = db.query(Land).filter(Land.user_id == user.id).all()
    return {
        "username": user.username,
        "lan_balance": user.lan_balance,
        "telegram_id": user.telegram_id,
        "is_admin": user.is_admin,
        "lands": [{"id": l.id, "type": l.type, "slots": l.slots_total} for l in lands]
    }

@app.post("/link-telegram/{username}")
def link_telegram(username: str, request: LinkTelegramRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    user.telegram_id = request.telegram_id
    db.commit()
    
    notify_user(request.telegram_id, f"✅ ¡Hola {username}! Tu cuenta ha sido vinculada.")
    notify_admin(f"El usuario {username} vinculó Telegram ID: {request.telegram_id}")
    return {"message": "Telegram vinculado correctamente"}

# --- Endpoints de Transacciones ---

@app.post("/transaction/request/{username}")
def request_transaction(username: str, request: TransactionRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if request.type not in ["recarga", "retiro"]:
        raise HTTPException(status_code=400, detail="Tipo de transacción inválido")
    
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="Monto debe ser positivo")
    
    if request.type == "retiro" and user.lan_balance < request.amount:
        raise HTTPException(status_code=400, detail="Saldo insuficiente para retiro")
    
    transaction = Transaction(user_id=user.id, type=request.type, amount=request.amount, status="pendiente")
    db.add(transaction)
    db.commit()
    
    msg = f"💰 *Nueva Solicitud*\nUsuario: {username}\nTipo: {request.type.upper()}\nMonto: {request.amount} LAN\nID: {transaction.id}"
    notify_admin(msg)
    try:
        send_telegram_notification(GRUPO_TELEGRAM_ID, f"📢 Nueva solicitud de {request.type} por {username}")
    except:
        pass
    return {"message": f"Solicitud de {request.type} enviada", "transaction_id": transaction.id}

@app.get("/transaction/pending")
def get_pending_transactions(telegram_id: int, db: Session = Depends(get_db)):
    admin = verify_admin(telegram_id, db)
    pending = db.query(Transaction).filter(Transaction.status == "pendiente").all()
    result = []
    for t in pending:
        user = db.query(User).filter(User.id == t.user_id).first()
        result.append({
            "id": t.id,
            "username": user.username if user else "Desconocido",
            "type": t.type,
            "amount": t.amount,
            "created_at": t.created_at.isoformat()
        })
    return result

@app.post("/transaction/process")
def process_transaction(request: ProcessTransactionRequest, telegram_id: int, db: Session = Depends(get_db)):
    admin = verify_admin(telegram_id, db)
    transaction = db.query(Transaction).filter(Transaction.id == request.transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transacción no encontrada")
    
    if transaction.status != "pendiente":
        raise HTTPException(status_code=400, detail="Transacción ya procesada")
    
    user = db.query(User).filter(User.id == transaction.user_id).first()
    
    if request.action == "aprobar":
        transaction.status = "aprobado"
        transaction.processed_at = datetime.utcnow()
        transaction.processed_by = admin.id
        
        if transaction.type == "recarga":
            user.lan_balance += transaction.amount
            msg = f"✅ *Recarga Aprobada*\nMonto: {transaction.amount} LAN\nNuevo saldo: {user.lan_balance} LAN"
        elif transaction.type == "retiro":
            user.lan_balance -= transaction.amount
            msg = f"✅ *Retiro Aprobado*\nMonto: {transaction.amount} LAN\nSaldo restante: {user.lan_balance} LAN"
        
        if user.telegram_id:
            notify_user(user.telegram_id, msg)
        notify_admin(f"Transacción #{transaction.id} aprobada para {user.username}")
        
    elif request.action == "rechazar":
        transaction.status = "rechazado"
        transaction.processed_at = datetime.utcnow()
        transaction.processed_by = admin.id
        msg = f"❌ *Transacción Rechazada*\nTipo: {transaction.type}\nMonto: {transaction.amount} LAN"
        if user.telegram_id:
            notify_user(user.telegram_id, msg)
        notify_admin(f"Transacción #{transaction.id} rechazada para {user.username}")
    else:
        raise HTTPException(status_code=400, detail="Acción inválida")
    
    db.commit()
    return {"message": f"Transacción {request.action}da exitosamente"}

# --- Endpoints del Juego ---

@app.post("/buy-land")
def buy_land(request: BuyLandRequest, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    price = LAND_PRICES.get(request.land_type)
    if not price:
        raise HTTPException(status_code=400, detail="Tipo de tierra inválido")
    
    if user.lan_balance < price:
        raise HTTPException(status_code=400, detail="Saldo LAN insuficiente")
    
    slots_map = {"Comun": 4, "Rara": 8, "Legendaria": 12}
    user.lan_balance -= price
    new_land = Land(user_id=user.id, type=request.land_type, slots_total=slots_map[request.land_type], is_free_land=False)
    db.add(new_land)
    db.commit()
    
    msg = f"🌱 *Nueva Compra*\nUsuario: {username}\nTierra: {request.land_type}\nSaldo: {user.lan_balance} LAN"
    if user.telegram_id:
        notify_user(user.telegram_id, msg)
    notify_admin(msg)
    return {"message": f"Tierra {request.land_type} comprada", "new_balance": user.lan_balance}

@app.post("/plant-seed")
def plant_seed(request: PlantSeedRequest, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    land = db.query(Land).filter(Land.id == request.land_id, Land.user_id == user.id).first()
    if not land:
        raise HTTPException(status_code=404, detail="Tierra no encontrada")
    
    existing_plants = db.query(Plant).filter(Plant.land_id == request.land_id).count()
    if existing_plants >= land.slots_total:
        raise HTTPException(status_code=400, detail="No hay slots disponibles")

    rarity_config = PLANT_DEFINITIONS.get(request.rarity)
    if not rarity_config:
        raise HTTPException(status_code=400, detail="Rareza inválida")
    
    seed_cost = rarity_config["price"]
    if user.lan_balance < seed_cost:
        raise HTTPException(status_code=400, detail="Saldo insuficiente")
    
    random_time = random.uniform(rarity_config["min_time"], rarity_config["max_time"])
    plant_name = get_random_plant_name(request.rarity)
    
    new_plant = Plant(land_id=request.land_id, name=plant_name, rarity=request.rarity, total_time_hours=random_time, start_time=datetime.utcnow(), is_harvested=False)
    user.lan_balance -= seed_cost
    db.add(new_plant)
    db.commit()
    
    msg = f"🌿 *Sembrado*\n{username}: {plant_name} ({request.rarity})\nTiempo: {round(random_time, 2)}h"
    if user.telegram_id:
        notify_user(user.telegram_id, msg)
    return {"message": "Planta sembrada", "plant_name": plant_name, "total_time_hours": round(random_time, 2), "new_balance": user.lan_balance}

@app.get("/my-plants/{username}", response_model=List[PlantResponse])
def get_my_plants(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    user_lands = db.query(Land).filter(Land.user_id == user.id).all()
    land_ids = [l.id for l in user_lands]
    plants = db.query(Plant).filter(Plant.land_id.in_(land_ids), Plant.is_harvested == False).all()
    
    result = []
    for p in plants:
        progress, remaining, is_ready = calculate_progress(p)
        result.append(PlantResponse(id=p.id, name=p.name, rarity=p.rarity, total_time_hours=p.total_time_hours, progress_percent=progress, time_remaining_hours=remaining, is_ready=is_ready))
    return result

@app.post("/harvest/{plant_id}")
def harvest_plant(plant_id: int, username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Planta no encontrada")
    
    land = db.query(Land).filter(Land.id == plant.land_id, Land.user_id == user.id).first()
    if not land:
        raise HTTPException(status_code=403, detail="Sin permiso")
    
    progress, remaining, is_ready = calculate_progress(plant)
    if not is_ready:
        raise HTTPException(status_code=400, detail=f"Faltan {remaining} horas")
    
    rarity_config = PLANT_DEFINITIONS[plant.rarity]
    reward = random.uniform(rarity_config["lan_reward_min"], rarity_config["lan_reward_max"])
    
    user.lan_balance += reward
    plant.is_harvested = True
    db.commit()
    
    msg = f"💰 *¡Cosecha!*\n{username}: +{round(reward, 2)} LAN\nSaldo: {user.lan_balance} LAN"
    if user.telegram_id:
        notify_user(user.telegram_id, msg)
    notify_admin(f"Cosecha: {username} +{round(reward, 2)} LAN")
    return {"message": f"Cosecha exitosa: {round(reward, 2)} LAN", "reward": round(reward, 2), "new_balance": user.lan_balance}

# --- Panel de Administrador ---

@app.get("/admin/dashboard")
def admin_dashboard(telegram_id: int, db: Session = Depends(get_db)):
    admin = verify_admin(telegram_id, db)
    total_users = db.query(User).count()
    total_transactions = db.query(Transaction).count()
    pending_transactions = db.query(Transaction).filter(Transaction.status == "pendiente").count()
    approved_transactions = db.query(Transaction).filter(Transaction.status == "aprobado").count()
    
    recent_transactions = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(10).all()
    transactions_list = []
    for t in recent_transactions:
        user = db.query(User).filter(User.id == t.user_id).first()
        transactions_list.append({
            "id": t.id,
            "username": user.username if user else "Desconocido",
            "type": t.type,
            "amount": t.amount,
            "status": t.status,
            "created_at": t.created_at.isoformat()
        })
    return {
        "admin_username": admin.username,
        "stats": {"total_users": total_users, "total_transactions": total_transactions, "pending": pending_transactions, "approved": approved_transactions},
        "recent_transactions": transactions_list,
        "admin_telegram_id": ADMIN_ID
    }

@app.get("/admin/check")
def check_admin_status(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    is_admin = user and user.is_admin
    return {"is_admin": is_admin, "message": "Acceso concedido" if is_admin else "Acceso denegado", "admin_panel_url": "/admin/dashboard" if is_admin else None}

# --- Botón de Grupo ---
@app.get("/grupo/info")
def get_grupo_info():
    return {"grupo_id": GRUPO_TELEGRAM_ID, "mensaje": "Únete al grupo oficial para novedades y soporte", "boton_texto": "Unirse al Grupo"}

# --- FUNCIÓN EN HILO SECUNDARIO PARA EL BOT ---
def run_bot():
    if bot:
        print("Bot de Telegram escuchando en segundo plano...")
        bot.infinity_polling()

if __name__ == "__main__":
    import uvicorn
    # Lanzamos el bot en un hilo paralelo para que no interfiera con FastAPI
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
