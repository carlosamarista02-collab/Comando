import threading
import psycopg2
from psycopg2.extras import RealDictCursor
import time
import ran
import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
TOKEN_TELEGRAM = '8939217389:AAHDVYsmfx8TFCbjtrZHlIfppajsPluJcQA'
URL_MINI_APP = 'https://aesthetic-chaja-a87a4e.netlify.app/'
ADMIN_ID = 6808824866

DATABASE_URL = "postgresql://postgres.rsqcsdheaibeuhjbxicn:72bGmBxf6qzb-iY@aws-1-us-west-2.pooler.supabase.com:6543/postgres"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
CORS(app)

# ==========================================
# GESTIÓN DE BASE DE DATOS
# ==========================================
def conectar_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"[DB ERROR] Conexión fallida: {e}")
        return None

def inicializar_base_datos():
    conn = conectar_db()
    if not conn: return
    cursor = conn.cursor()
    
    # Tabla Usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            telegram_id BIGINT PRIMARY KEY,
            nombre TEXT,
            username TEXT,
            saldo_usdt NUMERIC DEFAULT 0.0,
            saldo_lan NUMERIC DEFAULT 1250.0,
            tierras_compradas JSONB DEFAULT '[]'::jsonb
        )
    ''')

    # Tabla Inventario
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            telegram_id BIGINT,
            item_tipo TEXT, 
            cantidad INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, item_tipo)
        )
    ''')

    # Tabla Plantas Activas (en tierra)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plantas_activas (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            terreno_id TEXT,
            nombre_planta TEXT,
            icono TEXT,
            rareza TEXT, 
            produccion_hora NUMERIC,
            tiempo_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duracion_horas INTEGER,
            estado TEXT DEFAULT 'CRECIENDO',
            recursos JSONB DEFAULT '{}'::jsonb
        )
    ''')

    # Tabla Mercado Global P2P
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mercado_global (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            nombre_item TEXT,
            icono TEXT,
            tipo_item TEXT,
            rareza TEXT,
            produccion_hora NUMERIC DEFAULT 0,
            duracion_horas INTEGER DEFAULT 0,
            precio NUMERIC,
            cantidad INTEGER DEFAULT 1,
            vendedor_nombre TEXT,
            fecha_publicacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            estado TEXT DEFAULT 'ACTIVA'
        )
    ''')

    # Tabla Transacciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            tipo TEXT,
            monto NUMERIC,
            wallet_address TEXT,
            estado TEXT DEFAULT 'PENDIENTE',
            fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    cursor.close()
    conn.close()
    print("[DB] Base de datos inicializada correctamente.")

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
        if not conn: return
        cursor = conn.cursor()
        
        cursor.execute("SELECT telegram_id FROM usuarios WHERE telegram_id = %s", (user_id,))
        existe = cursor.fetchone()

        if not existe:
            cursor.execute(
                "INSERT INTO usuarios (telegram_id, nombre, username, saldo_usdt, saldo_lan) VALUES (%s, %s, %s, 0.0, 1250.0)",
                (user_id, first_name, username)
            )
            cursor.execute("""
                INSERT INTO inventario (telegram_id, item_tipo, cantidad) VALUES 
                (%s, 'maceta_grande', 2), (%s, 'agua', 5)
                ON CONFLICT (telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
            """, (user_id, user_id))
            conn.commit()
        
        cursor.close()
        conn.close()

        markup = InlineKeyboardMarkup(row_width=2)
        boton_jugar = InlineKeyboardButton(text="🚀 Jugar FlowerLan", web_app=telebot.types.WebAppInfo(url=URL_MINI_APP))
        
        if user_id == ADMIN_ID:
            btn_admin = InlineKeyboardButton(text="⚙️ Panel Admin", callback_data="panel_admin")
            markup.add(boton_jugar, btn_admin)
        else:
            markup.add(boton_jugar)

        bot.send_message(message.chat.id, f"¡Hola {first_name}! Bienvenido a FlowerLan 🌻\nToca el botón para entrar a tu granja.", reply_markup=markup)
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
            partes = call.data.split("_")
            accion = partes[0]
            tx_id = int(partes[1])
            gestionar_transaccion_admin(tx_id, accion, call.message)
    except Exception as e:
        print(f"[BOT ERROR] Error en manejar_botones: {e}")

