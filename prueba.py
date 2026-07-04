import logging
import threading
import time
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import uvicorn

# ============ CONFIGURACIÓN ============
BOT_TOKEN = "8206009148:AAGPVgO2VLfKYcUNy-BlBGWfv40gwrFivHQ"
ADMIN_ID = 6808824866
DATABASE_URL = "postgresql://postgres.rsqcsdheaibeuhjbxicn:c4OVrj3MTehgvu57@aws-1-us-west-2.pooler.supabase.com:6543/postgres"

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ BASE DE DATOS ============
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    telegram_username = Column(String, nullable=True)
    telegram_name = Column(String, nullable=True)
    balance_usdt = Column(Float, default=0.0)
    balance_stars = Column(Float, default=0.0)
    ships = Column(JSON, default=list)
    aliens = Column(JSON, default=list)
    planets = Column(JSON, default=list)
    active_contract = Column(JSON, nullable=True)
    fuel_available = Column(Float, default=0.0)
    has_done_expedition = Column(Boolean, default=False)
    last_expedition_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WalletRequest(Base):
    __tablename__ = "wallet_requests"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, index=True)
    type = Column(String)
    amount = Column(Float)
    network = Column(String)
    currency = Column(String)
    txid = Column(String, nullable=True)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class P2PListing(Base):
    __tablename__ = "p2p_listings"
    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(String, unique=True, index=True)
    type = Column(String)
    item_id = Column(String)
    name = Column(String)
    rarity = Column(String)
    image = Column(String)
    seller_id = Column(BigInteger, index=True)
    seller_name = Column(String)
    price = Column(Float)
    quantity = Column(Integer, default=1)
    data = Column(JSON, default=dict)
    status = Column(String, default='active')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============ SCHEMAS ============
class UserCreate(BaseModel):
    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_name: Optional[str] = None

class UserUpdate(BaseModel):
    balance_usdt: Optional[float] = None
    balance_stars: Optional[float] = None
    ships: Optional[List[Dict]] = None
    aliens: Optional[List[Dict]] = None
    planets: Optional[List[Dict]] = None
    active_contract: Optional[Dict] = None
    fuel_available: Optional[float] = None
    has_done_expedition: Optional[bool] = None
    last_expedition_time: Optional[datetime] = None

class UserResponse(BaseModel):
    id: int
    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_name: Optional[str] = None
    balance_usdt: float
    balance_stars: float
    ships: List[Dict]
    aliens: List[Dict]
    planets: List[Dict]
    active_contract: Optional[Dict] = None
    fuel_available: float
    has_done_expedition: bool
    last_expedition_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class WalletRequestCreate(BaseModel):
    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_name: Optional[str] = None
    type: str
    amount: float
    network: str
    currency: str
    txid: Optional[str] = None

class WalletRequestUpdate(BaseModel):
    status: str

class WalletRequestResponse(BaseModel):
    id: int
    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_name: Optional[str] = None
    type: str
    amount: float
    network: str
    currency: str
    txid: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class P2PListingCreate(BaseModel):
    listing_id: str
    type: str
    item_id: str
    name: str
    rarity: str
    image: str
    seller_id: int
    seller_name: str
    price: float
    quantity: int = 1
    data: Dict = {}

class P2PListingUpdate(BaseModel):
    status: str

class P2PListingResponse(BaseModel):
    id: int
    listing_id: str
    type: str
    item_id: str
    name: str
    rarity: str
    image: str
    seller_id: int
    seller_name: str
    price: float
    quantity: int
    data: Dict
    status: str
    created_at: datetime
    class Config:
        from_attributes = True

class SyncData(BaseModel):
    telegram_id: int
    ships: List[Dict]
    aliens: List[Dict]
    planets: List[Dict]
    p2pListings: List[Dict]
    balance_usdt: float
    balance_stars: float
    fuel_available: float = 0
    has_done_expedition: bool = False
    last_expedition_time: Optional[datetime] = None
    active_contract: Optional[Dict] = None

