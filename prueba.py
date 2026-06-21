import threading
import sqlite3
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
TOKEN_TELEGRAM = '8939217389:AAEhdiOAxP4Ny7IY2BUsqSTlblPOdiNwflE'
URL_MINI_APP = 'https://stellar-moonbeam-bef640.netlify.app/'
DATABASE = 'nueva_base_datos_v2.db'

# Administrador configurado con tu ID
ADMIN_ID = 6808824866  

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
CORS(app)

# ==========================================
# LIMPIEZA DE CACHÉ DE RESPUESTA (FLASK)
# ==========================================
@app.after_request
def evitar_cache(response):
    """Fuerza al navegador de la Mini App a pedir los saldos reales de la DB"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# ==========================================
# GESTIÓN DE BASE DE DATOS (SQLITE)
# ==========================================
def conectar_db():
    return sqlite3.connect(DATABASE)

def inicializar_base_datos():
    """Crea las tablas necesarias si no existen"""
    conn = conectar_db()
    cursor = conn.cursor()
    # Tabla de Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id INTEGER PRIMARY KEY,
            nombre TEXT,
            username TEXT,
            saldo_usdt REAL DEFAULT 0.0,
            saldo_lan REAL DEFAULT 1250.0
        )
    ''')
    # Tabla de Transacciones Pendientes (para el panel Admin)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            tipo TEXT,
            monto REAL,
            estado TEXT DEFAULT 'PENDIENTE'
        )
    ''')
    conn.commit()
    conn.close()

# ==========================================
# LÓGICA DEL BOT DE TELEGRAM (COMANDO /START Y PANEL)
# ==========================================
@bot.message_handler(commands=['start'])
def enviar_bienvenida(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username or ''

    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM usuarios WHERE telegram_id = ?", (user_id,))
    existe = cursor.fetchone()
    
    if not existe:
        cursor.execute(
            "INSERT INTO usuarios (telegram_id, nombre, username, saldo_usdt, saldo_lan) VALUES (?, ?, ?, 0.0, 1250.0)",
            (user_id, first_name, username)
        )
        conn.commit()
        print(f"[DB] Nuevo usuario registrado: {first_name} ({user_id})")
    conn.close()

    # Teclado con todas las opciones solicitadas
    markup = InlineKeyboardMarkup(row_width=2)
    
    boton_jugar = InlineKeyboardButton(text="🚀 Jugar FlowerLan", web_app=telebot.types.WebAppInfo(url=URL_MINI_APP))
    boton_noticia = InlineKeyboardButton(text="📢 Noticias", callback_data="ver_noticias")
    boton_recarga = InlineKeyboardButton(text="💳 Solicitar Recarga", callback_data="solicitar_recarga")
    boton_retiro = InlineKeyboardButton(text="💰 Solicitar Retiro", callback_data="solicitar_retiro")
    
    markup.add(boton_jugar)
    markup.row(boton_recarga, boton_retiro)
    markup.add(boton_noticia)

    # Si eres el Administrador, se añade el botón del Panel de Control
    if user_id == ADMIN_ID:
        boton_admin = InlineKeyboardButton(text="⚙️ Panel Administrador", callback_data="panel_admin")
        markup.add(boton_admin)

    mensaje_texto = (
        f"¡Hola {first_name}! 👋 Bienvenido(a) a **FlowerLan**.\n\n"
        f"Usa el menú interactivo para gestionar tus fondos, enterarte de las novedades o iniciar tu aventura agrícola."
    )
    bot.send_message(message.chat.id, mensaje_texto, parse_mode='Markdown', reply_markup=markup)

# ==========================================
# ACCIONES INTERACTIVAS DEL BOT (CALLBACK QUERY)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def manejar_botones(call):
    user_id = call.from_user.id
    
    if call.data == "ver_noticias":
        texto_noticias = (
            "📢 **NOTICIAS DE FLOWERLAN** 📢\n\n"
            "🌱 **Nueva Actualización v1.2**\n"
            "El crecimiento de las plantas comunes se ha optimizado un 10%.\n\n"
            "⚔️ **Sistema P2P Activo**\n"
            "Ya puedes comercializar tus soldados y naves usando sus IDs únicos en el mercado global."
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, texto_noticias, parse_mode='Markdown')

    elif call.data == "solicitar_recarga":
        bot.answer_callback_query(call.id)
        # Limpia cualquier paso de espera viejo en este chat para evitar colisiones
        bot.clear_step_handler_by_chat_id(chat_id=call.message.chat.id)
        msg = bot.send_message(call.message.chat.id, "✍️ Ingresa el monto en USDT que deseas **recargar**:")
        bot.register_next_step_handler(msg, procesar_solicitud_fondos, "RECARGA")

    elif call.data == "solicitar_retiro":
        bot.answer_callback_query(call.id)
        # Limpia cualquier paso de espera viejo en este chat para evitar colisiones
        bot.clear_step_handler_by_chat_id(chat_id=call.message.chat.id)
        msg = bot.send_message(call.message.chat.id, "✍️ Ingresa el monto en USDT que deseas **retirar**:")
        bot.register_next_step_handler(msg, procesar_solicitud_fondos, "RETIRO")

    elif call.data == "panel_admin":
        bot.answer_callback_query(call.id)
        if user_id != ADMIN_ID:
            bot.send_message(call.message.chat.id, "❌ No tienes permisos para ver esto.")
            return
        
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, telegram_id, tipo, monto FROM transacciones WHERE estado = 'PENDIENTE'")
        pendientes = cursor.fetchall()
        conn.close()

        if not pendientes:
            bot.send_message(call.message.chat.id, "✅ No hay solicitudes pendientes de aprobación.")
            return

        for tx_id, u_id, tipo, monto in pendientes:
            markup_tx = InlineKeyboardMarkup()
            btn_aprobar = InlineKeyboardButton(text="✅ Aprobar", callback_data=f"aprob_{tx_id}")
            btn_rechazar = InlineKeyboardButton(text="❌ Reject", callback_data=f"rech_{tx_id}")
            markup_tx.row(btn_aprobar, btn_rechazar)

            bot.send_message(
                ADMIN_ID, 
                f"📥 **Solicitud #{tx_id}**\n👤 ID Usuario: `{u_id}`\n🗂 Tipo: {tipo}\n💵 Monto: {monto} USDT", 
                parse_mode='Markdown', 
                reply_markup=markup_tx
            )

    # Procesar Aprobación/Rechazo del Administrador
    elif call.data.startswith("aprob_") or call.data.startswith("rech_"):
        bot.answer_callback_query(call.id)
        if user_id != ADMIN_ID: return
        
        accion, tx_id = call.data.split("_")
        conn = conectar_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT telegram_id, tipo, monto, estado FROM transacciones WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        
        if not tx or tx[3] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Esta transacción ya fue procesada.", chat_id=call.message.chat.id, message_id=call.message.message_id)
            conn.close()
            return
            
        u_id, tipo, monto, _ = tx
        
        if accion == "aprob":
            if tipo == "RECARGA":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt + ? WHERE telegram_id = ?", (monto, u_id))
            elif tipo == "RETIRO":
                cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = ?", (u_id,))
                saldo = cursor.fetchone()[0]
                if saldo < monto:
                    bot.send_message(ADMIN_ID, "❌ El usuario ya no cuenta con saldo suficiente para este retiro.")
                    cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = ?", (tx_id,))
                    conn.commit()
                    conn.close()
                    return
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - ? WHERE telegram_id = ?", (monto, u_id))
            
            cursor.execute("UPDATE transacciones SET estado = 'APROBADO' WHERE id = ?", (tx_id,))
            bot.edit_message_text(f"✅ Solicitud #{tx_id} **APROBADA**.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
            bot.send_message(u_id, f"🎉 ¡Tu solicitud de {tipo} por **{monto} USDT** ha sido aprobada!")
        
        else:
            cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = ?", (tx_id,))
            bot.edit_message_text(f"❌ Solicitud #{tx_id} **RECHAZADA**.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
            bot.send_message(u_id, f"⚠️ Tu solicitud de {tipo} por **{monto} USDT** fue rechazada por el administrador.")
            
        conn.commit()
        conn.close()

def procesar_solicitud_fondos(message, tipo):
    try:
        monto = float(message.text)
        if monto <= 0: raise ValueError
        
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto) VALUES (?, ?, ?)", (message.from_user.id, tipo, monto))
        conn.commit()
        conn.close()

        bot.send_message(message.chat.id, f"⏳ Tu solicitud de {tipo} por **{monto} USDT** ha sido enviada al administrador para su revisión.", parse_mode='Markdown')
        bot.send_message(ADMIN_ID, f"🔔 **Nueva {tipo} pendiente**: El usuario `{message.from_user.id}` solicita {monto} USDT. Usa el botón del Panel para procesar.")
    except:
        bot.send_message(message.chat.id, "❌ Monto inválido. Ingresa un número válido mayor a 0.")

# ==========================================
# LÓGICA DE LA API FLASK (PARA LA MINI APP)
# ==========================================
@app.route('/obtener_perfil', methods=['GET'])
def obtener_perfil():
    user_id = request.args.get('id')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT saldo_usdt, saldo_lan FROM usuarios WHERE telegram_id = ?", (user_id,))
    data = cursor.fetchone()
    conn.close()
    
    if data:
        return jsonify({"usdt": data[0], "lan": data[1]})
    return jsonify({"error": "Usuario no registrado"}), 404

@app.route('/play', methods=['POST'])
def play():
    datos = request.json
    user_id = datos.get('id')
    return jsonify({"mensaje": "¡Sincronización de juego FlowerLan exitosa!"})

def correr_bot_telegram():
    print("[Bot] Escuchando comandos en Telegram...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"[⚠️ Alerta de Red] Conexión interrumpida: {e}. Reintentando en 5 segundos...")
            import time
            time.sleep(5)

# ==========================================
# ARRANQUE UNIFICADO ADAPTADO A RENDER
# ==========================================
if __name__ == '__main__':
    inicializar_base_datos()
    
    # Iniciamos el Bot de Telegram en su propio hilo secundario
    hilo_bot = threading.Thread(target=correr_bot_telegram)
    hilo_bot.daemon = True
    hilo_bot.start()
    
    # Render asigna el puerto mediante la variable de entorno PORT, si no existe usa el 10000
    puerto = int(os.environ.get("PORT", 10000))
    print(f"[API] Iniciando servidor Flask en el puerto {puerto}...")
    app.run(host='0.0.0.0', port=puerto, debug=False, use_reloader=False)
