import random
import os
import threading
import time
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# --- Configuración de Base de Datos ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres.rsqcsdheaibeuhjbxicn:s1vwz36ddTBKPaUv@aws-1-us-west-2.pooler.supabase.com:6543/postgres")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_recycle=1800,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Configuración de Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8206009148:AAEEWSYAgxj3MRR8xGOe-s7V5COl5htsYnY")
ADMIN_ID = 6808824866  # <-- Tu Telegram ID
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
    usdt_balance = Column(Float, default=0.0)
    telegram_id = Column(BigInteger, nullable=True)
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
    type = Column(String)  # recarga, retiro
    amount = Column(Float)
    status = Column(String, default="pendiente")  # pendiente, aprobado, rechazado
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    processed_by = Column(BigInteger, nullable=True)
    payment_method = Column(String, nullable=True)
    proof_hash = Column(Text, nullable=True)
    wallet_address = Column(Text, nullable=True)  # Para retiros

try:
    Base.metadata.create_all(bind=engine)
except Exception as db_err:
    print(f"Error en tablas de Supabase: {db_err}")

# --- Definiciones del Juego ---
PLANT_DEFINITIONS = {
    "Comun": {"min_time": 1, "max_time": 4, "price": 5, "lan_reward_min": 10, "lan_reward_max": 20},
    "PocoComun": {"min_time": 5, "max_time": 12, "price": 15, "lan_reward_min": 30, "lan_reward_max": 50},
    "Epica": {"min_time": 13, "max_time": 24, "price": 40, "lan_reward_min": 80, "lan_reward_max": 150},
    "Legendaria": {"min_time": 25, "max_time": 72, "price": 100, "lan_reward_min": 200, "lan_reward_max": 500}
}
LAND_PRICES = {"Comun": 10, "Rara": 30, "Legendaria": 80}

# --- Pydantic Models ---
class TransactionRequest(BaseModel):
    type: str
    amount: float
    payment_method: Optional[str] = "USDT TRC20"
    proof_hash: Optional[str] = ""
    wallet_address: Optional[str] = ""  # Para retiros

class BuyLandRequest(BaseModel):
    land_type: str

class PlantSeedRequest(BaseModel):
    land_id: int
    rarity: str

class LinkTelegramRequest(BaseModel):
    telegram_id: int

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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
    return random.choice(names.get(rarity, ["Planta"]))