# ============ FASTAPI APP ============
app = FastAPI(title="XENOPORT API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ ENDPOINTS ============
@app.post("/api/users", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.telegram_id == user.telegram_id).first()
    if existing:
        return existing
    db_user = User(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/api/users/{telegram_id}", response_model=UserResponse)
def get_user(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    return user

@app.get("/api/users", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@app.put("/api/users/{telegram_id}", response_model=UserResponse)
def update_user(telegram_id: int, user_update: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    for key, value in user_update.dict(exclude_unset=True).items():
        setattr(user, key, value)
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user

@app.post("/api/sync")
def sync_data(data: SyncData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == data.telegram_id).first()
    if not user:
        user = User(telegram_id=data.telegram_id)
        db.add(user)
    user.ships = data.ships
    user.aliens = data.aliens
    user.planets = data.planets
    user.balance_usdt = data.balance_usdt
    user.balance_stars = data.balance_stars
    user.fuel_available = data.fuel_available
    user.has_done_expedition = data.has_done_expedition
    user.last_expedition_time = data.last_expedition_time
    user.active_contract = data.active_contract
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    for listing in data.p2pListings:
        existing = db.query(P2PListing).filter(P2PListing.listing_id == listing['id']).first()
        if existing:
            existing.status = listing.get('status', 'active')
            existing.updated_at = datetime.utcnow()
        else:
            db.add(P2PListing(
                listing_id=listing['id'],
                type=listing['type'],
                item_id=listing['itemId'],
                name=listing['name'],
                rarity=listing['rarity'],
                image=listing['image'],
                seller_id=listing['sellerId'],
                seller_name=listing['seller'],
                price=listing['price'],
                quantity=listing.get('quantity', 1),
                data=listing
            ))
    db.commit()
    return {"status": "synced"}

@app.post("/api/wallet-requests", response_model=WalletRequestResponse)
def create_wallet_request(request: WalletRequestCreate, db: Session = Depends(get_db)):
    db_request = WalletRequest(**request.dict(), status='pending')
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    # Notificar admin
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        text = f"📋 Nueva solicitud #{db_request.id}\nUsuario: {request.telegram_id}\nTipo: {request.type}\nMonto: {request.amount} {request.currency}"
        requests.post(url, json={"chat_id": ADMIN_ID, "text": text, "parse_mode": "Markdown"})
    except:
        pass
    return db_request

@app.get("/api/wallet-requests", response_model=List[WalletRequestResponse])
def get_wallet_requests(db: Session = Depends(get_db)):
    return db.query(WalletRequest).order_by(WalletRequest.created_at.desc()).all()

@app.get("/api/wallet-requests/pending", response_model=List[WalletRequestResponse])
def get_pending_requests(db: Session = Depends(get_db)):
    return db.query(WalletRequest).filter(WalletRequest.status == 'pending').order_by(WalletRequest.created_at.desc()).all()

@app.get("/api/wallet-requests/{request_id}", response_model=WalletRequestResponse)
def get_wallet_request(request_id: int, db: Session = Depends(get_db)):
    req = db.query(WalletRequest).filter(WalletRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Solicitud no encontrada")
    return req

@app.put("/api/wallet-requests/{request_id}", response_model=WalletRequestResponse)
def update_wallet_request(request_id: int, update: WalletRequestUpdate, db: Session = Depends(get_db)):
    req = db.query(WalletRequest).filter(WalletRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Solicitud no encontrada")
    req.status = update.status
    req.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    if update.status == 'approved':
        user = db.query(User).filter(User.telegram_id == req.telegram_id).first()
        if user:
            if req.currency == 'USDT':
                user.balance_usdt += req.amount
            elif req.currency == 'Stars':
                user.balance_stars += req.amount
            db.commit()
    return req

@app.get("/api/p2p/listings/active", response_model=List[P2PListingResponse])
def get_active_p2p_listings(db: Session = Depends(get_db)):
    return db.query(P2PListing).filter(P2PListing.status == 'active').order_by(P2PListing.created_at.desc()).all()

@app.post("/api/p2p/listings", response_model=P2PListingResponse)
def create_p2p_listing(listing: P2PListingCreate, db: Session = Depends(get_db)):
    db_listing = P2PListing(**listing.dict(), status='active')
    db.add(db_listing)
    db.commit()
    db.refresh(db_listing)
    return db_listing

@app.put("/api/p2p/listings/{listing_id}")
def update_p2p_listing(listing_id: str, update: P2PListingUpdate, db: Session = Depends(get_db)):
    listing = db.query(P2PListing).filter(P2PListing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Listing no encontrado")
    listing.status = update.status
    listing.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "updated"}

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    users = db.query(User).all()
    pending = db.query(WalletRequest).filter(WalletRequest.status == 'pending').count()
    active = db.query(P2PListing).filter(P2PListing.status == 'active').count()
    total_ships = sum(len(u.ships or []) for u in users)
    total_aliens = sum(len(u.aliens or []) for u in users)
    total_usdt = sum(u.balance_usdt or 0 for u in users)
    total_stars = sum(u.balance_stars or 0 for u in users)
    return {
        "total_users": len(users),
        "total_ships": total_ships,
        "total_aliens": total_aliens,
        "total_usdt": total_usdt,
        "total_stars": total_stars,
        "active_listings": active,
        "pending_requests": pending
    }

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ============ BOT DE TELEGRAM ============
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Usuario"
    name = message.from_user.first_name or ""
    # Registrar usuario
    try:
        requests.post(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/users", json={
            "telegram_id": user_id,
            "telegram_username": username,
            "telegram_name": name
        })
    except:
        pass
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(KeyboardButton("🎮 PLAY"), KeyboardButton("📋 Perfil"), KeyboardButton("💰 Saldo"))
    if user_id == ADMIN_ID:
        keyboard.add(KeyboardButton("🔐 Panel Admin"))
    bot.send_message(message.chat.id, f"🚀 ¡Bienvenido a XENOPORT, Capitán {name}!", reply_markup=keyboard, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "🎮 PLAY")
def play(m):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🚀 ABRIR XENOPORT", url=os.getenv('RENDER_EXTERNAL_URL', 'https://comando-evkk.onrender.com')))
    bot.send_message(m.chat.id, "🛸 Haz clic para comenzar:", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "📋 Perfil")
def perfil(m):
    user_id = m.from_user.id
    try:
        r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/users/{user_id}")
        if r.status_code == 200:
            u = r.json()
            txt = f"📋 *Perfil*\nID: {u['telegram_id']}\nNombre: {u.get('telegram_name','')}\nUsuario: @{u.get('telegram_username','')}\n💠 USDT: {u['balance_usdt']:.2f}\n⭐ Stars: {u['balance_stars']:.0f}\n⛽ Combustible: {u['fuel_available']:.0f}\n🚀 Naves: {len(u.get('ships',[]))}\n👾 Aliens: {len(u.get('aliens',[]))}"
            bot.send_message(m.chat.id, txt, parse_mode='Markdown')
        else:
            bot.send_message(m.chat.id, "❌ No se pudo obtener el perfil")
    except:
        bot.send_message(m.chat.id, "❌ Error de conexión")

@bot.message_handler(func=lambda m: m.text == "💰 Saldo")
def saldo(m):
    user_id = m.from_user.id
    try:
        r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/users/{user_id}")
        if r.status_code == 200:
            u = r.json()
            txt = f"💰 *Saldo*\n💠 USDT: {u['balance_usdt']:.2f}\n⭐ Stars: {u['balance_stars']:.0f}\n⛽ Combustible: {u['fuel_available']:.0f}"
            bot.send_message(m.chat.id, txt, parse_mode='Markdown')
        else:
            bot.send_message(m.chat.id, "❌ No se pudo obtener el saldo")
    except:
        bot.send_message(m.chat.id, "❌ Error de conexión")

@bot.message_handler(func=lambda m: m.text == "🔐 Panel Admin")
def admin_panel(m):
    if m.from_user.id != ADMIN_ID:
        bot.send_message(m.chat.id, "❌ No tienes permisos")
        return
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📋 Solicitudes Pendientes", callback_data="admin_pending"),
        InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Usuarios", callback_data="admin_users"),
        InlineKeyboardButton("📦 P2P", callback_data="admin_p2p")
    )
    bot.send_message(m.chat.id, "🔐 *Panel de Administración*", parse_mode='Markdown', reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "No autorizado")
        return
    if call.data == "admin_pending":
        try:
            r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/wallet-requests/pending")
            if r.status_code == 200:
                data = r.json()
                if not data:
                    bot.send_message(call.message.chat.id, "✅ No hay solicitudes pendientes")
                else:
                    for req in data:
                        kb = InlineKeyboardMarkup(row_width=2)
                        kb.add(
                            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{req['id']}"),
                            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{req['id']}")
                        )
                        txt = f"📋 Solicitud #{req['id']}\n👤 Usuario: {req['telegram_id']}\n📊 Tipo: {req['type']}\n💰 Monto: {req['amount']} {req['currency']}\n🔗 Red: {req['network']}\n📝 TXID: {req.get('txid','N/A')}"
                        bot.send_message(call.message.chat.id, txt, parse_mode='Markdown', reply_markup=kb)
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener solicitudes")
        except:
            bot.send_message(call.message.chat.id, "❌ Error de conexión")
    elif call.data == "admin_stats":
        try:
            r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/stats")
            if r.status_code == 200:
                s = r.json()
                txt = f"📊 *Estadísticas*\n👥 Usuarios: {s['total_users']}\n🚀 Naves: {s['total_ships']}\n👾 Aliens: {s['total_aliens']}\n💠 USDT: {s['total_usdt']:.2f}\n⭐ Stars: {s['total_stars']:.0f}\n📦 P2P activos: {s['active_listings']}\n📋 Pendientes: {s['pending_requests']}"
                bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error")
        except:
            bot.send_message(call.message.chat.id, "❌ Error de conexión")
    elif call.data == "admin_users":
        try:
            r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/users")
            if r.status_code == 200:
                users = r.json()
                if not users:
                    bot.send_message(call.message.chat.id, "👥 No hay usuarios")
                else:
                    txt = "👥 *Usuarios*\n"
                    for u in users[:15]:
                        txt += f"• {u.get('telegram_name','')} (@{u.get('telegram_username','')}) - 💠{u['balance_usdt']:.2f} ⭐{u['balance_stars']:.0f}\n"
                    if len(users) > 15:
                        txt += f"\n... y {len(users)-15} más"
                    bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error")
        except:
            bot.send_message(call.message.chat.id, "❌ Error de conexión")
    elif call.data == "admin_p2p":
        try:
            r = requests.get(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/p2p/listings/active")
            if r.status_code == 200:
                listings = r.json()
                if not listings:
                    bot.send_message(call.message.chat.id, "📦 No hay listados P2P")
                else:
                    txt = "📦 *Listados P2P activos*\n"
                    for l in listings[:10]:
                        txt += f"• {l['name']} ({l['rarity']}) - 💠{l['price']:.2f} - Vendedor: @{l['seller_name']}\n"
                    if len(listings) > 10:
                        txt += f"\n... y {len(listings)-10} más"
                    bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error")
        except:
            bot.send_message(call.message.chat.id, "❌ Error de conexión")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_approve_reject(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "No autorizado")
        return
    parts = call.data.split('_')
    action = parts[0]
    req_id = int(parts[1])
    try:
        r = requests.put(f"{os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:8000')}/api/wallet-requests/{req_id}", json={"status": action})
        if r.status_code == 200:
            # Notificar al usuario
            req = r.json()
            user_id = req['telegram_id']
            try:
                bot.send_message(user_id, f"✅ *Solicitud #{req_id} {action}ada*", parse_mode='Markdown')
            except:
                pass
            bot.edit_message_text(f"Solicitud #{req_id} {action}ada", call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Error al procesar")
    except:
        bot.answer_callback_query(call.id, "Error de conexión")

@bot.message_handler(func=lambda m: True)
def default(m):
    bot.send_message(m.chat.id, "Usa los botones del menú o /start")

# ============ INICIAR BOT EN HILO ============
def run_bot():
    logger.info("🤖 Bot iniciado...")
    try:
        bot.polling(non_stop=True, interval=1)
    except Exception as e:
        logger.error(f"Bot error: {e}")
        time.sleep(5)
        run_bot()

# ============ ARRANQUE PRINCIPAL ============
if __name__ == "__main__":
    # Iniciar el bot en un hilo
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("🚀 Servidor FastAPI iniciando...")
    # Obtener puerto de Render o usar 8000 por defecto
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
