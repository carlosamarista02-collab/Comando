import logging
import threading
import time
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON, BigInteger, Text
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

# ---------- TABLA USUARIOS ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    telegram_username = Column(String, nullable=True)
    telegram_name = Column(String, nullable=True)
    balance_usdt = Column(Float, default=0.0)
    balance_stars = Column(Float, default=0.0)
    ships = Column(JSON, default=list)          # Lista de naves
    aliens = Column(JSON, default=list)        # Lista de aliens
    planets = Column(JSON, default=list)       # Lista de planetas (progreso)
    active_contract = Column(JSON, nullable=True)
    fuel_available = Column(Float, default=0.0)
    has_done_expedition = Column(Boolean, default=False)
    last_expedition_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ---------- TABLA SOLICITUDES DE BILLETERA ----------
class WalletRequest(Base):
    __tablename__ = "wallet_requests"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, index=True)
    type = Column(String)                       # 'recarga' o 'retiro'
    amount = Column(Float)
    network = Column(String)
    currency = Column(String)
    txid = Column(String, nullable=True)
    status = Column(String, default='pending')  # 'pending', 'approved', 'rejected'
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ---------- TABLA LISTADOS P2P ----------
class P2PListing(Base):
    __tablename__ = "p2p_listings"
    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(String, unique=True, index=True)
    type = Column(String)                       # 'ship' o 'alien'
    item_id = Column(String)
    name = Column(String)
    rarity = Column(String)
    image = Column(String)
    seller_id = Column(BigInteger, index=True)
    seller_name = Column(String)
    price = Column(Float)
    quantity = Column(Integer, default=1)
    data = Column(JSON, default=dict)           # Datos extra (aliens, maxAliens, fuel, etc.)
    status = Column(String, default='active')   # 'active', 'sold', 'cancelled'
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Crear tablas si no existen
Base.metadata.create_all(bind=engine)

# ============ DEPENDENCIA DB ============
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============ SCHEMAS (Pydantic) ============
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

# ============ ENDPOINTS API ============

# --- Usuarios ---
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

# --- Sincronización ---
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
    # Sincronizar P2P listings
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

# --- Wallet Requests ---
@app.post("/api/wallet-requests", response_model=WalletRequestResponse)
def create_wallet_request(request: WalletRequestCreate, db: Session = Depends(get_db)):
    db_request = WalletRequest(**request.dict(), status='pending')
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    # Notificar al admin
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        text = f"📋 Nueva solicitud #{db_request.id}\n👤 Usuario: {request.telegram_id}\n📊 Tipo: {request.type}\n💰 Monto: {request.amount} {request.currency}"
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

# --- P2P Listings ---
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

# --- Estadísticas ---
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

# --- NUEVO: Ver todas las tablas (dump) ---
@app.get("/api/admin/tables")
def get_all_tables(db: Session = Depends(get_db)):
    users = db.query(User).all()
    requests = db.query(WalletRequest).all()
    listings = db.query(P2PListing).all()

    # Formatear para mostrar
    users_data = []
    for u in users:
        users_data.append({
            "id": u.id,
            "telegram_id": u.telegram_id,
            "nombre": u.telegram_name or "Sin nombre",
            "username": u.telegram_username or "Sin usuario",
            "usdt": u.balance_usdt,
            "stars": u.balance_stars,
            "naves": len(u.ships or []),
            "aliens": len(u.aliens or []),
            "combustible": u.fuel_available,
            "contrato": u.active_contract,
            "fecha_registro": u.created_at.isoformat() if u.created_at else None
        })

    requests_data = [
        {
            "id": r.id,
            "usuario": r.telegram_id,
            "tipo": r.type,
            "monto": r.amount,
            "moneda": r.currency,
            "red": r.network,
            "txid": r.txid,
            "estado": r.status,
            "fecha": r.created_at.isoformat() if r.created_at else None
        } for r in requests
    ]

    listings_data = [
        {
            "id": l.listing_id,
            "tipo": l.type,
            "nombre": l.name,
            "rareza": l.rarity,
            "precio": l.price,
            "vendedor": l.seller_name,
            "vendedor_id": l.seller_id,
            "estado": l.status,
            "fecha": l.created_at.isoformat() if l.created_at else None
        } for l in listings
    ]

    return {
        "usuarios": users_data,
        "solicitudes": requests_data,
        "listados_p2p": listings_data
    }

