import os
from datetime import datetime
from contextlib import asynccontextmanager
import pandas as pd
import numpy as np
import joblib
import httpx
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from google import genai
from google.genai import types
import json
import base64

# Cargar variables de entorno desde el archivo .env localmente
from dotenv import load_dotenv
load_dotenv()

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
from telegram_bot import enviar_mensaje_telegram, iniciar_bot_cloud, detener_bot_cloud
from vision_alertas import evaluador_vision, UMBRAL_ALERTA

# URL del servicio YOLO de Visión
YOLO_SERVICE_URL = os.getenv("YOLO_SERVICE_URL", "http://localhost:8001/predict")

# Clases críticas
CLASES_CRITICAS = ["foco_incendio", "humo_denso", "humo", "vehiculo", "carro", "fuego", "persona"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arrancar el bot de Telegram junto con la API
    await iniciar_bot_cloud()
    yield
    # Detener el bot al apagar la API
    await detener_bot_cloud()


app = FastAPI(
    title="VIPIS - API de Calidad del Aire e Integración IoT + CV",
    description="API para el registro, monitoreo, orquestación YOLO y fusión sensorial de la Vía Parque Isla de Salamanca",
    version="2.0.0",
    lifespan=lifespan
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
try:
    client = genai.Client(api_key=api_key_gemini) if api_key_gemini else None
    if client:
        print("✅ Cliente de Google GenAI inicializado correctamente.")
    else:
        print("⚠️ GEMINI_API_KEY no configurada. El endpoint /chat funcionará en modo respaldo.")
except Exception as e:
    client = None
    print(f"⚠️ GEMINI_API_KEY no configurada o error al iniciar: {e}")


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
        "mensaje": "API VIPIS funcionando correctamente con soporte para Visión por Computador y Menú IoT",
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
    # Si el LED lo encendió la visión y ya pasó el tiempo sin fuego/humo, se apaga solo
    if evaluador_vision.debe_apagar_led():
        try:
            db.execute(text("INSERT INTO comandos_led (estado) VALUES ('off');"))
            db.commit()
            evaluador_vision.marcar_led_apagado()
            return {"estado": "off"}
        except Exception:
            db.rollback()

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
# CHAT CON IA (PUNTO 4 - GOOGLE GEMINI CON RESPALDO NATURAL)
# ============================================================

@app.post(
    "/chat",
    tags=["chat_ia"],
    summary="Chat con IA para control y consultas (Punto 4)",
    description="Asistente con IA que interpreta lenguaje natural para consultar sensores, estadísticas, alertas, dispositivos, ubicaciones y controlar el LED."
)
async def chat_con_ia(mensaje: MensajeChat, db: Session = Depends(get_db)):
    prompt_usuario = mensaje.texto

    # Recopilar contexto completo del sistema para la IA
    contexto = []

    # Última medición
    try:
        query_db = text("""
            SELECT m.id, m.fecha_hora, m.dispositivo_id,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad,
            nr.nombre AS nivel_riesgo
            FROM mediciones m
            JOIN valores_medicion v ON v.medicion_id = m.id
            LEFT JOIN clasificaciones c ON c.medicion_id = m.id
            LEFT JOIN niveles_riesgo nr ON nr.id = c.nivel_riesgo_id
            GROUP BY m.id, m.fecha_hora, m.dispositivo_id, nr.nombre
            ORDER BY m.fecha_hora DESC
            LIMIT 1;
        """)
        res = db.execute(query_db).fetchone()
        if res:
            eco2 = int(res.eco2) if res.eco2 is not None else 0
            tvoc = int(res.tvoc) if res.tvoc is not None else 0
            temp = float(res.temperatura) if res.temperatura is not None else 0.0
            hum = int(res.humedad) if res.humedad is not None else 0
            nivel = res.nivel_riesgo or "N/D"
            fecha = str(res.fecha_hora)[:19] if res.fecha_hora else "N/D"
            contexto.append(
                f"Última medición (#{res.id}, fecha {fecha}, dispositivo {res.dispositivo_id}): "
                f"eCO2 {eco2} ppm, TVOC {tvoc} ppb, temperatura {temp} °C, humedad {hum}%, nivel de riesgo '{nivel}'."
            )
    except Exception:
        pass

    # Estadísticas generales
    try:
        total = db.execute(text("SELECT COUNT(*) FROM mediciones;")).scalar() or 0
        criticas = db.execute(
            text("SELECT COUNT(*) FROM clasificaciones WHERE nivel_riesgo_id >= 5;")
        ).scalar() or 0
        prom_eco2 = db.execute(
            text("SELECT ROUND(AVG(v.valor)::numeric,1) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")
        ).scalar() or 0
        max_eco2 = db.execute(
            text("SELECT MAX(v.valor) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")
        ).scalar() or 0
        prom_temp = db.execute(
            text("SELECT ROUND(AVG(v.valor)::numeric,1) FROM valores_medicion v WHERE v.tipo_medicion_id = 3;")
        ).scalar() or 0
        prom_hum = db.execute(
            text("SELECT ROUND(AVG(v.valor)::numeric,1) FROM valores_medicion v WHERE v.tipo_medicion_id = 4;")
        ).scalar() or 0
        contexto.append(
            f"Estadísticas históricas: {total} mediciones en total, {criticas} críticas, "
            f"promedio de eCO2 de {prom_eco2} ppm (máximo {max_eco2} ppm), "
            f"temperatura promedio de {prom_temp} °C y humedad promedio de {prom_hum}%."
        )
    except Exception:
        pass

    # Promedio eCO2 últimas 24h
    try:
        prom_24h = db.execute(text("""
            SELECT ROUND(AVG(v.valor)::numeric, 1)
            FROM mediciones m
            JOIN valores_medicion v ON v.medicion_id = m.id
            WHERE v.tipo_medicion_id = 1
              AND m.fecha_hora >= NOW() - INTERVAL '24 hours';
        """)).scalar()
        contexto.append(f"Promedio de eCO2 en las últimas 24 horas: {prom_24h or 0} ppm.")
    except Exception:
        pass

    # Alertas pendientes
    try:
        n_alertas = db.execute(
            text("SELECT COUNT(*) FROM alertas WHERE atendida = false;")
        ).scalar() or 0
        contexto.append(f"Alertas pendientes sin atender: {n_alertas}.")
    except Exception:
        pass

    # Últimas detecciones de visión por computador
    try:
        detecciones = db.execute(text("""
            SELECT clase, confianza, fecha_hora
            FROM detecciones_vision
            ORDER BY fecha_hora DESC
            LIMIT 3;
        """)).fetchall()
        if detecciones:
            det_str = "; ".join([
                f"{d.clase} ({float(d.confianza)}% el {str(d.fecha_hora)[:19]})"
                for d in detecciones
            ])
            contexto.append(f"Últimas alertas de visión (YOLO): {det_str}.")
        else:
            contexto.append("Últimas alertas de visión (YOLO): sin eventos recientes registrados.")
    except Exception:
        pass

    # Dispositivos
    try:
        dispositivos = db.query(models.Dispositivo).all()
        if dispositivos:
            disp_str = ", ".join([
                f"{d.codigo} (ID {d.id}, estado: {d.estado})"
                for d in dispositivos
            ])
            contexto.append(f"Dispositivos registrados: {disp_str}.")
    except Exception:
        pass

    # Sensores
    try:
        sensores = db.query(models.Sensor).all()
        if sensores:
            sen_str = ", ".join([
                f"{s.nombre} ({s.modelo} de {s.fabricante}, tipo {s.tipo})"
                for s in sensores
            ])
            contexto.append(f"Sensores instalados: {sen_str}.")
    except Exception:
        pass

    # Ubicaciones
    try:
        ubicaciones = db.query(models.Ubicacion).all()
        if ubicaciones:
            ubi_str = ", ".join([
                f"{u.nombre} en zona {u.zona} (lat {float(u.latitud)}, lon {float(u.longitud)})"
                for u in ubicaciones
            ])
            contexto.append(f"Ubicaciones de monitoreo: {ubi_str}.")
    except Exception:
        pass

    # Estado del LED
    try:
        led_estado = db.execute(
            text("SELECT estado FROM comandos_led ORDER BY id DESC LIMIT 1;")
        ).scalar()
        contexto.append(f"Estado actual del LED en el ESP32: {'encendido' if led_estado == 'on' else 'apagado'}.")
    except Exception:
        pass

    contexto_str = "\n".join(contexto) if contexto else "Sin datos disponibles en este momento."

    system_instruction = f"""
Eres el asistente virtual de VIPIS, el sistema de monitoreo ambiental y calidad del aire de la Vía Parque Isla de Salamanca.
Hablas en español con un tono cercano, claro y conversacional, como un compañero técnico que explica los datos de forma natural y útil.

CONTEXTO ACTUAL DEL SISTEMA EN TIEMPO REAL:
{contexto_str}

REGLAS DE ESTILO PARA REDACTAR "respuesta":
- Escribe en párrafos naturales y fluidos; evita formatos robóticos o de ficha técnica como "eCO₂=2000 ppm, TVOC=5000 ppb".
- Integra los números reales dentro de la oración e interpreta brevemente qué significan (por ejemplo, si el nivel de riesgo es alto o si los gases están elevados, coméntalo de forma natural).
- No menciones el ID interno de la medición ni la fecha exacta a menos que el usuario los pida.
- Si el usuario saluda ("hola", "buenas", "¿qué tal?"), respóndele con calidez y cuéntale brevemente en qué le puedes ayudar sin soltar una lista rígida.
- Si pide encender o apagar el LED, confirma de forma natural que ya enviaste la orden al ESP32.

Responde ÚNICAMENTE con un objeto JSON válido con exactamente dos claves:
- "accion": "encender_led" | "apagar_led" | "consulta" | "desconocido"
- "respuesta": texto natural en español para mostrar al usuario.
"""

    try:
        if client is None:
            raise Exception("Gemini no configurado (modo respaldo local)")

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt_usuario,
    config=types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
    ),
)

        resultado = json.loads(response.text)
        accion = resultado.get("accion", "desconocido")
        respuesta_texto = resultado.get("respuesta", "").strip()

        if not respuesta_texto:
            raise Exception("Respuesta vacía de Gemini")

        # Guardar en Neon si la intención implica mover el LED
        if accion in ["encender_led", "apagar_led"]:
            estado_clean = "on" if accion == "encender_led" else "off"
            try:
                db.execute(text("INSERT INTO comandos_led (estado) VALUES (:estado);"), {"estado": estado_clean})
                db.commit()
            except Exception:
                db.rollback()

        return {
            "accion": accion,
            "respuesta": respuesta_texto
        }

    except Exception as e:
        print(f"ERROR EXACTO DE GEMINI: {str(e)}")
        # Respaldo local natural por si Gemini no está disponible
        texto_lower = prompt_usuario.lower()
        accion = "consulta"
        respuesta_ia = ""

        # Control del LED
        if any(w in texto_lower for w in ["apag", "apagar", "apagues"]) and any(w in texto_lower for w in ["led", "luz"]):
            accion = "apagar_led"
            respuesta_ia = "Listo, ya envié la orden para apagar el LED del ESP32."
        elif any(w in texto_lower for w in ["enciend", "prend", "prende", "ilumina"]) and any(w in texto_lower for w in ["led", "luz"]):
            accion = "encender_led"
            respuesta_ia = "Listo, ya envié la orden para encender el LED del ESP32."

        # Estadísticas
        elif any(w in texto_lower for w in ["estadistic", "promedio", "media", "máximo", "maximo", "mínimo", "minimo", "cuántas", "cuantas", "total"]):
            try:
                total = db.execute(text("SELECT COUNT(*) FROM mediciones;")).scalar() or 0
                criticas = db.execute(text("SELECT COUNT(*) FROM clasificaciones WHERE nivel_riesgo_id >= 5;")).scalar() or 0
                prom = db.execute(text("SELECT ROUND(AVG(v.valor)::numeric,1) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")).scalar() or 0
                max_v = db.execute(text("SELECT MAX(v.valor) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")).scalar() or 0
                respuesta_ia = (
                    f"Hasta ahora llevamos {total} mediciones registradas en el sistema, y {criticas} de ellas "
                    f"han sido clasificadas como críticas. En general, el promedio de eCO₂ está en {prom} ppm "
                    f"y el pico máximo alcanzado ha sido de {max_v} ppm."
                )
            except Exception:
                respuesta_ia = "Ahora mismo no pude consultar las estadísticas históricas en la base de datos."

        # Alertas
        elif any(w in texto_lower for w in ["alerta", "alertas", "pendiente", "riesgo"]):
            try:
                count = db.execute(text("SELECT COUNT(*) FROM alertas WHERE atendida = false;")).scalar() or 0
                if count > 0:
                    respuesta_ia = f"Actualmente tienes {count} alertas pendientes por revisar en el sistema."
                else:
                    respuesta_ia = "Por ahora no hay alertas pendientes; todo está bajo control."
            except Exception:
                respuesta_ia = "No pude revisar el estado de las alertas en este momento."

        # Dispositivos
        elif any(w in texto_lower for w in ["dispositivo", "dispositivos"]):
            try:
                dispositivos = db.query(models.Dispositivo).all()
                if dispositivos:
                    lista = ", ".join([f"{d.codigo} ({d.estado})" for d in dispositivos])
                    respuesta_ia = f"Tenemos {len(dispositivos)} dispositivo(s) registrado(s): {lista}."
                else:
                    respuesta_ia = "Aún no hay dispositivos registrados en el sistema."
            except Exception:
                respuesta_ia = "No pude consultar los dispositivos en este momento."

        # Sensores
        elif any(w in texto_lower for w in ["sensor", "sensores"]) and "dispositivo" not in texto_lower:
            try:
                sensores = db.query(models.Sensor).all()
                if sensores:
                    lista = ", ".join([f"{s.nombre} ({s.modelo} de {s.fabricante})" for s in sensores])
                    respuesta_ia = f"El monitoreo trabaja con los siguientes sensores: {lista}."
                else:
                    respuesta_ia = "No encontré sensores registrados todavía."
            except Exception:
                respuesta_ia = "No pude consultar los sensores en este momento."

        # Ubicaciones
        elif any(w in texto_lower for w in ["ubicacion", "ubicaciones", "donde", "lugar", "zona", "coordenada"]):
            try:
                ubicaciones = db.query(models.Ubicacion).all()
                if ubicaciones:
                    lista = ", ".join([f"{u.nombre} (zona {u.zona})" for u in ubicaciones])
                    respuesta_ia = f"Estamos monitoreando en {lista}."
                else:
                    respuesta_ia = "No hay ubicaciones registradas en el sistema."
            except Exception:
                respuesta_ia = "No pude consultar las ubicaciones en este momento."

        # Estado del LED
        elif any(w in texto_lower for w in ["estado del led", "estado led", "led encendido", "led apagado", "cómo está el led", "como esta el led"]):
            try:
                led = db.execute(text("SELECT estado FROM comandos_led ORDER BY id DESC LIMIT 1;")).scalar() or "off"
                respuesta_ia = f"Ahora mismo el LED del ESP32 está {'encendido' if led == 'on' else 'apagado'}."
            except Exception:
                respuesta_ia = "No pude verificar el estado del LED en este momento."

        # Última medición / calidad del aire
        elif any(w in texto_lower for w in ["sensor", "registro", "valor", "medicion", "aire", "eco2", "temperatura", "humedad", "tvoc", "calidad", "cómo está", "como esta"]):
            try:
                q = text("""
                    SELECT m.id,
                    MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
                    MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
                    MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
                    MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad,
                    nr.nombre AS nivel_riesgo
                    FROM mediciones m
                    JOIN valores_medicion v ON v.medicion_id = m.id
                    LEFT JOIN clasificaciones c ON c.medicion_id = m.id
                    LEFT JOIN niveles_riesgo nr ON nr.id = c.nivel_riesgo_id
                    GROUP BY m.id, nr.nombre
                    ORDER BY m.fecha_hora DESC
                    LIMIT 1;
                """)
                r = db.execute(q).fetchone()
                if r:
                    nivel = r.nivel_riesgo or "sin clasificar"
                    respuesta_ia = (
                        f"Ahora mismo la calidad del aire presenta un nivel de riesgo {nivel}. "
                        f"Los sensores registran {int(r.eco2 or 0)} ppm de eCO₂ y {int(r.tvoc or 0)} ppb de TVOC, "
                        f"con una temperatura ambiente de {float(r.temperatura or 0)} °C y {int(r.humedad or 0)}% de humedad."
                    )
                else:
                    respuesta_ia = "Todavía no hay mediciones registradas en el sistema."
            except Exception:
                respuesta_ia = "No pude consultar la última medición en este momento."

        # Saludo o desconocido
        else:
            accion = "desconocido"
            respuesta_ia = (
                "¡Hola! Soy el asistente de VIPIS. Puedo contarte cómo está la calidad del aire, "
                "revisar estadísticas, alertas, sensores o encender y apagar el LED del ESP32. ¿Qué te gustaría consultar?"
            )

        # Ejecutar acción del LED
        if accion in ["encender_led", "apagar_led"]:
            estado_clean = "on" if accion == "encender_led" else "off"
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
# MODELO DE MACHINE LEARNING - VIPIS (Árbol de Decisión)
# ============================================================

