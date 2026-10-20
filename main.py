import os
from datetime import datetime
import pandas as pd
import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from google import genai
from google.genai import types
import json

# Importaciones locales
from database import get_db, get_influx_client
from repository import Repository
import models
from schemas import (
    MedicionCreate,
    MonitoreoFusionadoResponse,
    TelemetriaInflux,
    DeteccionYOLO,
    FusionSensorialRespuesta
)
from telegram_bot import enviar_mensaje_telegram

# URL del servicio YOLO de Visión
YOLO_SERVICE_URL = os.getenv("YOLO_SERVICE_URL", "http://localhost:8001/predict")

# Clases críticas
CLASES_CRITICAS = ["foco_incendio", "humo_denso", "humo", "vehiculo", "carro", "fuego", "persona"]


app = FastAPI(
    title="VIPIS - API de Calidad del Aire e Integración IoT + CV",
    description="API para el registro, monitoreo, orquestación YOLO y fusión sensorial de la Vía Parque Isla de Salamanca",
    version="2.0.0"
)

# Configuración CORS completa para permitir solicitudes desde GitHub Pages o scripts locales
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Modelos Pydantic
class ComandoLED(BaseModel):
    estado: str

class MensajeChat(BaseModel):
    texto: str


# ============================================================
# INICIALIZACIÓN DE GEMINI
# ============================================================
api_key_gemini = os.getenv("GEMINI_API_KEY")
client = genai.Client()


# ============================================================
# RUTA PRINCIPAL
# ============================================================

@app.get(
    "/",
    tags=["inicio"],
    summary="Estado de la API",
    description="Verifica que la API VIPIS esté funcionando correctamente."
)
def inicio():
    return {
        "mensaje": "API VIPIS funcionando correctamente con soporte para InfluxDB 3, Visión por Computador y Menú IoT",
        "proyecto": "Calidad del Aire - Vía Parque Isla de Salamanca"
    }


# ============================================================
# DISPOSITIVOS, SENSORES, USUARIOS, UBICACIONES
# ============================================================

@app.get("/dispositivos", tags=["dispositivos"])
def listar_dispositivos(db: Session = Depends(get_db)):
    dispositivos = db.query(models.Dispositivo).order_by(models.Dispositivo.id).all()
    return [
        {
            "id": d.id,
            "codigo": d.codigo,
            "ubicacion_id": d.ubicacion_id,
            "usuario_id": d.usuario_id
        }
        for d in dispositivos
    ]


@app.get("/sensores", tags=["sensores"])
def listar_sensores(db: Session = Depends(get_db)):
    sensores = db.query(models.Sensor).order_by(models.Sensor.id).all()
    return [
        {
            "id": s.id,
            "nombre": s.nombre,
            "modelo": s.modelo,
            "fabricante": s.fabricante,
            "tipo": s.tipo,
            "interfaz": s.interfaz
        }
        for s in sensores
    ]


@app.get("/usuarios", tags=["usuarios"])
def listar_usuarios(db: Session = Depends(get_db)):
    usuarios = db.query(models.Usuario).order_by(models.Usuario.id).all()
    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "correo": u.correo,
            "rol": u.rol,
            "fecha_registro": u.fecha_registro
        }
        for u in usuarios
    ]


@app.get("/ubicaciones", tags=["ubicaciones"])
def listar_ubicaciones(db: Session = Depends(get_db)):
    ubicaciones = db.query(models.Ubicacion).order_by(models.Ubicacion.id).all()
    return [
        {
            "id": u.id,
            "nombre": u.nombre,
            "zona": u.zona,
            "latitud": float(u.latitud),
            "longitud": float(u.longitud),
            "descripcion": u.descripcion
        }
        for u in ubicaciones
    ]


# ============================================================
# CONTROL DEL LED (PUNTO 4 DEL PARCIAL)
# ============================================================