# --- NUEVO: Resetear base de datos (borrar y recrear tablas) ---
@app.post("/api/admin/reset")
def reset_database(db: Session = Depends(get_db)):
    try:
        # Borrar todos los datos de las tablas
        db.query(User).delete()
        db.query(WalletRequest).delete()
        db.query(P2PListing).delete()
        db.commit()
        # Opcional: recrear tablas (si se quiere eliminar la estructura y volver a crearla)
        # Base.metadata.drop_all(bind=engine)
        # Base.metadata.create_all(bind=engine)
        return {"status": "reset_completed", "message": "Todos los datos han sido eliminados. Las tablas están vacías."}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error al resetear: {str(e)}")

# --- Health check ---
@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ============ BOT DE TELEGRAM ============
bot = telebot.TeleBot(BOT_TOKEN)

# Variables globales para la URL base
BASE_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://comando-evkk.onrender.com')

# ---------- COMANDOS ----------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Usuario"
    name = message.from_user.first_name or ""
    # Registrar usuario
    try:
        requests.post(f"{BASE_URL}/api/users", json={
            "telegram_id": user_id,
            "telegram_username": username,
            "telegram_name": name
        })
    except:
        pass
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🎮 PLAY"),
        KeyboardButton("📋 Perfil"),
        KeyboardButton("💰 Saldo")
    )
    if user_id == ADMIN_ID:
        keyboard.add(KeyboardButton("🔐 Panel Admin"))
    bot.send_message(
        message.chat.id,
        f"🚀 ¡Bienvenido a XENOPORT, Capitán {name}!",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.text == "🎮 PLAY")
def play(m):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🚀 ABRIR XENOPORT", url=BASE_URL))
    bot.send_message(m.chat.id, "🛸 Haz clic para comenzar:", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "📋 Perfil")
def perfil(m):
    user_id = m.from_user.id
    try:
        r = requests.get(f"{BASE_URL}/api/users/{user_id}")
        if r.status_code == 200:
            u = r.json()
            txt = (
                f"📋 *Perfil*\n"
                f"🆔 ID: {u['telegram_id']}\n"
                f"👤 Nombre: {u.get('telegram_name', 'Sin nombre')}\n"
                f"🐦 Usuario: @{u.get('telegram_username', 'sin usuario')}\n"
                f"💠 USDT: {u['balance_usdt']:.2f}\n"
                f"⭐ Stars: {u['balance_stars']:.0f}\n"
                f"⛽ Combustible: {u['fuel_available']:.0f}\n"
                f"🚀 Naves: {len(u.get('ships', []))}\n"
                f"👾 Aliens: {len(u.get('aliens', []))}\n"
                f"📅 Registro: {u.get('created_at', '')[:10] if u.get('created_at') else 'N/A'}"
            )
            bot.send_message(m.chat.id, txt, parse_mode='Markdown')
        else:
            bot.send_message(m.chat.id, "❌ No se pudo obtener el perfil")
    except:
        bot.send_message(m.chat.id, "❌ Error de conexión")

@bot.message_handler(func=lambda m: m.text == "💰 Saldo")
def saldo(m):
    user_id = m.from_user.id
    try:
        r = requests.get(f"{BASE_URL}/api/users/{user_id}")
        if r.status_code == 200:
            u = r.json()
            txt = f"💰 *Saldo*\n💠 USDT: {u['balance_usdt']:.2f}\n⭐ Stars: {u['balance_stars']:.0f}\n⛽ Combustible: {u['fuel_available']:.0f}"
            bot.send_message(m.chat.id, txt, parse_mode='Markdown')
        else:
            bot.send_message(m.chat.id, "❌ No se pudo obtener el saldo")
    except:
        bot.send_message(m.chat.id, "❌ Error de conexión")

# ---------- PANEL DE ADMINISTRACIÓN ----------
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
        InlineKeyboardButton("📦 Listados P2P", callback_data="admin_p2p")
    )
    keyboard.add(
        InlineKeyboardButton("📊 Ver Tablas", callback_data="admin_tables"),
        InlineKeyboardButton("🗑️ Resetear Base de Datos", callback_data="admin_reset")
    )
    bot.send_message(m.chat.id, "🔐 *Panel de Administración*", parse_mode='Markdown', reply_markup=keyboard)

