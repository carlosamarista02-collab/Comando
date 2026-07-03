import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import requests
import json
from datetime import datetime
import threading
import time

# ============ CONFIGURACIÓN ============
BOT_TOKEN = "8206009148:AAEEWSYAgxj3MRR8xGOe-s7V5COl5htsYnY"
ADMIN_ID = 6808824866
API_URL = "http://localhost:8000"

bot = telebot.TeleBot(BOT_TOKEN)

# ============ BASE DE DATOS LOCAL (para respaldo) ============
class LocalDB:
    def __init__(self):
        self.users = {}
        self.wallet_requests = {}
        self.p2p_listings = {}
    
    def get_user(self, telegram_id):
        return self.users.get(str(telegram_id))
    
    def save_user(self, user_data):
        self.users[str(user_data['telegram_id'])] = user_data
        return user_data
    
    def create_wallet_request(self, request_data):
        request_id = len(self.wallet_requests) + 1
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
            response = requests.get(url, timeout=5)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=5)
        elif method == 'PUT':
            response = requests.put(url, json=data, timeout=5)
        else:
            return None
        
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

def get_user_from_api(telegram_id):
    """Obtener usuario de la API o crearlo si no existe"""
    # Intentar obtener de la API
    user = api_request('GET', f'/api/users/{telegram_id}')
    if user:
        db.save_user(user)
        return user
    
    # Si no existe, crearlo
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
    
    # Registrar usuario
    user_data = {
        'telegram_id': user_id,
        'telegram_username': username,
        'telegram_name': name
    }
    api_request('POST', '/api/users', user_data)
    db.save_user(user_data)
    
    # Crear teclado con botón Play
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    play_btn = KeyboardButton("🎮 PLAY")
    profile_btn = KeyboardButton("📋 Perfil")
    balance_btn = KeyboardButton("💰 Saldo")
    keyboard.add(play_btn, profile_btn, balance_btn)
    
    # Si es admin, agregar botón de admin
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
    # Crear botón con URL del juego
    keyboard = InlineKeyboardMarkup()
    play_btn = InlineKeyboardButton("🚀 ABRIR XENOPORT", url="https://tu-dominio.com/index.html")
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
    
    # Intentar obtener de API
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
        InlineKeyboardButton("🔄 Sincronizar", callback_data="admin_sync")
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
    
    elif call.data == "admin_sync":
        bot.answer_callback_query(call.id, "🔄 Sincronizando datos...")
        # Aquí se puede agregar lógica de sincronización
        bot.send_message(call.message.chat.id, "✅ Datos sincronizados correctamente")
    
    bot.answer_callback_query(call.id)

# ============ SOLICITUDES PENDIENTES ============
def show_pending_requests(message):
    # Intentar obtener de API
    requests_data = api_request('GET', '/api/wallet-requests/pending')
    if not requests_data:
        # Usar datos locales
        requests_data = db.get_pending_requests()
    
    if not requests_data:
        bot.send_message(message.chat.id, "✅ No hay solicitudes pendientes")
        return
    
    # Enviar cada solicitud con botones de acción
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

# ============ APROBAR/RECHAZAR SOLICITUDES ============
@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_request_action(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ No tienes permisos")
        return
    
    parts = call.data.split('_')
    action = parts[0]
    request_id = int(parts[1])
    
    # Intentar actualizar en API
    result = api_request('PUT', f'/api/wallet-requests/{request_id}', {"status": action})
    
    if not result:
        # Usar base de datos local
        result = db.update_request(request_id, action)
    
    if result:
        # Obtener la solicitud para notificar al usuario
        req = api_request('GET', f'/api/wallet-requests/{request_id}')
        if not req:
            req = db.get_request(request_id)
        
        if req:
            user_id = req.get('telegram_id')
            amount = req.get('amount', 0)
            currency = req.get('currency', 'USDT')
            
            if action == 'approved':
                # Notificar al usuario
                text = f"""
✅ *¡Tu solicitud #{request_id} ha sido APROBADA!*

💰 Monto: {amount} {currency}
💠 Tu saldo ha sido actualizado.

¡Gracias por confiar en XENOPORT! 🚀
"""
                try:
                    bot.send_message(user_id, text, parse_mode='Markdown')
                except:
                    pass
                
                bot.edit_message_text(
                    f"✅ Solicitud #{request_id} APROBADA correctamente",
                    call.message.chat.id,
                    call.message.message_id
                )
            else:
                # Notificar al usuario
                text = f"""
❌ *Tu solicitud #{request_id} ha sido RECHAZADA*

💰 Monto: {amount} {currency}
📝 Motivo: Revisión manual no aprobada.

Por favor, contacta con soporte para más información.
"""
                try:
                    bot.send_message(user_id, text, parse_mode='Markdown')
                except:
                    pass
                
                bot.edit_message_text(
                    f"❌ Solicitud #{request_id} RECHAZADA",
                    call.message.chat.id,
                    call.message.message_id
                )
    else:
        bot.answer_callback_query(call.id, "❌ Error al procesar la solicitud")

# ============ ESTADÍSTICAS ============
def show_stats(message):
    stats = api_request('GET', '/api/stats')
    
    if not stats:
        # Estadísticas locales
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

# ============ USUARIOS ============
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

# ============ LISTADOS P2P ============
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

# ============ MENSAJES POR DEFECTO ============
@bot.message_handler(func=lambda message: True)
def default_message(message):
    if message.text and message.text.startswith('/'):
        return
    
    # Mensaje de ayuda para texto no reconocido
    help_text = """
❓ *Comandos disponibles:*

🎮 *PLAY* - Abrir el juego
📋 *Perfil* - Ver tu perfil
💰 *Saldo* - Ver tu saldo
🔐 *Panel Admin* - Panel de administración (solo admin)

O usa los botones del menú.
"""
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# ============ INICIAR EL BOT ============
def run_bot():
    print("🚀 Bot de XENOPORT iniciado...")
    print(f"🤖 Token: {BOT_TOKEN[:10]}...")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print("✅ Bot listo para usar!")
    
    try:
        bot.polling(non_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"❌ Error en el bot: {e}")
        time.sleep(5)
        run_bot()

if __name__ == "__main__":
    run_bot()
