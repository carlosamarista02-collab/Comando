import threading
import sqlite3
import time
import random
import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
TOKEN_TELEGRAM = '8939217389:AAHDVYsmfx8TFCbjtrZHlIfppajsPluJcQA'
URL_MINI_APP = 'https://dashing-quokka-8dcbf8.netlify.app/' 
DATABASE = '/data/flowerlan_db.db'
ADMIN_ID = 6808824866 

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
CORS(app)

# ==========================================
# GESTIÓN DE BASE DE DATOS
# ==========================================
def conectar_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row 
    return conn

def inicializar_base_datos():
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id INTEGER PRIMARY KEY,
            nombre TEXT,
            username TEXT,
            saldo_usdt REAL DEFAULT 0.0,
            saldo_lan REAL DEFAULT 1250.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            telegram_id INTEGER,
            item_tipo TEXT, 
            cantidad INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, item_tipo)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plantas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            rareza TEXT, 
            produccion_hora REAL,
            tiempo_inicio TEXT, 
            estado TEXT DEFAULT 'CRECIENDO' 
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mercado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planta_id INTEGER,
            vendedor_id INTEGER,
            precio REAL,
            fecha_publicacion TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            tipo TEXT,
            monto REAL,
            estado TEXT DEFAULT 'PENDIENTE',
            fecha_solicitud TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# ==========================================
# LÓGICA DEL BOT DE TELEGRAM
# ==========================================
@bot.message_handler(commands=['start'])
def enviar_bienvenida(message):
    try:
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
            cursor.execute("INSERT OR IGNORE INTO inventario (telegram_id, item_tipo, cantidad) VALUES (?, 'maceta_grande', 2)", (user_id,))
            cursor.execute("INSERT OR IGNORE INTO inventario (telegram_id, item_tipo, cantidad) VALUES (?, 'agua', 5)", (user_id,))
            conn.commit()
        conn.close()

        markup = InlineKeyboardMarkup(row_width=2)
        boton_jugar = InlineKeyboardButton(text="🚀 Jugar FlowerLan", web_app=telebot.types.WebAppInfo(url=URL_MINI_APP))
        
        if user_id == ADMIN_ID:
            btn_admin = InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="panel_admin")
            markup.add(boton_jugar, btn_admin)
        else:
            markup.add(boton_jugar)

        bot.send_message(message.chat.id, f"¡Hola {first_name}! Bienvenido a FlowerLan 🌻\nUsa la Mini App para gestionar tus fondos.", reply_markup=markup)
    except Exception as e:
        print(f"[BOT ERROR] Error en start: {e}")

@bot.callback_query_handler(func=lambda call: True)
def manejar_botones(call):
    try:
        user_id = call.from_user.id
        bot.answer_callback_query(call.id)
        
        if call.data == "panel_admin":
            if user_id != ADMIN_ID: 
                bot.send_message(call.message.chat.id, "❌ No tienes permisos.")
                return
            mostrar_panel_admin(call.message.chat.id)

        elif call.data.startswith("aprob_") or call.data.startswith("rech_"):
            if user_id != ADMIN_ID: return
            accion, tx_id = call.data.split("_")
            gestionar_transaccion_admin(int(tx_id), accion, call.message)
    except Exception as e:
        print(f"[BOT ERROR] Error en manejar_botones: {e}")

def mostrar_panel_admin(chat_id):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, telegram_id, tipo, monto FROM transacciones WHERE estado = 'PENDIENTE'")
        pendientes = cursor.fetchall()
        conn.close()
        
        if not pendientes:
            markup_vacio = InlineKeyboardMarkup()
            markup_vacio.add(InlineKeyboardButton("🔄 Verificar de nuevo", callback_data="panel_admin"))
            bot.send_message(chat_id, "⚙️ **Panel de Administración** ⚙️\n\n✅ Al día: No hay solicitudes de retiro o recarga pendientes.", parse_mode="Markdown", reply_markup=markup_vacio)
            return
            
        bot.send_message(chat_id, f"📥 ¡Tienes {len(pendientes)} solicitudes pendientes por revisar!")
        
        for tx in pendientes:
            # FIX: Extracción segura por nombre de columna
            tx_id = tx['id']
            u_id = tx['telegram_id']
            tipo = tx['tipo']
            monto = tx['monto']
            
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                       InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
            bot.send_message(chat_id, f"📥 **ID Transacción:** #{tx_id}\n👤 **User ID:** `{u_id}`\n📋 **Tipo:** {tipo}\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error mostrando panel: {e}")