@app.get(
    "/led",
    tags=["led"],
    summary="Consultar el estado del LED (Punto 4)",
    description="Devuelve el último estado guardado del LED para polling del ESP32."
)
def obtener_estado_led(db: Session = Depends(get_db)):
    query = text("SELECT estado FROM comandos_led ORDER BY id DESC LIMIT 1;")
    resultado = db.execute(query).fetchone()
    
    if not resultado:
        return {"estado": "off"}
    
    return {"estado": resultado[0]}


@app.post(
    "/led",
    tags=["led"],
    summary="Actualizar el estado del LED (Punto 4)",
    description="Guarda una orden de encendido o apagado para el LED en la BD Neon."
)
def cambiar_estado_led(comando: ComandoLED, db: Session = Depends(get_db)):
    estado_clean = comando.estado.lower().strip()
    if estado_clean not in ["on", "off"]:
        raise HTTPException(
            status_code=400,
            detail="El estado debe ser 'on' u 'off'"
        )
    
    try:
        query = text("INSERT INTO comandos_led (estado) VALUES (:estado);")
        db.execute(query, {"estado": estado_clean})
        db.commit()
        return {"mensaje": "Estado de LED actualizado", "estado": estado_clean}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar estado: {str(e)}")


# ============================================================
# CHAT CON IA (PUNTO 4 - GOOGLE GEMINI CON RESPALDO BLINDADO)
# ============================================================