# --- FastAPI App ---
app = FastAPI(title="GranjaP2P API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helpers ---
def send_telegram_notification(chat_id: int, message: str, reply_markup=None):
    if bot and chat_id:
        try:
            bot.send_message(chat_id, message, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception as e:
            print(f"Error notif a {chat_id}: {e}")

def notify_admin(message: str, reply_markup=None):
    send_telegram_notification(ADMIN_ID, message, reply_markup)

# --- Telegram Bot Logic ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        chat_id = message.chat.id
        tg_username = message.from_user.username or f"user_{chat_id}"
        first_name = message.from_user.first_name

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.telegram_id == chat_id).first()
            if not user:
                user = User(username=tg_username, telegram_id=chat_id, lan_balance=0.0, usdt_balance=0.0)
                db.add(user)
                db.commit()
            else:
                if user.telegram_id != chat_id:
                    user.telegram_id = chat_id
                    db.commit()

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(text="🌾 Jugar FlowerLand", web_app=WebAppInfo(url=MINI_APP_URL)))

            welcome_text = f"¡Hola *{first_name}*! 👋\nBienvenido a *FlowerLand*.\nPresiona el botón para jugar."
            bot.send_message(chat_id, welcome_text, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"Error start: {e}")
        finally:
            db.close()

    # --- HANDLERS DE BOTONES INLINE (APROBAR / RECHAZAR) ---
    @bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
    def handle_transaction_decision(call):
        chat_id = call.message.chat.id
        
        # Verificar que sea el admin
        if chat_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ No autorizado", show_alert=True)
            return

        action, tx_id_str = call.data.split("_", 1)
        tx_id = int(tx_id_str)
        
        db = SessionLocal()
        try:
            transaction = db.query(Transaction).filter(Transaction.id == tx_id).first()
            if not transaction or transaction.status != "pendiente":
                bot.answer_callback_query(call.id, "⚠️ Transacción ya procesada o no existe", show_alert=True)
                return

            user = db.query(User).filter(User.id == transaction.user_id).first()
            if not user:
                bot.answer_callback_query(call.id, "⚠️ Usuario no encontrado", show_alert=True)
                return

            if action == "approve":
                transaction.status = "aprobado"
                transaction.processed_at = datetime.utcnow()
                transaction.processed_by = chat_id

                if transaction.type == "recarga":
                    user.usdt_balance += transaction.amount
                    msg_user = f"✅ *Recarga Aprobada*\nSe han acreditado *{transaction.amount} USDT* a tu saldo."
                elif transaction.type == "retiro":
                    if user.usdt_balance < transaction.amount:
                        bot.answer_callback_query(call.id, "⚠️ Saldo insuficiente del usuario", show_alert=True)
                        return
                    user.usdt_balance -= transaction.amount
                    msg_user = f"✅ *Retiro Aprobado*\nSe han retirado *{transaction.amount} USDT*. Recibirás tus fondos pronto."

                # Editar el mensaje del admin para que vea que fue aprobado
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ *APROBADA* #{transaction.id}\nUsuario: `{user.username}`\nTipo: {transaction.type.upper()}\nMonto: {transaction.amount}\nMétodo: {transaction.payment_method}",
                    parse_mode="Markdown"
                )
                bot.answer_callback_query(call.id, "✅ Transacción APROBADA", show_alert=True)

            elif action == "reject":
                transaction.status = "rechazado"
                transaction.processed_at = datetime.utcnow()
                transaction.processed_by = chat_id
                msg_user = f"❌ Tu solicitud #{transaction.id} de {transaction.type} por {transaction.amount} ha sido RECHAZADA."

                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"❌ *RECHAZADA* #{transaction.id}\nUsuario: `{user.username}`\nTipo: {transaction.type.upper()}\nMonto: {transaction.amount}",
                    parse_mode="Markdown"
                )
                bot.answer_callback_query(call.id, "❌ Transacción RECHAZADA", show_alert=True)

            db.commit()

            # Notificar al usuario
            if user.telegram_id:
                send_telegram_notification(user.telegram_id, msg_user)

        except Exception as e:
            print(f"Error en callback: {e}")
            bot.answer_callback_query(call.id, f"Error: {str(e)}", show_alert=True)
        finally:
            db.close()

    def run_bot():
        if not bot: return
        print("🤖 [Telegram] Iniciando polling...")
        bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=True)

# --- Endpoints API ---

@app.get("/user-data/{telegram_id}")
def get_user_data(telegram_id: int, db: Session = Depends(get_db)):
    """Devuelve TODOS los datos reales del usuario desde la BD"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        # Auto-registro
        user = User(username=f"user_{telegram_id}", telegram_id=telegram_id, lan_balance=0.0, usdt_balance=0.0)
        db.add(user)
        db.commit()
        db.refresh(user)

    # Tierras reales
    lands = db.query(Land).filter(Land.user_id == user.id).all()
    lands_data = []
    for l in lands:
        # Contar plantas activas en esta tierra
        plants_count = db.query(Plant).filter(Plant.land_id == l.id, Plant.is_harvested == False).count()
        lands_data.append({
            "id": l.id,
            "type": l.type,
            "slots_total": l.slots_total,
            "is_free_land": l.is_free_land,
            "plants_count": plants_count
        })

    # Historial de transacciones reales
    transactions = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.created_at.desc()).limit(20).all()
    tx_data = [{
        "id": t.id,
        "type": t.type,
        "amount": t.amount,
        "status": t.status,
        "method": t.payment_method,
        "created_at": t.created_at.isoformat() if t.created_at else None
    } for t in transactions]

    return {
        "username": user.username,
        "telegram_id": user.telegram_id,
        "lan_balance": user.lan_balance,
        "usdt_balance": user.usdt_balance,
        "lands": lands_data,
        "transactions": tx_data
    }

@app.post("/transaction/request/{telegram_id}")
def request_transaction(telegram_id: int, request: TransactionRequest, db: Session = Depends(get_db)):
    """Crea la transacción y envía mensaje al admin con botones Aceptar/Rechazar"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado. Abre el bot primero con /start")

    if request.type not in ["recarga", "retiro"] or request.amount <= 0:
        raise HTTPException(status_code=400, detail="Monto o tipo inválido")

    # Validar saldo para retiros
    if request.type == "retiro" and user.usdt_balance < request.amount:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Tienes {user.usdt_balance} USDT")

    transaction = Transaction(
        user_id=user.id,
        type=request.type,
        amount=request.amount,
        status="pendiente",
        payment_method=request.payment_method,
        proof_hash=request.proof_hash,
        wallet_address=request.wallet_address
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # --- MENSAJE AL ADMIN CON BOTONES INLINE ---
    msg = (
        f"💰 *Nueva Solicitud #{transaction.id}*\n"
        f"👤 Usuario: `{user.username}`\n"
        f"🔢 Telegram ID: `{user.telegram_id}`\n"
        f"📋 Tipo: *{request.type.upper()}*\n"
        f"💵 Monto: *{request.amount} USDT*\n"
        f"💳 Método: {request.payment_method}\n"
    )
    if request.proof_hash:
        msg += f"🧾 Hash/Comprobante:\n`{request.proof_hash}`\n"
    if request.wallet_address:
        msg += f"📍 Wallet destino:\n`{request.wallet_address}`\n"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{transaction.id}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{transaction.id}")
    )

    notify_admin(msg, reply_markup=markup)

    return {
        "message": "Solicitud enviada al administrador. Recibirás notificación en Telegram.",
        "transaction_id": transaction.id
    }

