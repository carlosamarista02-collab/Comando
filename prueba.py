import threading
import psycopg2
from psycopg2.extras import RealDictCursor
import time
import random
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
TOKEN_TELEGRAM = '8939217389:AAHDVYsmfx8TFCbjtrZHlIfppajsPluJcQA'
URL_MINI_APP = 'https://lucent-moonbeam-09dd4d.netlify.app/' 
ADMIN_ID = 6808824866 

# URL definitiva usando el Transaction Pooler (IPv4 compatible con Render)
DATABASE_URL = "postgresql://postgres.rsqcsdheaibeuhjbxicn:72bGmBxf6qzb-iY@aws-1-us-west-2.pooler.supabase.com:6543/postgres"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
CORS(app)

# ==========================================
# GESTIÓN DE BASE DE DATOS (POSTGRESQL)
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
            tierras_compradas JSONB DEFAULT '[]'::jsonb -- Guarda IDs de tierras extra compradas
        )
    ''')
    
    # Tabla Inventario (Items consumibles y plantas base)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            telegram_id BIGINT,
            item_tipo TEXT, 
            cantidad INTEGER DEFAULT 0,
            PRIMARY KEY (telegram_id, item_tipo)
        )
    ''')
    
    # Tabla Plantas Activas (En crecimiento)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS plantas_activas (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            nombre_planta TEXT,
            rareza TEXT, 
            produccion_hora NUMERIC,
            tiempo_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duracion_horas INTEGER,
            estado TEXT DEFAULT 'CRECIENDO',
            recursos JSONB -- Guarda maceta/agua usada
        )
    ''')
    
    # Tabla Mercado P2P
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mercado (
            id SERIAL PRIMARY KEY,
            vendedor_id BIGINT,
            nombre_item TEXT,
            icono TEXT,
            rareza TEXT,
            precio NUMERIC,
            produccion_hora NUMERIC,
            fecha_publicacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla Transacciones (Recargas/Retiros)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transacciones (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            tipo TEXT, -- 'RECARGA' o 'RETIRO'
            monto NUMERIC,
            wallet_address TEXT, -- Para retiros
            estado TEXT DEFAULT 'PENDIENTE', -- PENDIENTE, APROBADO, RECHAZADO
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
        
        # Verificar si existe
        cursor.execute("SELECT telegram_id FROM usuarios WHERE telegram_id = %s", (user_id,))
        existe = cursor.fetchone()

        if not existe:
            cursor.execute(
                "INSERT INTO usuarios (telegram_id, nombre, username, saldo_usdt, saldo_lan) VALUES (%s, %s, %s, 0.0, 1250.0)",
                (user_id, first_name, username)
            )
            # Regalo de bienvenida
            cursor.execute("""
                INSERT INTO inventario (telegram_id, item_tipo, cantidad) VALUES 
                (%s, 'maceta_grande', 2),
                (%s, 'agua', 5)
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
            markup_vacio.add(InlineKeyboardButton("🔄 Actualizar", callback_data="panel_admin"))
            bot.send_message(chat_id, "⚙️ **Panel de Administración** ⚙️\n\n✅ Todo al día. No hay solicitudes pendientes.", parse_mode="Markdown", reply_markup=markup_vacio)
            return
            
        bot.send_message(chat_id, f"📥 Tienes {len(pendientes)} solicitudes pendientes:")
        
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
        
        # Bloquear fila para evitar doble gasto
        cursor.execute("SELECT * FROM transacciones WHERE id = %s FOR UPDATE", (tx_id,))
        tx = cursor.fetchone()
        
        if not tx or tx['estado'] != 'PENDIENTE':
            bot.edit_message_text("⚠️ Esta solicitud ya fue procesada.", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            cursor.close()
            conn.close()
            return
            
        u_id = tx['telegram_id']
        tipo = tx['tipo']
        monto = float(tx['monto'])
        
        if accion == "aprob":
            if tipo == "RECARGA":
                cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt + %s WHERE telegram_id = %s", (monto, u_id))
            elif tipo == "RETIRO":
                # Verificar saldo nuevamente antes de aprobar
                cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = %s", (u_id,))
                user_data = cursor.fetchone()
                if user_data and float(user_data['saldo_usdt']) >= monto:
                    cursor.execute("UPDATE usuarios SET saldo_usdt = saldo_usdt - %s WHERE telegram_id = %s", (monto, u_id))
                else:
                    bot.send_message(message_obj.chat.id, f"❌ Error: El usuario {u_id} ya no tiene saldo suficiente.")
                    cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO_SALDO' WHERE id = %s", (tx_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    return

            cursor.execute("UPDATE transacciones SET estado = 'APROBADO' WHERE id = %s", (tx_id,))
            conn.commit()
            
            try:
                bot.send_message(u_id, f"🎉 ¡Felicidades! Tu solicitud de {monto} USDT ({tipo}) ha sido **APROBADA**.", parse_mode="Markdown")
            except: pass
            bot.edit_message_text(f"✅ #{tx_id} APROBADA CORRECTAMENTE", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
        else:
            cursor.execute("UPDATE transacciones SET estado = 'RECHAZADO' WHERE id = %s", (tx_id,))
            conn.commit()
            
            try:
                bot.send_message(u_id, f"❌ Tu solicitud de {monto} USDT ha sido rechazada por el administrador.")
            except: pass
            bot.edit_message_text(f"❌ #{tx_id} RECHAZADA", chat_id=message_obj.chat.id, message_id=message_obj.message_id)
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error gestiónando transacción: {e}")

# ==========================================
# API FLASK PARA LA MINI APP (FRONTEND)
# ==========================================
@app.after_request
def evitar_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/obtener_perfil', methods=['GET'])
def obtener_perfil():
    user_id = request.args.get('id')
    if not user_id: return jsonify({"error": "Falta ID"}), 400
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT saldo_usdt, saldo_lan FROM usuarios WHERE telegram_id = %s", (user_id,))
    data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if data:
        return jsonify({"usdt": float(data[0]), "lan": float(data[1])})
    return jsonify({"error": "Usuario no registrado"}), 404

@app.route('/obtener_inventario', methods=['GET'])
def obtener_inventario():
    user_id = request.args.get('id')
    conn = conectar_db()
    if not conn: return jsonify({}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT item_tipo, cantidad FROM inventario WHERE telegram_id = %s AND cantidad > 0", (user_id,))
    items = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return jsonify(items)

# =====================================================
# NUEVO ENDPOINT: Obtener Tierras y Slots (AGREGADO)
# =====================================================
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
    slots_base = 4 
    
    cursor.close()
    conn.close()
    return jsonify({
        "slots_totales": slots_base + slots_extra,
        "tierras": tierras
    })

@app.route('/comprar_item', methods=['POST'])
def comprar_item():
    datos = request.json
    user_id = datos.get('id')
    item_key = datos.get('item') # Ej: 'maceta_grande', 'agua', 'tierra_comun'
    
    try:
        cantidad = int(datos.get('cantidad', 1))
        if cantidad <= 0: raise ValueError
    except:
        return jsonify({"error": "Cantidad inválida"}), 400
    
    # Precios definidos en el Frontend
    precios = {
        'maceta_grande': 20, 
        'agua': 5, 
        'semilla_misteriosa': 100,
        'maceta_especial': 50, 
        'fertilizante_pro': 75,
        'tierra_comun': 50, 
        'tierra_rara': 150, 
        'tierra_legendaria': 300
    }
    
    if item_key not in precios:
        return jsonify({"error": "Item no válido"}), 400
        
    costo_unitario = precios[item_key]
    costo_total = costo_unitario * cantidad
    
    conn = conectar_db()
    if not conn: return jsonify({"error": "DB Error"}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Verificar Saldo
    cursor.execute("SELECT saldo_lan FROM usuarios WHERE telegram_id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user or float(user['saldo_lan']) < costo_total:
        cursor.close()
        conn.close()
        return jsonify({"error": "Saldo $LAN insuficiente"}), 400
        
    # 2. Descontar Saldo
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan - %s WHERE telegram_id = %s", (costo_total, user_id))
    
    # 3. Agregar Item
    if 'tierra' in item_key:
        # ==========================================
        # CORREGIDO: Ahora guarda la tierra correctamente
        # ==========================================
        tipo_tierra_map = {
            'tierra_comun': 'comun',
            'tierra_rara': 'rara', 
            'tierra_legendaria': 'legendaria'
        }
        tipo_db = tipo_tierra_map.get(item_key)
        
        if tipo_db:
            cursor.execute("""
                UPDATE usuarios 
                SET tierras_compradas = COALESCE(tierras_compradas, '[]'::jsonb) || %s::jsonb
                WHERE telegram_id = %s
            """, ([tipo_db], user_id))
    else:
        # Items normales (Macetas, Agua, Semillas)
        cursor.execute("""
            INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
            VALUES (%s, %s, %s) 
            ON CONFLICT(telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
        """, (user_id, item_key, cantidad))
    
    conn.commit()
    nuevo_saldo = float(user['saldo_lan']) - costo_total
    cursor.close()
    conn.close()
    
    # ==========================================
    # CORREGIDO: Siempre retornar nuevo_saldo
    # ==========================================
    return jsonify({"mensaje": "Compra exitosa", "nuevo_saldo": nuevo_saldo})

# =====================================================
# NUEVO ENDPOINT: Germinación de Semillas (AGREGADO)
# =====================================================
@app.route('/germinar_semillas', methods=['POST'])
def germinar_semillas():
    datos = request.json
    user_id = datos.get('id')
    cantidad = int(datos.get('cantidad', 1))
    
    conn = conectar_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Verificar recursos necesarios (Maceta Esp + Agua + Fertilizante)
    cursor.execute("""
        SELECT cantidad FROM inventario 
        WHERE telegram_id = %s AND item_tipo IN ('maceta_especial', 'agua', 'fertilizante_pro')
    """, (user_id,))
    inv = {row['item_tipo']: row['cantidad'] for row in cursor.fetchall()}
    
    req_maceta = inv.get('maceta_especial', 0) >= cantidad
    req_agua = inv.get('agua', 0) >= (cantidad * 2)  # HTML dice 2 gotas
    req_fert = inv.get('fertilizante_pro', 0) >= cantidad
    
    if not (req_maceta and req_agua and req_fert):
        cursor.close(); conn.close()
        return jsonify({"error": "Recursos insuficientes"}), 400
    
    # 2. Descontar recursos
    cursor.execute("""
        UPDATE inventario SET cantidad = cantidad - %s 
        WHERE telegram_id = %s AND item_tipo = 'maceta_especial'
    """, (cantidad, user_id))
    cursor.execute("""
        UPDATE inventario SET cantidad = cantidad - %s 
        WHERE telegram_id = %s AND item_tipo = 'agua'
    """, (cantidad * 2, user_id))
    cursor.execute("""
        UPDATE inventario SET cantidad = cantidad - %s 
        WHERE telegram_id = %s AND item_tipo = 'fertilizante_pro'
    """, (cantidad, user_id))
    
    # 3. Crear plantas activas (Rareza aleatoria según HTML)
    rarezas = ['COMÚN', 'RARO', 'ÉPICO', 'LEGENDARIO']
    pesos = [60, 25, 10, 5]  # Probabilidades
    for _ in range(cantidad):
        rareza = random.choices(rarezas, weights=pesos, k=1)[0]
        prod_hora = {'COMÚN': 5, 'RARO': 15, 'ÉPICO': 50, 'LEGENDARIO': 200}[rareza]
        duracion = 24  # Horas según HTML
        
        cursor.execute("""
            INSERT INTO plantas_activas (telegram_id, nombre_planta, rareza, produccion_hora, duracion_horas, estado)
            VALUES (%s, %s, %s, %s, %s, 'CRECIENDO')
        """, (user_id, f"Planta {rareza}", rareza, prod_hora, duracion))
    
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"mensaje": "Germinación exitosa"})

# =====================================================
# NUEVO ENDPOINT: Cosecha de Plantas (AGREGADO)
# =====================================================
@app.route('/cosechar', methods=['POST'])
def cosechar():
    datos = request.json
    user_id = datos.get('id')
    planta_id = datos.get('planta_id')
    
    conn = conectar_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Verificar que la planta esté lista
    cursor.execute("""
        SELECT * FROM plantas_activas 
        WHERE id = %s AND telegram_id = %s AND estado = 'LISTO_PARA_COSCHA'
    """, (planta_id, user_id))
    planta = cursor.fetchone()
    
    if not planta:
        cursor.close(); conn.close()
        return jsonify({"error": "Planta no lista"}), 400
    
    # Sumar recompensa
    cursor.execute("UPDATE usuarios SET saldo_lan = saldo_lan + %s WHERE telegram_id = %s", 
                   (planta['produccion_hora'] * planta['duracion_horas'], user_id))
    
    # Eliminar planta activa
    cursor.execute("DELETE FROM plantas_activas WHERE id = %s", (planta_id,))
    
    # Devolver maceta al almacén (según HTML: "La planta vuelve al almacén")
    cursor.execute("""
        INSERT INTO inventario (telegram_id, item_tipo, cantidad) 
        VALUES (%s, 'maceta_grande', 1) 
        ON CONFLICT(telegram_id, item_tipo) DO UPDATE SET cantidad = inventario.cantidad + EXCLUDED.cantidad
    """, (user_id,))
    
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"mensaje": "Cosecha completada"})

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
    cursor.close()
    conn.close()
    
    # Notificar al Admin
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVA RECARGA (WEB)**\n\n🆔 ID: #{tx_id}\n👤 User: `{user_id}`\n💰 Monto: {monto} USDT", parse_mode="Markdown", reply_markup=markup)
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
    
    # Verificar saldo antes de crear solicitud
    cursor.execute("SELECT saldo_usdt FROM usuarios WHERE telegram_id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user or float(user['saldo_usdt']) < monto:
        cursor.close()
        conn.close()
        return jsonify({"error": "Saldo USDT insuficiente"}), 400

    fecha_actual = datetime.now()
    cursor.execute("INSERT INTO transacciones (telegram_id, tipo, monto, wallet_address, fecha_solicitud) VALUES (%s, %s, %s, %s, %s) RETURNING id", 
                   (user_id, "RETIRO", monto, wallet, fecha_actual))
    tx_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    
    try:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ Aprobar", callback_data=f"aprob_{tx_id}"),
                   InlineKeyboardButton("❌ Rechazar", callback_data=f"rech_{tx_id}"))
        bot.send_message(ADMIN_ID, f"🔔 **NUEVO RETIRO (WEB)**\n\n🆔 ID: #{tx_id}\n👤 User: `{user_id}`\n💰 Monto: {monto} USDT\n🏦 Wallet: `{wallet}`", parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error enviando notif admin: {e}")
        
    return jsonify({"mensaje": "Solicitud de retiro enviada", "tx_id": tx_id})

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
    print(f"🚀 Servidor FlowerLan activo en puerto: {puerto}")
    app.run(host='0.0.0.0', port=puerto, debug=False, use_reloader=False)