def gestionar_transaccion_admin(tx_id, accion, message_obj):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, tipo, monto, estado FROM transacciones WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        
        # FIX: Acceso por nombre de columna para evitar caídas en Row
        if not tx or tx['estado'] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Ya procesada o inexistente.", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            conn.close()
            return
            
        u_id = tx['telegram_id']
        tipo = tx['tipo']
        monto = tx['monto']
        
        if accion == "aprob":
            if tipo == "RECARGA":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt + ? WHERE telegram_id = ?", (monto, u_id))
            elif tipo == "RETIRO":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - ? WHERE telegram_id = ?", (monto, u_id))
            
            cursor.execute("UPDATE transacciones SET estado = 'APROBADO' WHERE id = ?", (tx_id,))
            conn.commit()
            
            try:
                bot.send_message(u_id, f"🎉 Tu solicitud de {monto} USDT fue aprobada.")
            except: pass
            bot.edit_message_text(f"✅ #{tx_id} APROBADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
        else:
            cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = ?", (tx_id,))
            conn.commit()
            
            try:
                bot.send_message(u_id, f"❌ Tu solicitud de {monto} USDT fue rechazada.")
            except: pass
            bot.edit_message_text(f"❌ #{tx_id} RECHAZADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            
        conn.close()
    except Exception as e:
        print(f"Error gestionando transacción: {e}")

# ==========================================
# API FLASK PARA LA MINI APP
# ==========================================
@app.after_request
def evitar_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

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

@app.route('/obtener_inventario', methods=['GET'])
def obtener_inventario():
    user_id = request.args.get('id')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = ?", (user_id,))
    items = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
    conn.close()
    return jsonify(items)

@app.route('/comprar_item', methods=['POST'])
def comprar_item():
    datos = request.json
    user_id = datos.get('id')
    item = datos.get('item')
    try:
        cantidad = int(datos.get('cantidad', 1))
        if cantidad <= 0: raise ValueError
    except:
        return jsonify({"error": "Cantidad inválida"}), 400
    
    precios = {
        'maceta_grande': 50, 'agua': 10, 'semilla_misteriosa': 100,
        'maceta_especial': 200, 'fertilizante': 150,
        'granja_comun': 50, 'granja_rara': 150, 'granja_legendaria': 300
    }
    
    if item not in precios:
        return jsonify({"error": "Item no válido"}), 400
        
    costo_total = precios[item] * cantidad
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user or user['saldo_lan'] < costo_total:
        conn.close()
        return jsonify({"error": "Saldo $LAN insuficiente"}), 400
        
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - ? WHERE telegram_id = ?", (costo_total, user_id))
    
    cursor.execute("""
        INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
        VALUES (?, ?, ?) 
        ON CONFLICT(telegram_id, item_tipo) DO UPDATE SET cantidad = cantidad + ?
    """, (user_id, item, cantidad, cantidad))
    
    conn.commit()
    nuevo_saldo = user['saldo_lan'] - costo_total
    conn.close()
    
    return jsonify({"mensaje": "Compra exitosa", "nuevo_saldo": nuevo_saldo})

@app.route('/solicitar_recarga_web', methods=['POST'])
def solicitar_recarga_web():
    datos = request.json
    user_id = datos.get('id')
    monto_str = str(datos.get('monto')).replace(',', '.')
    
    try:
        monto = float(monto_str)
        if monto <= 0: raise ValueError
    except:
        return jsonify({"error": "Monto inválido"}), 400

    conn = conectar_db()
    cursor = conn.cursor()
    
    fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, fecha_solicitud) VALUES (?, ?, ?, ?)", 
                   (user_id, "RECARGA", monto, fecha_actual))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    try:
        # FIX: Envía la alerta directa con botones interactivos al Admin
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVA RECARGA PENDIENTE (DESDE WEB)**\n\n📥 **ID:** #{tx_id}\n👤 **Usuario:** `{user_id}`\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except:
        pass 
        
    return jsonify({"mensaje": "Solicitud enviada. Espera la aprobación del admin."})

@app.route('/solicitar_retiro_web', methods=['POST'])
def solicitar_retiro_web():
    datos = request.json
    user_id = datos.get('id')
    monto_str = str(datos.get('monto')).replace(',', '.')
    
    try:
        monto = float(monto_str)
        if monto <= 0: raise ValueError
    except:
        return jsonify({"error": "Monto inválido"}), 400

    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user or user['saldo_usdt'] < monto:
        conn.close()
        return jsonify({"error": "Saldo USDT insuficiente"}), 400

    fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, fecha_solicitud) VALUES (?, ?, ?, ?)", 
                   (user_id, "RETIRO", monto, fecha_actual))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    try:
        # FIX: Envía la alerta directa con botones interactivos al Admin
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVO RETIRO PENDIENTE (DESDE WEB)**\n\n📥 **ID:** #{tx_id}\n👤 **Usuario:** `{user_id}`\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except:
        pass
        
    return jsonify({"mensaje": "Solicitud de retiro enviada. Espera la aprobación."})

# ==========================================
# ARRANQUE
# ==========================================
def correr_bot_telegram():
    print("[Bot] Escuchando comandos...")
    bot.infinity_polling(timeout=20)

if __name__ == '__main__':
    inicializar_base_datos()
    
    hilo_bot = threading.Thread(target=correr_bot_telegram)
    hilo_bot.daemon = True
    hilo_bot.start()
    
    puerto = int(os.environ.get("PORT", 10000))
    print(f"🚀 Servidor FlowerLan activo en puerto: {puerto}")
    app.run(host='0.0.0.0', port=puerto, debug=False, use_reloader=False)