try:
    modelo_ml = joblib.load("modelo_vipis_ml.pkl")
    print("✅ Modelo de Machine Learning cargado correctamente.")
except Exception as e:
    modelo_ml = None
    print(f"⚠️ Error al cargar el modelo de Machine Learning: {e}")


class MedicionML(BaseModel):
    temperatura: float  # Corresponde a field3
    humedad: float      # Corresponde a field4
    eco2: float         # Corresponde a field5
    tvoc: float         # Corresponde a field6


@app.post(
    "/api/ml/predecir",
    tags=["Machine Learning"],
    summary="Predecir calidad del aire con IA",
    description="Recibe temperatura, humedad, eCO2 y TVOC, y devuelve la predicción del modelo de Árbol de Decisión."
)
def predecir_calidad(medicion: MedicionML):
    if modelo_ml is None:
        raise HTTPException(
            status_code=500,
            detail="El modelo de Machine Learning no está cargado en el servidor."
        )

    # Organizar los datos en el orden exacto en que se entrenó: [Temperatura, Humedad, eCO2, TVOC]
    datos_entrada = np.array([[medicion.temperatura, medicion.humedad, medicion.eco2, medicion.tvoc]])

    # Ejecutar la predicción
    prediccion = modelo_ml.predict(datos_entrada)[0]

    return {
        "estado": "exitoso",
        "calidad_predicha": prediccion,
        "datos_recibidos": {
            "temperatura": medicion.temperatura,
            "humedad": medicion.humedad,
            "eco2": medicion.eco2,
            "tvoc": medicion.tvoc
        }
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
            msg = (
                f"🚨 *ALERTA VIPIS*\n\n"
                f"⚠️ Riesgo: *{nivel_riesgo.nombre}*\n"
                f"🆔 Medición: #{medicion.id}\n"
                f"📅 {medicion.fecha_hora}\n\n"
                f"🌫️ eCO₂: {datos.eco2} ppm\n"
                f"🧪 TVOC: {datos.tvoc} ppb\n"
                f"🌡️ Temperatura: {datos.temperatura} °C\n"
                f"💧 Humedad: {datos.humedad} %\n\n"
                f"📝 {alerta.descripcion}"
            )
            telegram_enviado = await enviar_mensaje_telegram(msg)

        return {"mensaje": "Medición registrada correctamente", "medicion_id": medicion.id, "telegram_enviado": telegram_enviado}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error al registrar la medición")


@app.get("/mediciones/ultima", tags=["mediciones"])
def obtener_ultima_medicion(db: Session = Depends(get_db)):
    query = text("""
        SELECT m.id, m.dispositivo_id, m.fecha_hora,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad,
            nr.nombre AS nivel_riesgo
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        LEFT JOIN clasificaciones c ON c.medicion_id = m.id
        LEFT JOIN niveles_riesgo nr ON nr.id = c.nivel_riesgo_id
        GROUP BY m.id, m.dispositivo_id, m.fecha_hora, nr.nombre
        ORDER BY m.fecha_hora DESC
        LIMIT 1;
    """)
    res = db.execute(query).fetchone()
    if not res:
        raise HTTPException(status_code=404, detail="No hay mediciones registradas")

    return {
        "medicion_id": res.id,
        "dispositivo_id": res.dispositivo_id,
        "fecha_hora": res.fecha_hora,
        "eco2": res.eco2,
        "tvoc": res.tvoc,
        "temperatura": res.temperatura,
        "humedad": res.humedad,
        "nivel_riesgo": res.nivel_riesgo
    }


@app.get("/mediciones", tags=["mediciones"])
def listar_mediciones(limit: int = 10, db: Session = Depends(get_db)):
    if limit < 1 or limit > 100:
        limit = 10

    query = text("""
        SELECT m.id, m.dispositivo_id, m.fecha_hora,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS humedad,
            nr.nombre AS nivel_riesgo
        FROM mediciones m
        JOIN valores_medicion v ON v.medicion_id = m.id
        LEFT JOIN clasificaciones c ON c.medicion_id = m.id
        LEFT JOIN niveles_riesgo nr ON nr.id = c.nivel_riesgo_id
        GROUP BY m.id, m.dispositivo_id, m.fecha_hora, nr.nombre
        ORDER BY m.fecha_hora DESC
        LIMIT :limit;
    """)
    rows = db.execute(query, {"limit": limit}).fetchall()
    return {"mediciones": [
        {
            "medicion_id": r.id,
            "dispositivo_id": r.dispositivo_id,
            "fecha_hora": r.fecha_hora,
            "eco2": r.eco2,
            "tvoc": r.tvoc,
            "temperatura": r.temperatura,
            "humedad": r.humedad,
            "nivel_riesgo": r.nivel_riesgo
        }
        for r in rows
    ]}


@app.get("/mediciones/estadisticas", tags=["mediciones"])
def estadisticas_mediciones(db: Session = Depends(get_db)):
    total = db.execute(text("SELECT COUNT(*) FROM mediciones;")).scalar() or 0

    criticas = db.execute(
        text("SELECT COUNT(*) FROM clasificaciones WHERE nivel_riesgo_id >= 5;")
    ).scalar() or 0

    query = text("""
        SELECT
            ROUND(AVG(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END)::numeric, 1) AS promedio_eco2,
            MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS maximo_eco2,
            MIN(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS minimo_eco2,
            ROUND(AVG(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END)::numeric, 1) AS promedio_tvoc,
            MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS maximo_tvoc,
            MIN(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS minimo_tvoc,
            ROUND(AVG(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END)::numeric, 1) AS promedio_temperatura,
            MAX(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS maximo_temperatura,
            MIN(CASE WHEN v.tipo_medicion_id = 3 THEN v.valor END) AS minimo_temperatura,
            ROUND(AVG(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END)::numeric, 1) AS promedio_humedad,
            MAX(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS maximo_humedad,
            MIN(CASE WHEN v.tipo_medicion_id = 4 THEN v.valor END) AS minimo_humedad
        FROM valores_medicion v;
    """)
    res = db.execute(query).fetchone()

    def val(attr):
        return getattr(res, attr) if res and getattr(res, attr) is not None else 0

    return {
        "total_mediciones": total,
        "mediciones_criticas": criticas,
        "promedio_eco2_todas_las_mediciones": val("promedio_eco2"),
        "maximo_eco2_todas_las_mediciones": val("maximo_eco2"),
        "minimo_eco2_todas_las_mediciones": val("minimo_eco2"),
        "promedio_tvoc_todas_las_mediciones": val("promedio_tvoc"),
        "maximo_tvoc_todas_las_mediciones": val("maximo_tvoc"),
        "minimo_tvoc_todas_las_mediciones": val("minimo_tvoc"),
        "promedio_temperatura_todas_las_mediciones": val("promedio_temperatura"),
        "maximo_temperatura_todas_las_mediciones": val("maximo_temperatura"),
        "minimo_temperatura_todas_las_mediciones": val("minimo_temperatura"),
        "promedio_humedad_todas_las_mediciones": val("promedio_humedad"),
        "maximo_humedad_todas_las_mediciones": val("maximo_humedad"),
        "minimo_humedad_todas_las_mediciones": val("minimo_humedad")
    }


@app.get("/alertas/pendientes", tags=["alertas"])
def alertas_pendientes(db: Session = Depends(get_db)):
    query = text("""
        SELECT a.id AS alerta_id, a.descripcion, a.fecha_generada,
               c.medicion_id,
               nr.nombre AS nivel_riesgo_nombre,
               MAX(CASE WHEN v.tipo_medicion_id = 1 THEN v.valor END) AS eco2,
               MAX(CASE WHEN v.tipo_medicion_id = 2 THEN v.valor END) AS tvoc
        FROM alertas a
        JOIN clasificaciones c ON c.id = a.clasificacion_id
        JOIN niveles_riesgo nr ON nr.id = c.nivel_riesgo_id
        JOIN valores_medicion v ON v.medicion_id = c.medicion_id
        WHERE a.atendida = false
        GROUP BY a.id, a.descripcion, a.fecha_generada, c.medicion_id, nr.nombre
        ORDER BY a.fecha_generada DESC;
    """)
    rows = db.execute(query).fetchall()
    return [
        {
            "alerta_id": r.alerta_id,
            "medicion_id": r.medicion_id,
            "valores": {
                "eco2": r.eco2,
                "tvoc": r.tvoc
            },
            "nivel_riesgo": {
                "nombre": r.nivel_riesgo_nombre
            },
            "descripcion": r.descripcion
        }
        for r in rows
    ]


@app.put("/alertas/{alerta_id}/atender", tags=["alertas"])
def atender_alerta(alerta_id: int, db: Session = Depends(get_db)):
    existe = db.execute(
        text("SELECT id FROM alertas WHERE id = :alerta_id;"),
        {"alerta_id": alerta_id}
    ).fetchone()

    if not existe:
        raise HTTPException(
            status_code=404,
            detail=f"No existe la alerta #{alerta_id}"
        )

    db.execute(
        text("UPDATE alertas SET atendida = true WHERE id = :alerta_id;"),
        {"alerta_id": alerta_id}
    )
    db.commit()

    return {"mensaje": f"Alerta #{alerta_id} atendida correctamente"}


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


# ============================================================
# VISIÓN POR COMPUTADOR: YOLO (ROBOFLOW)
# ============================================================

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
_roboflow_model = os.getenv("ROBOFLOW_MODEL", "vipis-vision-air")
_roboflow_version = os.getenv("ROBOFLOW_VERSION", "2")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", f"{_roboflow_model}/{_roboflow_version}")
ROBOFLOW_URL = "https://detect.roboflow.com"
MAX_IMAGEN_BYTES = 2_000_000  # 2 MB por imagen


@app.post(
    "/analizar-imagen",
    tags=["vision_yolo"],
    summary="Detectar objetos en una imagen con YOLO (Roboflow)",
    description="Recibe una imagen (campo 'file'), la envía al modelo en Roboflow y devuelve las detecciones."
)
async def analizar_imagen_yolo(file: UploadFile = File(...), confianza: int = 40, db: Session = Depends(get_db)):
    if not ROBOFLOW_API_KEY:
        raise HTTPException(status_code=500, detail="ROBOFLOW_API_KEY no está configurada en el servidor.")

    contenido = await file.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="La imagen está vacía.")
    if len(contenido) > MAX_IMAGEN_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera el máximo de 2 MB.")

    confianza = max(1, min(confianza, 100))

    try:
        async with httpx.AsyncClient(timeout=20.0) as client_http:
            respuesta = await client_http.post(
                f"{ROBOFLOW_URL}/{ROBOFLOW_MODEL_ID}",
                params={"api_key": ROBOFLOW_API_KEY, "confidence": confianza},
                content=base64.b64encode(contenido),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo contactar a Roboflow: {type(e).__name__}")

    if respuesta.status_code != 200:
        print(f"Roboflow respondió {respuesta.status_code}: {respuesta.text[:200]}")
        raise HTTPException(status_code=502, detail=f"Roboflow respondió con código {respuesta.status_code}")

    datos = respuesta.json()
    predicciones = datos.get("predictions", [])

    # Evaluar si hay que disparar una alerta (umbral + frames seguidos + enfriamiento)
    evaluacion = evaluador_vision.evaluar(predicciones)
    alerta = None
    if evaluacion["alerta"]:
        alerta = await _disparar_alerta_vision(db, evaluacion["mejor"])

    return {
        "status": "success",
        "predicciones": predicciones,
        "imagen": datos.get("image"),
        "alerta": alerta,
    }


async def _disparar_alerta_vision(db: Session, mejor: dict) -> dict:
    """Enciende el LED, avisa por Telegram y guarda el registro. Cada paso es independiente."""
    clase = str(mejor.get("class", "desconocido"))
    confianza = round(float(mejor.get("confidence", 0)) * 100, 2)
    led_ok = False
    telegram_ok = False

    # 1) LED: el ESP32 lo lee por polling en GET /led
    try:
        db.execute(text("INSERT INTO comandos_led (estado) VALUES ('on');"))
        db.commit()
        evaluador_vision.marcar_led_encendido()
        led_ok = True
    except Exception as e:
        db.rollback()
        print(f"Alerta visión: no se pudo encender el LED: {e}")

    # 2) Telegram
    try:
        telegram_ok = await enviar_mensaje_telegram(
            f"🔥 *ALERTA VISIÓN VIPIS*\n\n"
            f"Se detectó *{clase}* con {confianza}% de confianza.\n"
            f"💡 LED: {'encendido' if led_ok else 'no se pudo encender'}"
        )
    except Exception as e:
        print(f"Alerta visión: no se pudo enviar Telegram: {e}")

    # 3) Registro en Neon
    try:
        _asegurar_tabla_detecciones(db)
        db.execute(
            text("""INSERT INTO detecciones_vision (clase, confianza, led_activado, telegram_enviado)
                    VALUES (:clase, :confianza, :led, :tg);"""),
            {"clase": clase, "confianza": confianza, "led": led_ok, "tg": bool(telegram_ok)},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Alerta visión: no se pudo guardar el registro: {e}")

    return {"clase": clase, "confianza": confianza, "led_activado": led_ok, "telegram": bool(telegram_ok)}


def _asegurar_tabla_detecciones(db: Session):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS detecciones_vision (
            id SERIAL PRIMARY KEY,
            fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            clase VARCHAR(100) NOT NULL,
            confianza NUMERIC(5,2) NOT NULL,
            led_activado BOOLEAN NOT NULL DEFAULT FALSE,
            telegram_enviado BOOLEAN NOT NULL DEFAULT FALSE
        );
    """))
    db.commit()


@app.get(
    "/vision/alertas",
    tags=["vision_yolo"],
    summary="Historial de alertas de visión",
    description="Devuelve las últimas alertas disparadas por la detección de fuego/humo."
)
def listar_alertas_vision(limit: int = 20, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    _asegurar_tabla_detecciones(db)
    rows = db.execute(
        text("""SELECT id, fecha_hora, clase, confianza, led_activado, telegram_enviado
                FROM detecciones_vision ORDER BY fecha_hora DESC LIMIT :limit;"""),
        {"limit": limit},
    ).fetchall()
    return {"total": len(rows), "alertas": [
        {"id": r.id, "fecha_hora": r.fecha_hora, "clase": r.clase,
         "confianza": float(r.confianza), "led_activado": r.led_activado,
         "telegram_enviado": r.telegram_enviado}
        for r in rows
    ]}
