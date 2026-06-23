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

        markup = InlineKeyboardMarkup(row_width=1)
        boton_jugar = InlineKeyboardButton(text="🚀 Jugar FlowerLan", web_app=telebot.types.WebAppInfo(url=URL_MINI_APP))
        markup.add(boton_jugar)
        
        if user_id == ADMIN_ID:
            btn_admin = InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="panel_admin")
            markup.add(btn_admin)

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
            bot.send_message(chat_id, "✅ No hay solicitudes pendientes.")
            return
            
        bot.send_message(chat_id, f"📊 **Solicitudes pendientes encontradas ({len(pendientes)}):**")
        
        for tx in pendientes:
            tx_id = tx['id']
            u_id = tx['telegram_id']
            tipo = tx['tipo']
            monto = tx['monto']
            
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                       InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
            bot.send_message(chat_id, f"📥 **ID:** #{tx_id}\n👤 **User:** `{u_id}`\n📋 **Tipo:** {tipo}\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error mostrando panel: {e}")
        bot.send_message(chat_id, "❌ Error interno al leer las transacciones.")

def gestionar_transaccion_admin(tx_id, accion, message_obj):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id, tipo, monto, estado FROM transacciones WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        
        if not tx or tx['estado'] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Ya procesada o no existe.", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
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
            bot.edit_message_text(f"✅ #{tx_id} APROBADA ({monto} USDT)", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
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
    return jsonify({"mensaje": "Germinación exitosa", "rareza": rareza, "produccion_hora": prod_hora[rareza]})

@app.route('/obtener_plantas', methods=['GET'])
def obtener_plantas():
    user_id = request.args.get('id')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, rareza, produccion_hora, tiempo_inicio FROM plantas WHERE telegram_id = ? AND estado != 'EN_VENTA'", (user_id,))
    plantas = [{"id": p['id'], "rareza": p['rareza'], "produccion_hora": p['produccion_hora'], "tiempo_inicio": p['tiempo_inicio']} for p in cursor.fetchall()]
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
        return jsonify({"error": "Planta no encontrada"}), 404
        
    inicio = datetime.strptime(planta['tiempo_inicio'], '%Y-%m-%d %H:%M:%S')
    horas = (datetime.now() - inicio).total_seconds() / 3600
    
    if horas < 1: 
         conn.close()
         return jsonify({"error": "La planta aún está creciendo"}), 400
         
    horas_a_cosechar = min(horas, 24) 
    recompensa = planta['produccion_hora'] * horas_a_cosechar
    
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
        return jsonify({"error": "No posees esta planta"}), 404
        
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("INSERT INTO mercado (planta_id, vendedor_id, precio, fecha_publicacion) VALUES (?, ?, ?, ?)", (planta_id, user_id, precio, ahora))
    cursor.execute("UPDATE plantas SET estado = 'EN_VENTA' WHERE id = ?", (planta_id,))
    conn.commit()
    conn.close()
    return jsonify({"mensaje": "Publicado en mercado"})

@app.route('/ver_mercado', methods=['GET'])
def ver_mercado():
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT m.id AS oferta_id, m.precio, m.vendedor_id, p.rareza, p.produccion_hora FROM mercado m INNER JOIN plantas p ON m.planta_id = p.id")
    ofertas = [{"id": o['oferta_id'], "precio": o['precio'], "vendedor": o['vendedor_id'], "rareza": o['rareza'], "produccion_hora": o['produccion_hora']} for o in cursor.fetchall()]
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
        
    planta_id, precio, vendedor_id = oferta['planta_id'], oferta['precio'], oferta['vendedor_id']
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
    return jsonify({"mensaje": "Compra realizada"})

@app.route('/intercambiar', methods=['POST'])
def intercambiar():
    datos = request.json
    user_id = datos.get('id')
    monto = float(datos.get('monto'))
    tipo = datos.get('tipo') 
    
    if monto <= 0: return jsonify({"error": "Monto inválido"}), 400

    conn = conectar_db()
    cursor = conn.cursor()
    
    if tipo == 'USDT_TO_LAN':
        cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = ?", (user_id,))
        saldo = cursor.fetchone()
        if not saldo or saldo['saldo_usdt'] < monto:
            conn.close()
            return jsonify({"error": "Saldo USDT insuficiente"}), 400
        cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - ?, saldo_lan = saldo_lan + ? WHERE telegram_id = ?", (monto, monto, user_id))
    elif tipo == 'LAN_TO_USDT':
        cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = ?", (user_id,))
        saldo = cursor.fetchone()
        if not saldo or saldo['saldo_lan'] < monto:
            conn.close()
            return jsonify({"error": "Saldo LAN insuficiente"}), 400
        cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - ?, saldo_usdt = saldo_usdt + ? WHERE telegram_id = ?", (monto, monto, user_id))
    else:
        conn.close()
        return jsonify({"error": "Tipo inválido"}), 400
        
    conn.commit()
    conn.close()
    return jsonify({"mensaje": "Intercambio exitoso"})

# ======================================================
# RUTAS DE RECARGA Y RETIRO DESDE WEB (CON BOTONES INMEDIATOS)
# ======================================================
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
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, fecha_solicitud) VALUES (?, ?, ?, ?)", (user_id, "RECARGA", monto, fecha_actual))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVA RECARGA PENDIENTE (DESDE WEB)**\n\n📥 **ID:** #{tx_id}\n👤 **Usuario:** `{user_id}`\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except: pass
        
    return jsonify({"mensaje": "Solicitud de recarga enviada. Espera la aprobación del admin."})

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
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, fecha_solicitud) VALUES (?, ?, ?, ?)", (user_id, "RETIRO", monto, fecha_actual))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVO RETIRO PENDIENTE (DESDE WEB)**\n\n📥 **ID:** #{tx_id}\n👤 **Usuario:** `{user_id}`\n💰 **Monto:** {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except: pass
        
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