@app.post("/buy-land/{telegram_id}")
def buy_land(telegram_id: int, request: BuyLandRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    price = LAND_PRICES.get(request.land_type)
    if not price:
        raise HTTPException(status_code=400, detail="Tipo de tierra inválido")
    if user.usdt_balance < price:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Necesitas {price} USDT")

    slots_map = {"Comun": 4, "Rara": 8, "Legendaria": 12}
    user.usdt_balance -= price

    new_land = Land(user_id=user.id, type=request.land_type, slots_total=slots_map[request.land_type])
    db.add(new_land)
    db.commit()

    return {"message": "Tierra comprada", "new_balance": user.usdt_balance}

@app.post("/plant-seed/{telegram_id}")
def plant_seed(telegram_id: int, request: PlantSeedRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    land = db.query(Land).filter(Land.id == request.land_id, Land.user_id == user.id).first()
    rarity_config = PLANT_DEFINITIONS.get(request.rarity)
    if not land or not rarity_config:
        raise HTTPException(status_code=400, detail="Datos inválidos")
    if user.lan_balance < rarity_config["price"]:
        raise HTTPException(status_code=400, detail="Saldo LAN insuficiente")

    random_time = random.uniform(rarity_config["min_time"], rarity_config["max_time"])
    new_plant = Plant(
        land_id=request.land_id,
        name=get_random_plant_name(request.rarity),
        rarity=request.rarity,
        total_time_hours=random_time
    )
    user.lan_balance -= rarity_config["price"]
    db.add(new_plant)
    db.commit()

    return {"message": "Planta sembrada", "plant_id": new_plant.id}

@app.get("/plants/{telegram_id}")
def get_plants(telegram_id: int, db: Session = Depends(get_db)):
    """Devuelve plantas reales del usuario"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return []

    user_lands = db.query(Land).filter(Land.user_id == user.id).all()
    land_ids = [l.id for l in user_lands]
    if not land_ids:
        return []

    plants = db.query(Plant).filter(Plant.land_id.in_(land_ids), Plant.is_harvested == False).all()
    result = []
    for p in plants:
        progress, remaining, is_ready = calculate_progress(p)
        land = db.query(Land).filter(Land.id == p.land_id).first()
        result.append({
            "id": p.id,
            "land_id": p.land_id,
            "name": p.name,
            "rarity": p.rarity,
            "total_time_hours": p.total_time_hours,
            "progress_percent": progress,
            "time_remaining_hours": remaining,
            "is_ready": is_ready,
            "land_type": land.type if land else "Desconocida"
        })
    return result

@app.post("/harvest/{plant_id}/{telegram_id}")
def harvest_plant(plant_id: int, telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Planta no encontrada")

    land = db.query(Land).filter(Land.id == plant.land_id, Land.user_id == user.id).first()
    if not land:
        raise HTTPException(status_code=403, detail="No eres dueño de esta planta")

    progress, remaining, is_ready = calculate_progress(plant)
    if not is_ready:
        raise HTTPException(status_code=400, detail="Cultivo no listo")

    reward = random.uniform(PLANT_DEFINITIONS[plant.rarity]["lan_reward_min"], PLANT_DEFINITIONS[plant.rarity]["lan_reward_max"])
    user.lan_balance += reward
    plant.is_harvested = True
    db.commit()

    return {"message": "Cosechado", "reward": round(reward, 2), "new_lan_balance": user.lan_balance}

# --- Inicialización ---
if __name__ == "__main__":
    import uvicorn
    if bot:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("🚀 [Sistema] Hilo del Bot iniciado.")
    uvicorn.run(app, host="0.0.0.0", port=8000)
