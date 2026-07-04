import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import logging
import os
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============ CONFIGURACIÓN ============
# IMPORTANTE: El token ahora se lee desde las variables de entorno de Render.
# NO escribas el token directamente aquí.
BOT_TOKEN = os.getenv('8206009148:AAGPVgO2VLfKYcUNy-BlBGWfv40gwrFivHQ', '')
ADMIN_ID = 6808824866
API_URL = os.getenv('API_URL', 'https://comando-evkk.onrender.com')
PORT = int(os.environ.get('PORT', 8080))

# Verificar token (Evita que el bot arranque si no hay token configurado)
if not BOT_TOKEN or len(BOT_TOKEN) < 20:
    print("❌ ERROR CRÍTICO: Token inválido o vacío. Asegúrate de configurar BOT_TOKEN en las variables de entorno de Render.")
    exit(1)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# ============ SERVIDOR HTTP PARA KEEP-ALIVE (Render) ============
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def log_message(self, format, *args):
        return  # Silenciar logs del servidor HTTP

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), KeepAliveHandler)
    logger.info(f"🌐 Servidor HTTP escuchando en el puerto {PORT} (para mantener vivo el bot)")
    server.serve_forever()

# ============ CLASE LOCALDB (respaldo) ============
class LocalDB:
    def __init__(self):
        self.users = {}
        self.wallet_requests = {}
        self.p2p_listings = {}
        self.request_counter = 0
    
    def get_user(self, telegram_id):
        return self.users.get(str(telegram_id))
    
    def save_user(self, user_data):
        self.users[str(user_data['telegram_id'])] = user_data
        return user_data
    
    def create_wallet_request(self, request_data):
        self.request_counter += 1
        request_id = self.request_counter
        request_data['id'] = request_id
        request_data['status'] = 'pending'
        request_data['created_at'] = datetime.utcnow().isoformat()
        self.wallet_requests[str(request_id)] = request_data
        return request_data
    
    def get_pending_requests(self):
        return [r for r in self.wallet_requests.values() if r['status'] == 'pending']
    
    def get_request(self, request_id):
        return self.wallet_requests.get(str(request_id))
    
    def update_request(self, request_id, status):
        if str(request_id) in self.wallet_requests:
            self.wallet_requests[str(request_id)]['status'] = status
            self.wallet_requests[str(request_id)]['updated_at'] = datetime.utcnow().isoformat()
            return self.wallet_requests[str(request_id)]
        return None

db = LocalDB()

# ============ FUNCIONES DE API ============
def api_request(method, endpoint, data=None):
    """Función para hacer peticiones a la API"""
    url = f"{API_URL}{endpoint}"
    try:
        if method == 'GET':
            response = requests.get(url, timeout=10)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=10)
        elif method == 'PUT':
            response = requests.put(url, json=data, timeout=10)
        else:
            return None
        
        if response.status_code == 200:
            return response.json()
        logger.warning(f"API error {response.status_code}: {response.text}")
        return None
    except Exception as e:
        logger.error(f"Error en api_request: {e}")
        return None

def get_user_from_api(telegram_id):
    """Obtener usuario de la API o crearlo si no existe"""
    user = api_request('GET', f'/api/users/{telegram_id}')
    if user:
        db.save_user(user)
        return user
    
    user_data = {
        'telegram_id': telegram_id,
        'telegram_username': None,
        'telegram_name': None,
        'balance_usdt': 0.0,
        'balance_stars': 0.0,
        'ships': [],
        'aliens': [],
        'planets': [],
        'fuel_available': 0,
        'has_done_expedition': False,
        'active_contract': None
    }
    created = api_request('POST', '/api/users', user_data)
    if created:
        db.save_user(created)
        return created
    return user_data