# ---------- CALLBACKS DEL ADMIN ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "No autorizado")
        return

    # ----- Solicitudes Pendientes -----
    if call.data == "admin_pending":
        try:
            r = requests.get(f"{BASE_URL}/api/wallet-requests/pending")
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
                        txt = (
                            f"📋 *Solicitud #{req['id']}*\n"
                            f"👤 Usuario: {req['telegram_id']}\n"
                            f"📊 Tipo: {req['type'].upper()}\n"
                            f"💰 Monto: {req['amount']} {req['currency']}\n"
                            f"🔗 Red: {req['network']}\n"
                            f"📝 TXID: {req.get('txid', 'N/A')}\n"
                            f"📅 Fecha: {req['created_at'][:16] if req.get('created_at') else 'N/A'}"
                        )
                        bot.send_message(call.message.chat.id, txt, parse_mode='Markdown', reply_markup=kb)
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener solicitudes")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

    # ----- Estadísticas -----
    elif call.data == "admin_stats":
        try:
            r = requests.get(f"{BASE_URL}/api/stats")
            if r.status_code == 200:
                s = r.json()
                txt = (
                    f"📊 *Estadísticas*\n"
                    f"👥 Usuarios: {s['total_users']}\n"
                    f"🚀 Naves: {s['total_ships']}\n"
                    f"👾 Aliens: {s['total_aliens']}\n"
                    f"💠 USDT en circulación: {s['total_usdt']:.2f}\n"
                    f"⭐ Stars en circulación: {s['total_stars']:.0f}\n"
                    f"📦 Listados P2P activos: {s['active_listings']}\n"
                    f"📋 Solicitudes pendientes: {s['pending_requests']}"
                )
                bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener estadísticas")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

    # ----- Usuarios -----
    elif call.data == "admin_users":
        try:
            r = requests.get(f"{BASE_URL}/api/users")
            if r.status_code == 200:
                users = r.json()
                if not users:
                    bot.send_message(call.message.chat.id, "👥 No hay usuarios registrados")
                else:
                    txt = "👥 *Usuarios registrados*\n\n"
                    for u in users[:15]:
                        txt += (
                            f"• {u.get('telegram_name', 'Sin nombre')} "
                            f"(@{u.get('telegram_username', 'sin usuario')}) - "
                            f"💠{u['balance_usdt']:.2f} ⭐{u['balance_stars']:.0f}\n"
                        )
                    if len(users) > 15:
                        txt += f"\n... y {len(users) - 15} más"
                    bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener usuarios")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

    # ----- Listados P2P -----
    elif call.data == "admin_p2p":
        try:
            r = requests.get(f"{BASE_URL}/api/p2p/listings/active")
            if r.status_code == 200:
                listings = r.json()
                if not listings:
                    bot.send_message(call.message.chat.id, "📦 No hay listados P2P activos")
                else:
                    txt = "📦 *Listados P2P activos*\n\n"
                    for l in listings[:10]:
                        txt += (
                            f"• {l['name']} ({l['rarity']}) - "
                            f"💠{l['price']:.2f} - "
                            f"Vendedor: @{l['seller_name']}\n"
                        )
                    if len(listings) > 10:
                        txt += f"\n... y {len(listings) - 10} más"
                    bot.send_message(call.message.chat.id, txt, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener listados")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

    # ----- VER TABLAS COMPLETAS (NUEVO) -----
    elif call.data == "admin_tables":
        try:
            r = requests.get(f"{BASE_URL}/api/admin/tables")
            if r.status_code == 200:
                data = r.json()
                msg = "📊 *TABLAS DE LA BASE DE DATOS*\n\n"

                # Usuarios
                msg += "👥 *USUARIOS*\n"
                if data['usuarios']:
                    for u in data['usuarios'][:10]:
                        msg += (
                            f"• ID:{u['id']} | {u['nombre']} (@{u['username']}) | "
                            f"💠{u['usdt']:.2f} ⭐{u['stars']:.0f} | "
                            f"🚀{u['naves']} 👾{u['aliens']} | ⛽{u['combustible']:.0f}\n"
                        )
                    if len(data['usuarios']) > 10:
                        msg += f"... y {len(data['usuarios'])-10} más\n"
                else:
                    msg += "   (vacía)\n"

                # Solicitudes
                msg += "\n📋 *SOLICITUDES DE BILLETERA*\n"
                if data['solicitudes']:
                    for s in data['solicitudes'][:10]:
                        msg += (
                            f"• #{s['id']} | Usuario:{s['usuario']} | "
                            f"{s['tipo'].upper()} {s['monto']} {s['moneda']} | "
                            f"Estado: {s['estado']}\n"
                        )
                    if len(data['solicitudes']) > 10:
                        msg += f"... y {len(data['solicitudes'])-10} más\n"
                else:
                    msg += "   (vacía)\n"

                # Listados P2P
                msg += "\n📦 *LISTADOS P2P*\n"
                if data['listados_p2p']:
                    for l in data['listados_p2p'][:10]:
                        msg += (
                            f"• {l['nombre']} ({l['rareza']}) | "
                            f"💠{l['precio']:.2f} | "
                            f"Vendedor: @{l['vendedor']} | "
                            f"Estado: {l['estado']}\n"
                        )
                    if len(data['listados_p2p']) > 10:
                        msg += f"... y {len(data['listados_p2p'])-10} más\n"
                else:
                    msg += "   (vacía)\n"

                # Enviar mensaje (si es muy largo, partir en varios)
                if len(msg) > 4096:
                    for x in range(0, len(msg), 4096):
                        bot.send_message(call.message.chat.id, msg[x:x+4096], parse_mode='Markdown')
                else:
                    bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "❌ Error al obtener las tablas")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

    # ----- RESETEAR BASE DE DATOS (NUEVO) -----
    elif call.data == "admin_reset":
        # Confirmación con botón
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Sí, resetear", callback_data="reset_confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="reset_cancel")
        )
        bot.send_message(
            call.message.chat.id,
            "⚠️ *¿Estás seguro de que quieres resetear la base de datos?*\n"
            "Se borrarán TODOS los datos (usuarios, transacciones, listados).\n"
            "Esta acción no se puede deshacer.",
            parse_mode='Markdown',
            reply_markup=kb
        )

    bot.answer_callback_query(call.id)