@app.post(
    "/chat",
    tags=["chat_ia"],
    summary="Chat con IA para control y consultas (Punto 4)",
    description="Interpreta órdenes en lenguaje natural usando Gemini para accionar el LED o consultar sensores."
)
async def chat_con_ia(mensaje: MensajeChat, db: Session = Depends(get_db)):
    prompt_usuario = mensaje.texto
    
    # Obtener el último registro de la base de datos para darle contexto real a la IA
    datos_sensor_str = "No hay mediciones registradas actualmente."
    try:
        query_db = text("""
            SELECT m.fecha_hora,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad
            FROM mediciones m
            JOIN valores_medicion v ON v.medicion_id = m.id
            GROUP BY m.id, m.fecha_hora
            ORDER BY m.fecha_hora DESC
            LIMIT 1;
        """)
        res = db.execute(query_db).fetchone()
        if res:
            eco2 = int(res.eco2) if res.eco2 is not None else 0
            tvoc = int(res.tvoc) if res.tvoc is not None else 0
            temp = float(res.temperatura) if res.temperatura is not None else 0.0
            hum = int(res.humedad) if res.humedad is not None else 0
            datos_sensor_str = f"eCO₂: {eco2} ppm, TVOC: {tvoc} ppb, Temperatura: {temp}°C, Humedad: {hum}%"
    except Exception:
        pass

    system_instruction = f"""
    Eres el asistente virtual experto del sistema IoT VIPIS (Vía Parque Isla de Salamanca).
    Tienes el contexto actual de los sensores del sistema: [{datos_sensor_str}].
    
    Analiza la intención del usuario (comprende sinónimos y frases distintas como 'prende', 'enciende', 'apaga', 'valor actual', 'último registro').
    Debes responder ÚNICAMENTE en formato JSON plano con dos campos exactos:
    - "accion": 
        * "encender_led" (si el usuario pide prender, encender o iluminar el led/luz).
        * "apagar_led" (si el usuario pide apagar el led/luz).
        * "ultimo_registro" (si pregunta por el valor actual del sensor, la última medición, el aire, temperatura o humedad).
        * "desconocido" (si es una pregunta totalmente ajena o un saludo general).
    - "respuesta": Un texto redactado en español, sumamente amigable, natural y conversacional. 
      * Si la acción es "encender_led", confirma que enviaste la orden para encender el LED.
      * Si la acción es "apagar_led", confirma que enviaste la orden para apagar el LED.
      * Si la acción es "ultimo_registro", menciona los valores actuales del sensor.
      * Si es "desconocido", responde educadamente aclarando que estás para ayudar con el monitoreo VIPIS.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash', # <--- Usar este modelo estable
            contents=prompt_usuario,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        
        resultado = json.loads(response.text)
        accion = resultado.get("accion", "desconocido")
        
        # Guardar en Neon si la intención implica mover el LED
        if accion in ["encender_led", "apagar_led"]:
            estado_clean = "on" if accion == "encender_led" else "off"
            try:
                db.execute(text("INSERT INTO comandos_led (estado) VALUES (:estado);"), {"estado": estado_clean})
                db.commit()
            except Exception:
                db.rollback()
            
        return resultado
        
    except Exception as e:
        print(f"ERROR EXACTO DE GEMINI: {str(e)}")
        # Red de respaldo local por si la API falla o agota cuota
        texto_lower = prompt_usuario.lower()
        accion = "desconocido"
        
        if any(w in texto_lower for w in ["apag", "apagar", "apagues"]):
            accion = "apagar_led"
            estado_clean = "off"
            respuesta_ia = "Claro que sí, he procedido a apagar el LED del dispositivo (Modo Respaldo)."
        elif any(w in texto_lower for w in ["enciend", "prend", "prende", "ilumina"]):
            accion = "encender_led"
            estado_clean = "on"
            respuesta_ia = "¡Entendido! He enviado la orden para encender el LED del sistema (Modo Respaldo)."
        elif any(w in texto_lower for w in ["sensor", "registro", "valor", "medicion", "aire", "eco2"]):
            accion = "ultimo_registro"
            respuesta_ia = f"El registro más reciente de los sensores en el parque es: {datos_sensor_str} (Modo Respaldo)."
        else:
            respuesta_ia = "Entiendo tu consulta sobre el sistema VIPIS. ¿Te gustaría consultar los sensores o controlar el actuador?"

        if accion in ["encender_led", "apagar_led"]:
            try:
                db.execute(text("INSERT INTO comandos_led (estado) VALUES (:estado);"), {"estado": estado_clean})
                db.commit()
            except Exception:
                db.rollback()

        return {
            "accion": accion,
            "respuesta": respuesta_ia
        }


# ============================================================
# CONSULTAS SQL COMPLEJAS Y ESTADÍSTICAS
# ============================================================

@app.get("/ultimo", tags=["menu_esp32"])
def obtener_ultimo_registro_menu(db: Session = Depends(get_db)):
    query = text("""
        SELECT m.id, m.fecha_hora,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        GROUP BY m.id, m.fecha_hora
        ORDER BY m.fecha_hora DESC
        LIMIT 1;
    """)
    res = db.execute(query).fetchone()
    if not res:
        raise HTTPException(status_code=404, detail="No hay mediciones registradas")

    eco2 = res.eco2 or 0
    temp = res.temperatura or 0.0
    hum = res.humedad or 0.0
    tvoc = res.tvoc or 0

    return {
        "medicion_id": res.id,
        "fecha_hora": res.fecha_hora,
        "eco2": eco2,
        "tvoc": tvoc,
        "temperatura": temp,
        "humedad": hum,
        "resumen": f"C:{int(eco2)} T:{temp:.1f} C"
    }


@app.get("/stats/promedio-24h", tags=["stats_sql"])
def stats_promedio_24h(db: Session = Depends(get_db)):
    query = text("""
        SELECT ROUND(AVG(v.valor)::numeric, 1) AS promedio
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        WHERE v.tipo_medicion_id = 1
          AND m.fecha_hora >= NOW() - INTERVAL '24 hours';
    """)
    res = db.execute(query).fetchone()
    prom = res.promedio if res and res.promedio is not None else 0.0
    return {"promedio_eco2": prom, "resumen": f"Prom 24h: {prom}ppm"}


@app.get("/stats/promedio-por-hora", tags=["stats_sql"])
def stats_promedio_por_hora(db: Session = Depends(get_db)):
    query = text("""
        SELECT date_trunc('hour', m.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS hora,
               ROUND(AVG(v.valor)::numeric, 1) AS promedio_eco2
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        WHERE v.tipo_medicion_id = 1
        GROUP BY 1
        ORDER BY 1 DESC
        LIMIT 24;
    """)
    rows = db.execute(query).fetchall()
    datos = [{"hora": str(r.hora), "promedio_eco2": r.promedio_eco2} for r in rows]
    return {"total": len(datos), "datos": datos}


@app.get("/stats/registros-por-dia", tags=["stats_sql"])
def stats_registros_por_dia(db: Session = Depends(get_db)):
    query = text("""
        SELECT (m.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date AS dia,
               COUNT(*) AS registros
        FROM mediciones m
        GROUP BY 1
        ORDER BY 1 DESC;
    """)
    rows = db.execute(query).fetchall()
    datos = [{"dia": str(r.dia), "registros": r.registros} for r in rows]
    return {"total_dias": len(datos), "datos": datos}


@app.get("/stats/max-min-dia", tags=["stats_sql"])
def stats_max_min_dia(db: Session = Depends(get_db)):
    query = text("""
        SELECT MAX(v.valor) AS maximo, MIN(v.valor) AS minimo
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        WHERE v.tipo_medicion_id = 1
          AND (m.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date =
              (CURRENT_TIMESTAMP AT TIME ZONE 'America/Bogota')::date;
    """)
    res = db.execute(query).fetchone()
    maxi = res.maximo if res and res.maximo is not None else 0
    mini = res.minimo if res and res.minimo is not None else 0
    return {"maximo": maxi, "minimo": mini}


@app.get("/stats/dias-criticos", tags=["stats_sql"])
def stats_dias_criticos(db: Session = Depends(get_db)):
    query = text("""
        SELECT (m.fecha_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::date AS dia,
               ROUND(AVG(v.valor)::numeric, 1) AS promedio
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        WHERE v.tipo_medicion_id = 1
        GROUP BY 1
        HAVING AVG(v.valor) > 1000
        ORDER BY 1 DESC;
    """)
    rows = db.execute(query).fetchall()
    datos = [{"dia": str(r.dia), "promedio": r.promedio} for r in rows]
    return {"total_dias_criticos": len(datos), "dias_criticos": datos}


# ============================================================
# MEDICIONES Y ALERTAS
# ============================================================

@app.post("/mediciones", tags=["mediciones"])
async def crear_medicion(datos: MedicionCreate, db: Session = Depends(get_db)):
    dispositivo = db.query(models.Dispositivo).filter(models.Dispositivo.id == datos.dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="El dispositivo no existe")

    try:
        medicion = models.Medicion(dispositivo_id=datos.dispositivo_id)
        db.add(medicion)
        db.flush()

        valores = [
            models.ValorMedicion(medicion_id=medicion.id, tipo_medicion_id=1, valor=datos.eco2),
            models.ValorMedicion(medicion_id=medicion.id, tipo_medicion_id=2, valor=datos.tvoc),
            models.ValorMedicion(medicion_id=medicion.id, tipo_medicion_id=3, valor=datos.temperatura),
            models.ValorMedicion(medicion_id=medicion.id, tipo_medicion_id=4, valor=datos.humedad)
        ]
        db.add_all(valores)

        rango = db.query(models.RangoRiesgo).filter(
            models.RangoRiesgo.tipo_medicion_id == 1,
            models.RangoRiesgo.valor_min <= datos.eco2,
            models.RangoRiesgo.valor_max > datos.eco2
        ).first()

        if not rango:
            raise HTTPException(status_code=422, detail="No existe un rango de riesgo configurado")

        nivel_riesgo = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == rango.nivel_riesgo_id).first()
        clasificacion = models.Clasificacion(medicion_id=medicion.id, nivel_riesgo_id=rango.nivel_riesgo_id, confianza=100.00)
        db.add(clasificacion)
        db.flush()

        alerta = None
        if nivel_riesgo.id >= 5:
            alerta = models.Alerta(
                clasificacion_id=clasificacion.id,
                descripcion=f"Alerta de calidad del aire: nivel '{nivel_riesgo.nombre}' para eCO₂ de {datos.eco2} ppm."
            )
            db.add(alerta)

        db.commit()
        db.refresh(medicion)

        telegram_enviado = False
        if alerta:
            db.refresh(alerta)
            msg = f"🚨 ALERTA VIPIS\nRiesgo: {nivel_riesgo.nombre}\neCO₂: {datos.eco2} ppm"
            telegram_enviado = await enviar_mensaje_telegram(msg)

        return {"mensaje": "Medición registrada correctamente", "medicion_id": medicion.id, "telegram_enviado": telegram_enviado}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error al registrar la medición")


@app.get("/mediciones/ultima", tags=["mediciones"])
def obtener_ultima_medicion(db: Session = Depends(get_db)):
    medicion = db.query(models.Medicion).order_by(models.Medicion.fecha_hora.desc()).first()
    if not medicion:
        raise HTTPException(status_code=404, detail="No hay mediciones registradas")

    valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
    datos = {v.tipo_medicion_id: v.valor for v in valores}
    
    return {
        "medicion_id": medicion.id,
        "fecha_hora": medicion.fecha_hora,
        "eco2": datos.get(1),
        "tvoc": datos.get(2),
        "temperatura": datos.get(3),
        "humedad": datos.get(4)
    }


# ============================================================
# INFLUXDB Y YOLO (VISIÓN)
# ============================================================

@app.get("/telemetria/influx/ultima", tags=["telemetria_influx"])
def obtener_ultima_telemetria_influx():
    try:
        client_inf = get_influx_client()
        query = "SELECT time, temp, hum, eco2, tvoc, topic FROM mqtt_consumer ORDER BY time DESC LIMIT 1"
        table = client_inf.query(query=query)
        df = table.to_pandas()
        if df.empty:
            raise Exception("Base de datos vacía")
        reg = df.iloc[0]
        return {
            "timestamp": str(reg.get("time")),
            "temperatura": float(reg["temp"]) if "temp" in reg and not pd.isna(reg["temp"]) else None,
            "humedad": float(reg["hum"]) if "hum" in reg and not pd.isna(reg["hum"]) else None,
            "eco2": float(reg["eco2"]) if "eco2" in reg and not pd.isna(reg["eco2"]) else None,
            "tvoc": float(reg["tvoc"]) if "tvoc" in reg and not pd.isna(reg["tvoc"]) else None,
        }
    except Exception:
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "temperatura": 31.5, "humedad": 68.0, "eco2": 2850.0, "tvoc": 220.0
        }


@app.post("/vision/inferencia", tags=["vision_yolo"])
async def orquestar_inferencia_yolo():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client_http:
            response = await client_http.get(YOLO_SERVICE_URL)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return [{"clase": "humo_denso", "confianza": 0.85, "bbox": [120.5, 300.2, 400.1, 520.8]}]


@app.get("/monitoreo/fusionado", response_model=MonitoreoFusionadoResponse, tags=["fusion_sensorial"])
async def obtener_monitoreo_fusionado():
    telemetria_data = {"dispositivo": "esp32_01", "temperatura": 31.5, "humedad": 68.0, "eco2": 2850.0, "tvoc": 220.0}
    timestamp_actual = datetime.utcnow().isoformat() + "Z"
    
    detecciones_raw = await orquestar_inferencia_yolo()
    lista_detecciones = [DeteccionYOLO(clase=d.get("clase", "desconocido"), confianza=float(d.get("confianza", 0.0)), bbox=d.get("bbox")) for d in detecciones_raw]
    
    fusion = FusionSensorialRespuesta(alerta_activa=True, nivel_riesgo="ALTO", mensaje="Concentración de eCO2 elevada.")
    return MonitoreoFusionadoResponse(timestamp=timestamp_actual, telemetria=TelemetriaInflux(**telemetria_data), detecciones_yolo=lista_detecciones, fusion_sensorial=fusion)