# ============ COMANDOS PRINCIPALES ============
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Usuario"
    name = message.from_user.first_name or ""
    
    logger.info(f"📥 /start desde {user_id} (@{username})")
    
    # Registrar usuario
    user_data = {
        'telegram_id': user_id,
        'telegram_username': username,
        'telegram_name': name
    }
    api_request('POST', '/api/users', user_data)
    db.save_user(user_data)
    
    # Crear teclado
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    play_btn = KeyboardButton("🎮 PLAY")
    profile_btn = KeyboardButton("📋 Perfil")
    balance_btn = KeyboardButton("💰 Saldo")
    keyboard.add(play_btn, profile_btn, balance_btn)
    
    if user_id == ADMIN_ID:
        admin_btn = KeyboardButton("🔐 Panel Admin")
        keyboard.add(admin_btn)
    
    welcome_text = f"""
🚀 *¡Bienvenido a XENOPORT, Capitán {name}!*

Tu aventura espacial comienza aquí. 
Explora el universo, recolecta naves y alienígenas.

🌌 *¡Que la fuerza te acompañe!*
"""
    
    bot.send_message(
        message.chat.id, 
        welcome_text, 
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: message.text == "🎮 PLAY")
def play_button(message):
    keyboard = InlineKeyboardMarkup()
    play_btn = InlineKeyboardButton("🚀 ABRIR XENOPORT", url=API_URL)
    keyboard.add(play_btn)
    
    bot.send_message(
        message.chat.id,
        "🛸 *Prepárate para la aventura espacial!*\n\nHaz clic en el botón para comenzar:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: message.text == "📋 Perfil")
def profile_button(message):
    user_id = message.from_user.id
    user = api_request('GET', f'/api/users/{user_id}')
    if not user:
        user = db.get_user(user_id)
    
    if not user:
        bot.send_message(message.chat.id, "❌ No se pudo obtener tu perfil")
        return
    
    ships_count = len(user.get('ships', []))
    aliens_count = len(user.get('aliens', []))
    
    profile_text = f"""
📋 *Tu Perfil*

🆔 ID: {user.get('telegram_id')}
👤 Nombre: {user.get('telegram_name', 'Sin nombre')}
🐦 Usuario: @{user.get('telegram_username', 'sin usuario')}

💰 *Saldo:*
💠 USDT: {user.get('balance_usdt', 0):.2f}
⭐ Stars: {user.get('balance_stars', 0):.0f}
⛽ Combustible: {user.get('fuel_available', 0):.0f}

🚀 *Inventario:*
Naves: {ships_count}
Aliens: {aliens_count}

📅 Miembro desde: {user.get('created_at', '')[:10] if user.get('created_at') else 'N/A'}
"""
    bot.send_message(message.chat.id, profile_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "💰 Saldo")
def balance_button(message):
    user_id = message.from_user.id
    user = api_request('GET', f'/api/users/{user_id}')
    if not user:
        user = db.get_user(user_id)
    
    if not user:
        bot.send_message(message.chat.id, "❌ No se pudo obtener tu saldo")
        return
    
    balance_text = f"""
💰 *Tu Saldo*

💠 *USDT:* {user.get('balance_usdt', 0):.2f}
⭐ *Stars:* {user.get('balance_stars', 0):.0f}
⛽ *Combustible:* {user.get('fuel_available', 0):.0f}

📊 *Total de activos:*
🚀 Naves: {len(user.get('ships', []))}
👾 Aliens: {len(user.get('aliens', []))}
"""
    bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')

# ============ PANEL DE ADMINISTRACIÓN ============
@bot.message_handler(func=lambda message: message.text == "🔐 Panel Admin")
def admin_panel_button(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ No tienes permisos de administrador")
        return
    
    show_admin_panel(message.chat.id)

def show_admin_panel(chat_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📋 Solicitudes Pendientes", callback_data="admin_pending"),
        InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")
    )
    keyboard.add(
        InlineKeyboardButton("👥 Usuarios", callback_data="admin_users"),
        InlineKeyboardButton("📦 Listados P2P", callback_data="admin_p2p")
    )
    keyboard.add(
        InlineKeyboardButton("📊 Ver Tablas", callback_data="admin_tables"),
        InlineKeyboardButton("🗑️ Resetear Base de Datos", callback_data="admin_reset")
    )
    
    bot.send_message(
        chat_id,
        "🔐 *Panel de Administración de XENOPORT*\n\nSelecciona una opción:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

# ============ CALLBACKS DEL ADMIN ============
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ No tienes permisos")
        return
    
    if call.data == "admin_pending":
        show_pending_requests(call.message)
    elif call.data == "admin_stats":
        show_stats(call.message)
    elif call.data == "admin_users":
        show_users(call.message)
    elif call.data == "admin_p2p":
        show_p2p_listings(call.message)
    elif call.data == "admin_tables":
        show_tables(call.message)
    elif call.data == "admin_reset":
        ask_reset_confirmation(call.message)
    
    bot.answer_callback_query(call.id)

# ---------- SOLICITUDES PENDIENTES ----------
def show_pending_requests(message):
    requests_data = api_request('GET', '/api/wallet-requests/pending')
    if not requests_data:
        requests_data = db.get_pending_requests()
    
    if not requests_data:
        bot.send_message(message.chat.id, "✅ No hay solicitudes pendientes")
        return
    
    for req in requests_data:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{req['id']}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{req['id']}")
        )
        
        text = f"""
📋 *Solicitud #{req['id']}*
👤 Usuario: {req.get('telegram_name', 'Desconocido')}
🆔 ID: {req.get('telegram_id')}
📊 Tipo: {req.get('type', 'N/A').upper()}
💰 Monto: {req.get('amount', 0)} {req.get('currency', 'USDT')}
🔗 Red: {req.get('network', 'N/A')}
📝 TXID: {req.get('txid', 'N/A')}
📅 Fecha: {req.get('created_at', '')[:16] if req.get('created_at') else 'N/A'}
"""
        bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=keyboard)

# ---------- ESTADÍSTICAS ----------
def show_stats(message):
    stats = api_request('GET', '/api/stats')
    if not stats:
        users = db.users
        pending = len(db.get_pending_requests())
        stats = {
            'total_users': len(users),
            'total_ships': 0,
            'total_aliens': 0,
            'total_usdt': 0,
            'total_stars': 0,
            'active_listings': 0,
            'pending_requests': pending
        }
        for user in users.values():
            stats['total_ships'] += len(user.get('ships', []))
            stats['total_aliens'] += len(user.get('aliens', []))
            stats['total_usdt'] += user.get('balance_usdt', 0)
            stats['total_stars'] += user.get('balance_stars', 0)
    
    text = f"""
📊 *Estadísticas de XENOPORT*

👥 *Usuarios:* {stats.get('total_users', 0)}
🚀 *Naves totales:* {stats.get('total_ships', 0)}
👾 *Aliens totales:* {stats.get('total_aliens', 0)}

💰 *Economía:*
💠 USDT en circulación: {stats.get('total_usdt', 0):.2f}
⭐ Stars en circulación: {stats.get('total_stars', 0):.0f}

📦 *Mercado P2P:* {stats.get('active_listings', 0)} activos
📋 *Solicitudes pendientes:* {stats.get('pending_requests', 0)}
"""
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ---------- USUARIOS ----------
def show_users(message):
    users = api_request('GET', '/api/users')
    if not users:
        users = list(db.users.values())
    
    if not users:
        bot.send_message(message.chat.id, "👥 No hay usuarios registrados")
        return
    
    text = "👥 *Usuarios Registrados*\n\n"
    for user in users[:15]:
        name = user.get('telegram_name', 'Usuario')
        username = user.get('telegram_username', '')
        usdt = user.get('balance_usdt', 0)
        stars = user.get('balance_stars', 0)
        ships = len(user.get('ships', []))
        aliens = len(user.get('aliens', []))
        text += f"• {name} (@{username}) - 💠{usdt:.2f} ⭐{stars:.0f} 🚀{ships} 👾{aliens}\n"
    
    if len(users) > 15:
        text += f"\n... y {len(users) - 15} más"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ---------- LISTADOS P2P ----------
def show_p2p_listings(message):
    listings = api_request('GET', '/api/p2p/listings/active')
    if not listings:
        bot.send_message(message.chat.id, "📦 No hay listados P2P activos")
        return
    
    text = "📦 *Listados P2P Activos*\n\n"
    for l in listings[:10]:
        name = l.get('name', 'Desconocido')
        rarity = l.get('rarity', 'Común')
        price = l.get('price', 0)
        seller = l.get('seller_name', 'Anónimo')
        item_type = l.get('type', 'item').upper()
        text += f"• {name} ({rarity}) - 💠{price:.2f} - {item_type} - Vendedor: @{seller}\n"
    
    if len(listings) > 10:
        text += f"\n... y {len(listings) - 10} más"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ---------- VER TABLAS ----------
def show_tables(message):
    try:
        r = requests.get(f"{API_URL}/api/admin/tables", timeout=10)
        if r.status_code == 200:
            data = r.json()
            msg = "📊 *TABLAS DE LA BASE DE DATOS*\n\n"

            msg += "👥 *USUARIOS*\n"
            if data.get('usuarios'):
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

            msg += "\n📋 *SOLICITUDES DE BILLETERA*\n"
            if data.get('solicitudes'):
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

            msg += "\n📦 *LISTADOS P2P*\n"
            if data.get('listados_p2p'):
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

            if len(msg) > 4096:
                for x in range(0, len(msg), 4096):
                    bot.send_message(message.chat.id, msg[x:x+4096], parse_mode='Markdown')
            else:
                bot.send_message(message.chat.id, msg, parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, "❌ Error al obtener las tablas")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {str(e)}")

# ---------- RESET ----------
def ask_reset_confirmation(message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Sí, resetear", callback_data="reset_confirm"),
        InlineKeyboardButton("❌ Cancelar", callback_data="reset_cancel")
    )
    bot.send_message(
        message.chat.id,
        "⚠️ *¿Estás seguro de que quieres resetear la base de datos?*\n"
        "Se borrarán TODOS los datos (usuarios, transacciones, listados).\n"
        "Esta acción no se puede deshacer.",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

# ---------- APROBAR/RECHAZAR ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_request_action(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ No tienes permisos")
        return
    
    parts = call.data.split('_')
    action = parts[0]
    request_id = int(parts[1])
    
    result = api_request('PUT', f'/api/wallet-requests/{request_id}', {"status": action})
    if not result:
        result = db.update_request(request_id, action)
    
    if result:
        req = api_request('GET', f'/api/wallet-requests/{request_id}')
        if not req:
            req = db.get_request(request_id)
        
        if req:
            user_id = req.get('telegram_id')
            amount = req.get('amount', 0)
            currency = req.get('currency', 'USDT')
            
            if action == 'approved':
                try:
                    bot.send_message(
                        user_id,
                        f"✅ *Tu solicitud #{request_id} ha sido APROBADA!*\n\n💰 Monto: {amount} {currency}\n💠 Tu saldo ha sido actualizado.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                bot.edit_message_text(
                    f"✅ Solicitud #{request_id} APROBADA correctamente",
                    call.message.chat.id,
                    call.message.message_id
                )
            else:
                try:
                    bot.send_message(
                        user_id,
                        f"❌ *Tu solicitud #{request_id} ha sido RECHAZADA*\n\n💰 Monto: {amount} {currency}\n📝 Motivo: Revisión manual no aprobada.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                bot.edit_message_text(
                    f"❌ Solicitud #{request_id} RECHAZADA",
                    call.message.chat.id,
                    call.message.message_id
                )
    else:
        bot.answer_callback_query(call.id, "❌ Error al procesar la solicitud")

# ---------- RESET CONFIRMACIÓN ----------
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

    try:
        r = requests.post(f"{API_URL}/api/admin/reset", timeout=10)
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
@bot.message_handler(func=lambda message: True)
def default_message(message):
    if message.text and message.text.startswith('/'):
        return
    
    help_text = """
❓ *Comandos disponibles:*

🎮 *PLAY* - Abrir el juego
📋 *Perfil* - Ver tu perfil
💰 *Saldo* - Ver tu saldo
🔐 *Panel Admin* - Panel de administración (solo admin)

O usa los botones del menú.
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# ============ FUNCIÓN PARA INICIAR EL BOT (POLLING) ============
def run_bot():
    logger.info("🚀 Bot de XENOPORT iniciado (modo polling)...")
    logger.info(f"🤖 Bot token: {BOT_TOKEN[:10]}...") 
    logger.info(f"👤 Admin ID: {ADMIN_ID}")
    logger.info(f"🌐 API URL: {API_URL}")
    logger.info("⏳ El bot está escuchando mensajes...")
    
    # Eliminar webhook existente para evitar conflictos
    try:
        bot.remove_webhook()
        logger.info("✅ Webhook eliminado (modo polling activo)")
    except Exception as e:
        logger.warning(f"No se pudo eliminar webhook: {e}")
    
    while True:
        try:
            bot.polling(non_stop=True, interval=1, timeout=30, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"❌ Error en polling: {e}")
            time.sleep(5)

# ============ ARRANQUE PRINCIPAL ============
if __name__ == "__main__":
    # Iniciar servidor HTTP para mantener el bot vivo en Render
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    logger.info(f"🌐 Servidor HTTP iniciado en el puerto {PORT}")
    
    # Iniciar el bot (polling) en el hilo principal
    run_bot()