# ---------- CALLBACKS DE APROBAR/RECHAZAR ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_approve_reject(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "No autorizado")
        return
    parts = call.data.split('_')
    action = parts[0]
    req_id = int(parts[1])
    try:
        r = requests.put(f"{BASE_URL}/api/wallet-requests/{req_id}", json={"status": action})
        if r.status_code == 200:
            req = r.json()
            user_id = req['telegram_id']
            # Notificar al usuario
            try:
                bot.send_message(
                    user_id,
                    f"✅ *Tu solicitud #{req_id} ha sido {action}ada*",
                    parse_mode='Markdown'
                )
            except:
                pass
            bot.edit_message_text(
                f"Solicitud #{req_id} {action}ada correctamente",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "Error al procesar")
    except Exception as e:
        bot.answer_callback_query(call.id, f"Error: {str(e)}")

# ---------- CALLBACK DE RESET CONFIRMACIÓN ----------
@bot.callback_query_handler(func=lambda call: call.data in ["reset_confirm", "reset_cancel"])
def reset_confirmation(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "No autorizado")
        return

    if call.data == "reset_cancel":
        bot.edit_message_text(
            "❌ Reset cancelado.",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    # Confirmar reset
    try:
        r = requests.post(f"{BASE_URL}/api/admin/reset")
        if r.status_code == 200:
            bot.edit_message_text(
                "✅ *Base de datos reseteada correctamente.*\n"
                "Todas las tablas han sido vaciadas.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown'
            )
        else:
            bot.edit_message_text(
                "❌ Error al resetear la base de datos.",
                call.message.chat.id,
                call.message.message_id
            )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Error: {str(e)}",
            call.message.chat.id,
            call.message.message_id
        )
    bot.answer_callback_query(call.id)

# ---------- MENSAJES POR DEFECTO ----------
@bot.message_handler(func=lambda m: True)
def default(m):
    bot.send_message(m.chat.id, "Usa los botones del menú o /start")

# ============ INICIAR BOT EN HILO ============
def run_bot():
    logger.info("🤖 Bot de Telegram iniciado...")
    try:
        bot.polling(non_stop=True, interval=1)
    except Exception as e:
        logger.error(f"Error en el bot: {e}")
        time.sleep(5)
        run_bot()

# ============ ARRANQUE PRINCIPAL ============
if __name__ == "__main__":
    # Iniciar el bot en un hilo
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("🚀 Servidor FastAPI iniciando...")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