def mostrar_panel_admin(chat_id):
    try:
        conn = conectar_db()
        if not conn: return
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, telegram_id, tipo, monto, wallet_address FROM transacciones WHERE estado = 'PENDIENTE' ORDER BY id DESC")
        pendientes = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not pendientes:
            markup_vacio = InlineKeyboardMarkup()
            markup_vacio.add(InlineKeyboardButton("Actualizar", callback_data="panel_admin"))
            bot.send_message(chat_id, "⚙️ **Panel de Administración** ⚙️\n\n✅ Todo al día. No hay solicitudes pendientes.", parse_mode="Markdown", reply_markup=markup_vacio)
            return
            
        for tx in pendientes:
            tx_id = tx['id']
            u_id = tx['telegram_id']
            tipo = tx['tipo']
            monto = tx['monto']
            wallet = tx.get('wallet_address', 'N/A')
            
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                       InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
            
            msg_text = f"📥 **ID Transacción:** #{tx_id}\n👤 **User ID:** `{u_id}`\n📋 **Tipo:** {tipo}\n💰 **Monto:** {monto} USDT"
            if tipo == 'RETIRO':
                msg_text += f"\n🏦 **Wallet:** `{wallet}`"
                
            bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error mostrando panel: {e}")

def gestionar_transaccion_admin(tx_id, accion, message_obj):
    try:
        conn = conectar_db()
        if not conn: return
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM transacciones WHERE id = %s FOR UPDATE", (tx_id,))
        tx = cursor.fetchone()
        
        if not tx or tx['estado'] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Esta solicitud ya fue procesada.", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            cursor.close(); conn.close(); return
            
        u_id = tx['telegram_id']
        tipo = tx['tipo']
        monto = float(tx['monto'])
        
        if accion == "aprob":
            if tipo == "RECARGA":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt + %s WHERE telegram_id = %s", (monto, u_id))
            elif tipo == "RETIRO":
                cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = %s", (u_id,))
                user_data = cursor.fetchone()
                if user_data and float(user_data['saldo_usdt']) >= monto:
                    cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - %s WHERE telegram_id = %s", (monto, u_id))
                else:
                    bot.send_message(message_obj.chat.id, f"❌ Error: El usuario {u_id} ya no tiene saldo suficiente.")
                    cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO_SALDO' WHERE id = %s", (tx_id,))
                    conn.commit(); cursor.close(); conn.close(); return

            cursor.execute("UPDATE transacciones SET estado = 'APROBADO' WHERE id = %s", (tx_id,))
            conn.commit()
            
            try: bot.send_message(u_id, f"🎉 ¡Tu solicitud de {monto} USDT ({tipo}) ha sido **APROBADA**!", parse_mode="Markdown")
            except: pass
            
            bot.edit_message_text(f"✅ #{tx_id} APROBADA CORRECTAMENTE", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            
        else:
            cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = %s", (tx_id,))
            conn.commit()
            
            try: bot.send_message(u_id, f"❌ Tu solicitud de {monto} USDT ha sido rechazada.")
            except: pass
            
            bot.edit_message_text(f"❌ #{tx_id} RECHAZADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            
        cursor.close(); conn.close()
    except Exception as e:
        print(f"Error gestionando transacción: {e}")

# ==========================================
# API FLASK - ENDPOINTS PÚBLICOS
# ==========================================
@app.after_request
def evitar_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

# ---------- PERFIL ----------
@app.route('/obtener_perfil', methods=['GET'])
def obtener_perfil():
    user_id = request.args.get('id')
    if not user_id: return jsonify({"error": "Falta ID"}), 400
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT saldo_usdt, saldo_lan FROM usuarios WHERE telegram_id = %s", (user_id,))
    data = cursor.fetchone()
    cursor.close(); conn.close()

    if data:
        return jsonify({"usdt": float(data[0]), "lan": float(data[1])})
    return jsonify({"error": "Usuario no registrado"}), 404

# ---------- INVENTARIO ----------
@app.route('/obtener_inventario', methods=['GET'])
def obtener_inventario():
    user_id = request.args.get('id')
    conn = conectar_db()
    if not conn: return jsonify({}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = %s AND cantidad > 0", (user_id,))
    items = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
    cursor.close(); conn.close()
    return jsonify(items)

# ---------- TIERRAS ----------
@app.route('/obtener_tierras', methods=['GET'])
def obtener_tierras():
    user_id = request.args.get('id')
    conn = conectar_db()
    if not conn: return jsonify({"slots_totales": 0, "tierras": []}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT tierras_compradas FROM usuarios WHERE telegram_id = %s", (user_id,))
    data = cursor.fetchone()
    if not data: 
        cursor.close(); conn.close()
        return jsonify({"slots_totales": 4, "tierras": []}), 200
        
    tierras = data['tierras_compradas'] or []
    mapa_slots = {'comun': 4, 'rara': 8, 'legendaria': 12}
    slots_extra = sum(mapa_slots.get(t, 0) for t in tierras)

    cursor.close(); conn.close()
    return jsonify({"slots_totales": 4 + slots_extra, "tierras": tierras})

# ---------- COMPRAR ITEMS ----------
@app.route('/comprar_item', methods=['POST'])
def comprar_item():
    datos = request.json
    user_id = datos.get('id')
    item_key = datos.get('item')
    try:
        cantidad = int(datos.get('cantidad', 1))
        if cantidad <= 0: raise ValueError
    except:
        return jsonify({"error": "Cantidad inválida"}), 400
        
    precios = {
        'maceta_grande': 20, 'agua': 5, 'semilla_misteriosa': 100,
        'maceta_especial': 50, 'fertilizante_pro': 75,
        'tierra_comun': 50, 'tierra_rara': 150, 'tierra_legendaria': 300
    }

    if item_key not in precios:
        return jsonify({"error": "Item no válido"}), 400
        
    costo_total = precios[item_key] * cantidad

    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = %s FOR UPDATE", (user_id,))
    user = cursor.fetchone()

    if not user or float(user['saldo_lan']) < costo_total:
        cursor.close(); conn.close()
        return jsonify({"error": "Saldo $LAN insuficiente"}), 400
        
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - %s WHERE telegram_id = %s", (costo_total, user_id))

    if 'tierra' in item_key:
        tipo_tierra_map = {'tierra_comun': 'comun', 'tierra_rara': 'rara', 'tierra_legendaria': 'legendaria'}
        tipo_db = tipo_tierra_map.get(item_key)
        if tipo_db:
            cursor.execute("""
                UPDATE usuarios 
                SET tierras_compradas = COALESCE(tierras_compradas, '[]'::jsonb) || %s::jsonb
                WHERE telegram_id = %s
            """, (json.dumps([tipo_db]), user_id))
    else:
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, %s) 
            ON CONFLICT(telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
        """, (user_id, item_key, cantidad))

    conn.commit()
    nuevo_saldo = float(user['saldo_lan']) - costo_total
    cursor.close(); conn.close()

    return jsonify({"mensaje": "Compra exitosa", "nuevo_saldo": nuevo_saldo})

# ---------- INTERCAMBIO ----------
@app.route('/api/intercambio', methods=['POST'])
def realizar_intercambio():
    datos = request.json
    user_id = datos.get('id')
    monto = float(datos.get('monto', 0))
    direccion = datos.get('direccion', 'usdt_to_lan')
    
    if monto <= 0:
        return jsonify({"error": "Monto inválido"}), 400

    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT saldo_usdt, saldo_lan FROM usuarios WHERE telegram_id = %s FOR UPDATE", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({"error": "Usuario no encontrado"}), 404
            
        saldo_usdt = float(user['saldo_usdt'])
        saldo_lan = float(user['saldo_lan'])
        
        if direccion == 'usdt_to_lan':
            if saldo_usdt < monto:
                return jsonify({"error": "Saldo USDT insuficiente"}), 400
            nuevo_usdt = saldo_usdt - monto
            nuevo_lan = saldo_lan + monto
        elif direccion == 'lan_to_usdt':
            if saldo_lan < monto:
                return jsonify({"error": "Saldo LAN insuficiente"}), 400
            nuevo_lan = saldo_lan - monto
            nuevo_usdt = saldo_usdt + monto
        else:
            return jsonify({"error": "Dirección inválida"}), 400
            
        cursor.execute("UPDATE usuarios SET saldo_usdt = %s, saldo_lan = %s WHERE telegram_id = %s", (nuevo_usdt, nuevo_lan, user_id))
        conn.commit()
        
        try:
            bot.send_message(ADMIN_ID, f"💱 <b>Intercambio Realizado</b>\n👤 User: {user_id}\n💰 Monto: {monto}\n🔄 Dirección: {direccion}", parse_mode="HTML")
        except: pass
        
        return jsonify({"success": True, "nuevo_usdt": nuevo_usdt, "nuevo_lan": nuevo_lan})
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- RECARGAS Y RETIROS ----------
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
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor()

    fecha_actual = datetime.now()
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, fecha_solicitud) VALUES (%s, %s, %s, %s) RETURNING id", 
                   (user_id, "RECARGA", monto, fecha_actual))
    tx_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close(); conn.close()

    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVA RECARGA (WEB)**\n\n🆔 ID: #{tx_id}\nUser: `{user_id}`\n💰 Monto: {monto} USDT", parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error enviando notif admin: {e}")
        
    return jsonify({"mensaje": "Solicitud enviada", "tx_id": tx_id})

@app.route('/solicitar_retiro_web', methods=['POST'])
def solicitar_retiro_web():
    datos = request.json
    user_id = datos.get('id')
    monto_str = str(datos.get('monto')).replace(',', '.')
    wallet = datos.get('walletAddress', 'No especificada')
    try:
        monto = float(monto_str)
        if monto <= 0: raise ValueError
    except:
        return jsonify({"error": "Monto inválido"}), 400
        
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = %s", (user_id,))
    user = cursor.fetchone()

    if not user or float(user['saldo_usdt']) < monto:
        cursor.close(); conn.close()
        return jsonify({"error": "Saldo USDT insuficiente"}), 400

    fecha_actual = datetime.now()
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, wallet_address, fecha_solicitud) VALUES (%s, %s, %s, %s, %s) RETURNING id", 
                   (user_id, "RETIRO", monto, wallet, fecha_actual))
    tx_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close(); conn.close()

    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"**NUEVO RETIRO (WEB)**\n\n🆔 ID: #{tx_id}\n👤 User: `{user_id}`\nMonto: {monto} USDT\nWallet: `{wallet}`", parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error enviando notif admin: {e}")
        
    return jsonify({"mensaje": "Solicitud de retiro enviada", "tx_id": tx_id})

# ==========================================
# NUEVOS ENDPOINTS: PLANTAS, COSECHA, MERCADO
# ==========================================

# ---------- OBTENER PLANTAS ACTIVAS ----------
@app.route('/obtener_plantas', methods=['GET'])
def obtener_plantas():
    user_id = request.args.get('id')
    conn = conectar_db()
    if not conn: return jsonify([]), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT id, terreno_id, nombre_planta, icono, rareza, produccion_hora, 
               tiempo_inicio, duracion_horas, estado, recursos
        FROM plantas_activas 
        WHERE telegram_id = %s
        ORDER BY tiempo_inicio DESC
    """, (user_id,))
    plantas = cursor.fetchall()
    cursor.close(); conn.close()
    
    resultado = []
    for p in plantas:
        resultado.append({
            'id': p['id'],
            'terreno_id': p['terreno_id'],
            'nombre': p['nombre_planta'],
            'icono': p['icono'],
            'rareza': p['rareza'],
            'produccion_hora': float(p['produccion_hora']),
            'tiempo_inicio': p['tiempo_inicio'].isoformat() if p['tiempo_inicio'] else None,
            'duracion_horas': p['duracion_horas'],
            'estado': p['estado'],
            'recursos': p['recursos'] or {}
        })
    return jsonify(resultado)

# ---------- PLANTAR PLANTA ----------
@app.route('/plantar_planta', methods=['POST'])
def plantar_planta():
    datos = request.json
    user_id = datos.get('id')
    terreno_id = datos.get('terreno_id')
    nombre_planta = datos.get('nombre')
    icono = datos.get('icono', '🌱')
    rareza = datos.get('rareza', 'comun')
    prod_hora = float(datos.get('produccion_hora', 0))
    duracion_horas = int(datos.get('duracion_horas', 8))
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Verificar recursos: maceta y agua
        cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = %s AND item_tipo IN ('maceta_grande', 'agua') FOR UPDATE", (user_id,))
        items = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
        
        if items.get('maceta_grande', 0) < 1:
            return jsonify({"error": "Falta Maceta"}), 400
        if items.get('agua', 0) < 2:
            return jsonify({"error": "Falta Agua"}), 400
        
        # Verificar que la planta existe en inventario
        cursor.execute("SELECT cantidad FROM inventario WHERE telegram_id = %s AND item_tipo = %s FOR UPDATE", (user_id, nombre_planta))
        planta_inv = cursor.fetchone()
        if not planta_inv or planta_inv['cantidad'] < 1:
            return jsonify({"error": "No tienes esa planta en el almacén"}), 400
        
        # Consumir recursos
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 1 WHERE telegram_id = %s AND item_tipo = 'maceta_grande'", (user_id,))
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 2 WHERE telegram_id = %s AND item_tipo = 'agua'", (user_id,))
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 1 WHERE telegram_id = %s AND item_tipo = %s", (user_id, nombre_planta))
        
        # Limpiar inventario con cantidad 0
        cursor.execute("DELETE FROM inventario WHERE telegram_id = %s AND cantidad <= 0", (user_id,))
        
        # Insertar planta activa
        cursor.execute("""
            INSERT INTO plantas_activas (telegram_id, terreno_id, nombre_planta, icono, rareza, produccion_hora, duracion_horas, estado, recursos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'CRECIENDO', %s)
            RETURNING id
        """, (user_id, terreno_id, nombre_planta, icono, rareza, prod_hora, duracion_horas, json.dumps({'maceta': 1, 'agua': 2})))
        
        nueva_id = cursor.fetchone()['id']
        conn.commit()
        
        return jsonify({"success": True, "planta_id": nueva_id, "mensaje": "Planta sembrada"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- GERMINAR SEMILLA ----------
@app.route('/germinar_semilla', methods=['POST'])
def germinar_semilla():
    datos = request.json
    user_id = datos.get('id')
    terreno_id = datos.get('terreno_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Verificar recursos especiales
        cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = %s AND item_tipo IN ('semilla_misteriosa', 'maceta_especial', 'agua', 'fertilizante_pro') FOR UPDATE", (user_id,))
        items = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
        
        if items.get('semilla_misteriosa', 0) < 1:
            return jsonify({"error": "Falta Semilla Misteriosa"}), 400
        if items.get('maceta_especial', 0) < 1:
            return jsonify({"error": "Falta Maceta Especial"}), 400
        if items.get('agua', 0) < 2:
            return jsonify({"error": "Falta Agua"}), 400
        if items.get('fertilizante_pro', 0) < 1:
            return jsonify({"error": "Falta Fertilizante"}), 400
        
        # Consumir recursos
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 1 WHERE telegram_id = %s AND item_tipo = 'semilla_misteriosa'", (user_id,))
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 1 WHERE telegram_id = %s AND item_tipo = 'maceta_especial'", (user_id,))
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 2 WHERE telegram_id = %s AND item_tipo = 'agua'", (user_id,))
        cursor.execute("UPDATE inventario SET cantidad = cantidad - 1 WHERE telegram_id = %s AND item_tipo = 'fertilizante_pro'", (user_id,))
        cursor.execute("DELETE FROM inventario WHERE telegram_id = %s AND cantidad <= 0", (user_id,))
        
        # Crear planta en estado GERMINANDO (72 horas)
        cursor.execute("""
            INSERT INTO plantas_activas (telegram_id, terreno_id, nombre_planta, icono, rareza, produccion_hora, duracion_horas, estado, recursos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'GERMINANDO', %s)
            RETURNING id
        """, (user_id, terreno_id, 'Semilla Misteriosa', '🌰', 'comun', 0, 72, json.dumps({'maceta_especial': 1, 'agua': 2, 'fertilizante': 1})))
        
        nueva_id = cursor.fetchone()['id']
        conn.commit()
        
        return jsonify({"success": True, "planta_id": nueva_id, "mensaje": "Germinación iniciada"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- FINALIZAR GERMINACIÓN ----------
@app.route('/finalizar_germinacion', methods=['POST'])
def finalizar_germinacion():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM plantas_activas WHERE id = %s AND telegram_id = %s FOR UPDATE", (planta_id, user_id))
        planta = cursor.fetchone()
        
        if not planta or planta['estado'] != 'GERMINANDO':
            return jsonify({"error": "Planta no válida o no está germinando"}), 400
        
        # Verificar tiempo transcurrido
        tiempo_inicio = planta['tiempo_inicio']
        ahora = datetime.now()
        horas_transcurridas = (ahora - tiempo_inicio).total_seconds() / 3600
        
        if horas_transcurridas < planta['duracion_horas']:
            return jsonify({"error": "La germinación aún no termina"}), 400
        
        # Generar planta aleatoria
        rand = random.random() * 100
        if rand < 40:
            rareza = 'comun'
            min_h, max_h = 24, 75
        elif rand < 70:
            rareza = 'raro'
            min_h, max_h = 76, 150
        elif rand < 90:
            rareza = 'epico'
            min_h, max_h = 152, 250
        else:
            rareza = 'legendario'
            min_h, max_h = 250, 450
        
        # Base de datos de plantas
        prefijos = ["Silvestre", "Real", "Ancestral", "Místico", "Dorado", "Sombrío", "Celestial", "Eterno", "Brillante", "Oscuro"]
        tipos_comun = ["Brote", "Helecho", "Orquídea", "Enredadera", "Musgo", "Liana", "Raíz", "Flor", "Hongo", "Árbol"]
        iconos = {
            'comun': ['🌿','🍀','🌱','🌾','🌵','🌴','🌳','🌲','🌷','🌹'],
            'raro': ['🍄','🌺','🌻','🌼','🪷','🪻','🥀','🌸','🌹','🌺'],
            'epico': ['🌵','🌴','🌳','🌲','🌿','🍀','🌱','🌾','🍄','🌺'],
            'legendario': ['🌲','🌳','🌴','🌵','🌾','🌱','🍀','🌿','🌺','🌻']
        }
        
        idx = random.randint(0, 9)
        nombre_planta = f"{prefijos[idx]} {tipos_comun[idx]} {rareza.capitalize()}"
        icono = iconos[rareza][idx]
        duracion = random.randint(min_h, max_h)
        prod_hora = duracion
        
        # Eliminar la semilla germinando
        cursor.execute("DELETE FROM plantas_activas WHERE id = %s", (planta_id,))
        
        # Agregar la nueva planta al inventario
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, 1) 
            ON CONFLICT (telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + 1
        """, (user_id, nombre_planta))
        
        conn.commit()
        
        return jsonify({
            "success": True,
            "planta": {
                "nombre": nombre_planta,
                "icono": icono,
                "rareza": rareza,
                "produccion_hora": prod_hora,
                "duracion_horas": duracion
            }
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- COSECHAR PLANTA ----------
@app.route('/cosechar_planta', methods=['POST'])
def cosechar_planta():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM plantas_activas WHERE id = %s AND telegram_id = %s FOR UPDATE", (planta_id, user_id))
        planta = cursor.fetchone()
        
        if not planta or planta['estado'] != 'CRECIENDO':
            return jsonify({"error": "Planta no válida o no está lista"}), 400
        
        # Verificar tiempo transcurrido
        tiempo_inicio = planta['tiempo_inicio']
        ahora = datetime.now()
        horas_transcurridas = (ahora - tiempo_inicio).total_seconds() / 3600
        
        if horas_transcurridas < planta['duracion_horas']:
            return jsonify({"error": "La planta aún no está lista para cosechar"}), 400
        
        # Calcular $LAN generados
        lan_generado = float(planta['produccion_hora']) * planta['duracion_horas']
        
        # Sumar $LAN al usuario
        cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan + %s WHERE telegram_id = %s", (lan_generado, user_id))
        
        # Devolver planta al inventario
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, 1) 
            ON CONFLICT (telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + 1
        """, (user_id, planta['nombre_planta']))
        
        # Eliminar planta activa
        cursor.execute("DELETE FROM plantas_activas WHERE id = %s", (planta_id,))
        
        # Obtener nuevo saldo
        cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = %s", (user_id,))
        nuevo_saldo = float(cursor.fetchone()['saldo_lan'])
        
        conn.commit()
        
        return jsonify({
            "success": True,
            "lan_generado": lan_generado,
            "nuevo_saldo": nuevo_saldo,
            "nombre_planta": planta['nombre_planta']
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- ELIMINAR PLANTA (cancelar) ----------
@app.route('/eliminar_planta', methods=['POST'])
def eliminar_planta():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM plantas_activas WHERE id = %s AND telegram_id = %s", (planta_id, user_id))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ==========================================
# MERCADO GLOBAL P2P
# ==========================================

# ---------- OBTENER MERCADO ----------
@app.route('/obtener_mercado', methods=['GET'])
def obtener_mercado():
    conn = conectar_db()
    if not conn: return jsonify([]), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT id, telegram_id, nombre_item, icono, tipo_item, rareza, 
               produccion_hora, duracion_horas, precio, cantidad, vendedor_nombre, fecha_publicacion
        FROM mercado_global 
        WHERE estado = 'ACTIVA'
        ORDER BY fecha_publicacion DESC
        LIMIT 100
    """)
    items = cursor.fetchall()
    cursor.close(); conn.close()
    
    resultado = []
    for item in items:
        resultado.append({
            'id': item['id'],
            'telegram_id': item['telegram_id'],
            'nombre': item['nombre_item'],
            'icono': item['icono'],
            'tipo': item['tipo_item'],
            'rareza': item['rareza'],
            'produccion_hora': float(item['produccion_hora'] or 0),
            'duracion_horas': item['duracion_horas'] or 0,
            'precio': float(item['precio']),
            'cantidad': item['cantidad'],
            'vendedor': item['vendedor_nombre'],
            'fecha': item['fecha_publicacion'].isoformat() if item['fecha_publicacion'] else None
        })
    return jsonify(resultado)

# ---------- PUBLICAR VENTA ----------
@app.route('/vender_p2p', methods=['POST'])
def vender_p2p():
    datos = request.json
    user_id = datos.get('id')
    nombre_item = datos.get('nombre')
    icono = datos.get('icono', '🌱')
    tipo_item = datos.get('tipo', 'plant')
    rareza = datos.get('rareza', 'comun')
    prod_hora = float(datos.get('produccion_hora', 0))
    duracion_horas = int(datos.get('duracion_horas', 0))
    precio = float(datos.get('precio', 0))
    cantidad = int(datos.get('cantidad', 1))
    vendedor_nombre = datos.get('vendedor_nombre', '@Usuario')
    
    if precio <= 0 or cantidad <= 0:
        return jsonify({"error": "Precio o cantidad inválidos"}), 400
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Verificar que el usuario tiene el item
        cursor.execute("SELECT cantidad FROM inventario WHERE telegram_id = %s AND item_tipo = %s FOR UPDATE", (user_id, nombre_item))
        inv = cursor.fetchone()
        
        if not inv or inv['cantidad'] < cantidad:
            return jsonify({"error": "No tienes suficientes items"}), 400
        
        # Descontar del inventario
        cursor.execute("UPDATE inventario SET cantidad = cantidad - %s WHERE telegram_id = %s AND item_tipo = %s", (cantidad, user_id, nombre_item))
        cursor.execute("DELETE FROM inventario WHERE telegram_id = %s AND cantidad <= 0", (user_id,))
        
        # Publicar en mercado
        cursor.execute("""
            INSERT INTO mercado_global (telegram_id, nombre_item, icono, tipo_item, rareza, produccion_hora, duracion_horas, precio, cantidad, vendedor_nombre)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, nombre_item, icono, tipo_item, rareza, prod_hora, duracion_horas, precio, cantidad, vendedor_nombre))
        
        venta_id = cursor.fetchone()['id']
        conn.commit()
        
        return jsonify({"success": True, "venta_id": venta_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- COMPRAR DEL MERCADO ----------
@app.route('/comprar_mercado', methods=['POST'])
def comprar_mercado():
    datos = request.json
    user_id = datos.get('id')
    venta_id = datos.get('venta_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Obtener venta
        cursor.execute("SELECT * FROM mercado_global WHERE id = %s AND estado = 'ACTIVA' FOR UPDATE", (venta_id,))
        venta = cursor.fetchone()
        
        if not venta:
            return jsonify({"error": "Venta no disponible"}), 400
        
        if venta['telegram_id'] == int(user_id):
            return jsonify({"error": "No puedes comprar tu propia venta"}), 400
        
        precio_total = float(venta['precio']) * venta['cantidad']
        
        # Verificar saldo del comprador
        cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = %s FOR UPDATE", (user_id,))
        comprador = cursor.fetchone()
        
        if not comprador or float(comprador['saldo_lan']) < precio_total:
            return jsonify({"error": "Saldo $LAN insuficiente"}), 400
        
        # Descontar al comprador
        cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - %s WHERE telegram_id = %s", (precio_total, user_id))
        
        # Sumar al vendedor
        cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan + %s WHERE telegram_id = %s", (precio_total, venta['telegram_id']))
        
        # Agregar item al inventario del comprador
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
        """, (user_id, venta['nombre_item'], venta['cantidad']))
        
        # Marcar venta como completada
        cursor.execute("UPDATE mercado_global SET estado = 'VENDIDA' WHERE id = %s", (venta_id,))
        
        # Obtener nuevo saldo
        cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = %s", (user_id,))
        nuevo_saldo = float(cursor.fetchone()['saldo_lan'])
        
        conn.commit()
        
        return jsonify({
            "success": True,
            "nuevo_saldo": nuevo_saldo,
            "item": venta['nombre_item'],
            "cantidad": venta['cantidad']
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ---------- CANCELAR VENTA ----------
@app.route('/cancelar_venta', methods=['POST'])
def cancelar_venta():
    datos = request.json
    user_id = datos.get('id')
    venta_id = datos.get('venta_id')
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM mercado_global WHERE id = %s AND telegram_id = %s AND estado = 'ACTIVA' FOR UPDATE", (venta_id, user_id))
        venta = cursor.fetchone()
        
        if not venta:
            return jsonify({"error": "Venta no encontrada o no te pertenece"}), 400
        
        # Devolver items al inventario
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
        """, (user_id, venta['nombre_item'], venta['cantidad']))
        
        # Marcar como cancelada
        cursor.execute("UPDATE mercado_global SET estado = 'CANCELADA' WHERE id = %s", (venta_id,))
        
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close(); conn.close()

# ==========================================
# ARRANQUE
# ==========================================
def correr_bot_telegram():
    print("[Bot] Iniciando polling...")
    bot.infinity_polling(timeout=20)

if __name__ == '__main__':
    inicializar_base_datos()
    hilo_bot = threading.Thread(target=correr_bot_telegram)
    hilo_bot.daemon = True
    hilo_bot.start()
    
    puerto = int(os.environ.get("PORT", 10000))
    print(f"Servidor FlowerLan activo en puerto: {puerto}")
    app.run(host='0.0.0.0', port=puerto, debug=False, use_reloader=False)
