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
TOKEN_TELEGRAM = '8939217389:AAEjcV86PramtLXvZ2sLCnCB8xrX8ZzFEMQ'
URL_MINI_APP = 'https://dashing-quokka-8dcbf8.netlify.app/' 
DATABASE = 'flowerlan_db.db'
ADMIN_ID = 6808824866

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
CORS(app)

# ==========================================
# LIMPIEZA DE CACHÉ (IMPORTANTE PARA SALDOS)
# ==========================================
@app.after_request
def evitar_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# ==========================================
# GESTIÓN DE BASE DE DATOS
# ==========================================
def conectar_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row 
    return conn

def inicializar_base_datos():
    """Crea todas las tablas necesarias para el juego"""
    conn = conectar_db()
    cursor = conn.cursor()
    
    # 1. Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id INTEGER PRIMARY KEY,
            nombre TEXT,
            username TEXT,
            saldo_usdt REAL DEFAULT 0.0,
            saldo_lan REAL DEFAULT 1250.0
        )
    ''')
    
    # 2. Inventario (Items del usuario)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            telegram_id INTEGER,
            item_tipo TEXT, 
            cantidad INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, item_tipo)
        )
    ''')
    
    # 3. Plantas Activas
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
    
    # 4. Mercado P2P
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mercado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planta_id INTEGER,
            vendedor_id INTEGER,
            precio REAL,
            fecha_publicacion TEXT
        )
    ''')
    
    # 5. Transacciones (Admin)
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
    print("[DB] Base de datos inicializada correctamente.")

# ==========================================
# LÓGICA DEL BOT DE TELEGRAM (CORREGIDO COMPLETO)
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
            # SE CORRIGIERON LAS LÍNEAS DEL INVENTARIO AQUÍ:
            cursor.execute("INSERT OR IGNORE INTO inventario (telegram_id, item_tipo, cantidad) VALUES (?, 'maceta_grande', 2)", (user_id,))
            cursor.execute("INSERT OR IGNORE INTO inventario (telegram_id, item_tipo, cantidad) VALUES (?, 'agua', 5)", (user_id,))
            conn.commit()
            print(f"[DB] Nuevo usuario registrado: {first_name} ({user_id})")
        conn.close()

        markup = InlineKeyboardMarkup(row_width=2)
        boton_jugar = InlineKeyboardButton(text="🚀 Jugar FlowerLan", web_app=telebot.types.WebAppInfo(url=URL_MINI_APP))
        boton_recarga = InlineKeyboardButton(text="💳 Recargar USDT", callback_data="solicitar_recarga")
        boton_retiro = InlineKeyboardButton(text="💰 Retirar USDT", callback_data="solicitar_retiro")
        
        markup.add(boton_jugar)
        markup.row(boton_recarga, boton_retiro)

        if user_id == ADMIN_ID:
            btn_admin = InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="panel_admin")
            markup.add(btn_admin)

        bot.send_message(message.chat.id, f"¡Hola {first_name}! Bienvenido a FlowerLan 🌻", reply_markup=markup)
    except Exception as e:
        print(f"[BOT ERROR] Error en start: {e}")

@bot.callback_query_handler(func=lambda call: True)
def manejar_botones(call):
    try:
        user_id = call.from_user.id
        # Responde al callback al instante para que no se congele el botón en la pantalla
        bot.answer_callback_query(call.id)
        
        if call.data == "solicitar_recarga":
            msg = bot.send_message(call.message.chat.id, "✍️ Ingresa el monto USDT a recargar:")
            bot.register_next_step_handler(msg, lambda m: procesar_solicitud_fondos(m, "RECARGA"))
            
        elif call.data == "solicitar_retiro":
            msg = bot.send_message(call.message.chat.id, "✍️ Ingresa el monto USDT a retirar:")
            bot.register_next_step_handler(msg, lambda m: procesar_solicitud_fondos(m, "RETIRO"))
            
        elif call.data == "panel_admin":
            if user_id != ADMIN_ID: 
                bot.send_message(call.message.chat.id, "❌ No tienes permisos de administrador.")
                return
            mostrar_panel_admin(call.message.chat.id)

        elif call.data.startswith("aprob_") or call.data.startswith("rech_"):
            if user_id != ADMIN_ID: return
            accion, tx_id = call.data.split("_")
            gestionar_transaccion_admin(int(tx_id), accion, call.message)
    except Exception as e:
        print(f"[BOT ERROR] Error en manejar_botones: {e}")

def procesar_solicitud_fondos(message, tipo):
    try:
        monto = float(message.text)
        if monto <= 0: raise ValueError
        
        conn = conectar_db()
        cursor = conn.cursor()
        
        if tipo == "RETIRO":
            cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = ?", (message.from_user.id,))
            res = cursor.fetchone()
            if not res or res['saldo_usdt'] < monto:
                bot.send_message(message.chat.id, f"❌ Saldo USDT insuficiente para retirar {monto} USDT.")
                conn.close()
                return

        cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto) VALUES (?, ?, ?)", (message.from_user.id, tipo, monto))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, f"✅ Solicitud de {monto} USDT enviada a revisión.")
        bot.send_message(ADMIN_ID, f"🔔 Nueva solicitud #{tipo}:\n👤 Usuario: {message.from_user.id}\n💰 Monto: {monto} USDT")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Error: Ingresa un número válido y mayor a cero.")
    except Exception as e:
        print(f"Error procesando fondos: {e}")

def mostrar_panel_admin(chat_id):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, telegram_id, tipo, monto FROM transacciones WHERE estado = 'PENDIENTE'")
        pendientes = cursor.fetchall()
        conn.close()
        
        if not pendientes:
            bot.send_message(chat_id, "✅ No hay solicitudes pendientes.")
            return
            
        for tx in pendientes:
            tx_id, u_id, tipo, monto = tx
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                       InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
            bot.send_message(chat_id, f"📥 ID Solicitud: {tx_id}\n👤 User: {u_id}\n📋 Tipo: {tipo}\n💰 Monto: {monto} USDT", reply_markup=markup)
    except Exception as e:
        print(f"Error mostrando panel: {e}")

def gestionar_transaccion_admin(tx_id, accion, message_obj):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, tipo, monto, estado FROM transacciones WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        
        if not tx or tx[3] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Esta solicitud ya fue procesada.", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            conn.close()
            return
            
        u_id, tipo, monto, _ = tx
        
        if accion == "aprob":
            if tipo == "RECARGA":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt + ? WHERE telegram_id = ?", (monto, u_id))
            elif tipo == "RETIRO":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - ? WHERE telegram_id = ?", (monto, u_id))
            cursor.execute("UPDATE transacciones SET estado = 'APROBADO' WHERE id = ?", (tx_id,))
            bot.send_message(u_id, f"🎉 Tu solicitud de {monto} USDT fue aprobada.")
            bot.edit_message_text(f"✅ #{tx_id} APROBADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
        else:
            cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = ?", (tx_id,))
            bot.send_message(u_id, f"❌ Tu solicitud de {monto} USDT fue rechazada.")
            bot.edit_message_text(f"❌ #{tx_id} RECHAZADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error gestionando transacción admin: {e}")

# ==========================================
# API FLASK PARA LA MINI APP (JUEGO)
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
    cantidad = int(datos.get('cantidad', 1))
    
    precios = {
        'maceta_grande': 50,
        'agua': 10,
        'semilla_misteriosa': 100,
        'maceta_especial': 200,
        'fertilizante': 150,
        'granja_comun': 50,      
        'granja_rara': 150,
        'granja_legendaria': 300
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

@app.route('/germinar_semilla', methods=['POST'])
def germinar_semilla():
    datos = request.json
    user_id = datos.get('id')
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = ? AND item_tipo IN ('semilla_misteriosa', 'maceta_especial', 'agua', 'fertilizante')", (user_id,))
    inv = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
    
    reqs = {'semilla_misteriosa': 1, 'maceta_especial': 1, 'agua': 2, 'fertilizante': 1}
    for item, cant_req in reqs.items():
        if inv.get(item, 0) < cant_req:
            conn.close()
            return jsonify({"error": f"Falta: {item}"}), 400
            
    for item, cant_req in reqs.items():
        cursor.execute("UPDATE inventario SET cantidad = cantidad - ? WHERE telegram_id = ? AND item_tipo = ?", (cant_req, user_id, item))
        
    rarezas = ['comun', 'raro', 'epico', 'legendario']
    pesos = [60, 25, 10, 5]
    rareza = random.choices(rarezas, weights=pesos, k=1)[0]
    
    prod_hora = {'comun': 20, 'raro': 50, 'epico': 120, 'legendario': 300}
    
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO plantas (telegram_id, rareza, produccion_hora, tiempo_inicio, estado) VALUES (?, ?, ?, ?, 'CRECIENDO')",
                   (user_id, rareza, prod_hora[rareza], ahora))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        "mensaje": "Germinación exitosa",
        "rareza": rareza,
        "produccion_hora": prod_hora[rareza]
    })

@app.route('/obtener_plantas', methods=['GET'])
def obtener_plantas():
    user_id = request.args.get('id')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, rareza, produccion_hora, tiempo_inicio FROM plantas WHERE telegram_id = ? AND estado != 'EN_VENTA'", (user_id,))
    plantas = []
    for p in cursor.fetchall():
        plantas.append({
            "id": p['id'],
            "rareza": p['rareza'],
            "produccion_hora": p['produccion_hora'],
            "tiempo_inicio": p['tiempo_inicio']
        })
    conn.close()
    return jsonify(plantas)

@app.route('/cosechar_planta', methods=['POST'])
def cosechar_planta():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT rareza, produccion_hora, tiempo_inicio, estado FROM plantas WHERE id = ? AND telegram_id = ?", (planta_id, user_id))
    planta = cursor.fetchone()
    
    if not planta or planta['estado'] == 'EN_VENTA':
        conn.close()
        return jsonify({"error": "Planta no encontrada o en venta"}), 404
        
    inicio = datetime.strptime(planta['tiempo_inicio'], '%Y-%m-%d %H:%M:%S')
    ahora = datetime.now()
    horas = (ahora - inicio).total_seconds() / 3600
    
    if horas < 1: 
         conn.close()
         return jsonify({"error": "La planta aún está creciendo"}), 400
         
    recompensa = planta['produccion_hora'] * horas
    
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan + ? WHERE telegram_id = ?", (recompensa, user_id))
    cursor.execute("DELETE FROM plantas WHERE id = ?", (planta_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"mensaje": "Cosecha exitosa", "recompensa": round(recompensa, 2)})

@app.route('/publicar_mercado', methods=['POST'])
def publicar_mercado():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    precio = float(datos.get('precio'))
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM plantas WHERE id = ? AND telegram_id = ? AND estado != 'EN_VENTA'", (planta_id, user_id))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "No posees esta planta o ya está en venta"}), 404
        
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO mercado (planta_id, vendedor_id, precio, fecha_publicacion) VALUES (?, ?, ?, ?)",
                   (planta_id, user_id, precio, ahora))
    
    cursor.execute("UPDATE plantas SET estado = 'EN_VENTA' WHERE id = ?", (planta_id,))
    
    conn.commit()
    conn.close()
    return jsonify({"mensaje": "Publicado en mercado con éxito"})

@app.route('/ver_mercado', methods=['GET'])
def ver_mercado():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id AS oferta_id, m.precio, m.vendedor_id, p.rareza, p.produccion_hora 
        FROM mercado m 
        INNER JOIN plantas p ON m.planta_id = p.id
    """)
    ofertas = []
    for o in cursor.fetchall():
        ofertas.append({
            "id": o['oferta_id'],
            "precio": o['precio'],
            "vendedor": o['vendedor_id'],
            "rareza": o['rareza'],
            "produccion_hora": o['produccion_hora']
        })
    conn.close()
    return jsonify(ofertas)

@app.route('/comprar_mercado', methods=['POST'])
def comprar_mercado():
    datos = request.json
    user_id = datos.get('id') 
    oferta_id = datos.get('oferta_id')
    
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT planta_id, precio, vendedor_id FROM mercado WHERE id = ?", (oferta_id,))
    oferta = cursor.fetchone()
    
    if not oferta:
        conn.close()
        return jsonify({"error": "La oferta ya no existe"}), 404
        
    planta_id, precio, vendedor_id = oferta
    
    if user_id == vendedor_id:
        conn.close()
        return jsonify({"error": "No puedes comprar tu propia planta"}), 400
        
    cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = ?", (user_id,))
    saldo_comprador = cursor.fetchone()['saldo_lan']
    
    if saldo_comprador < precio:
        conn.close()
        return jsonify({"error": "Saldo insuficiente"}), 400
        
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - ? WHERE telegram_id = ?", (precio, user_id))
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan + ? WHERE telegram_id = ?", (precio, vendedor_id))
    
    cursor.execute("UPDATE plantas SET telegram_id = ?, estado = 'CRECIENDO' WHERE id = ?", (user_id, planta_id))
    cursor.execute("DELETE FROM mercado WHERE id = ?", (oferta_id,))
    
    conn.commit()
    conn.close()
    return jsonify({"mensaje": "Compra realizada con éxito"})


# ==========================================
# ARRANQUE ADAPTADO PARA RENDER
# ==========================================
def correr_bot_telegram():
    print("[Bot] Escuchando comandos en Render...")
    bot.infinity_polling(timeout=20)

if __name__ == '__main__':
    inicializar_base_datos()
    
    hilo_bot = threading.Thread(target=correr_bot_telegram)
    hilo_bot.daemon = True
    hilo_bot.start()
    
    puerto = int(os.environ.get("PORT", 10000))
    print(f"🚀 Servidor FlowerLan activo en el puerto dinámico: {puerto}")
    app.run(host='0.0.0.0', port=puerto, debug=False, use_reloader=False)
