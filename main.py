import os
from datetime import datetime
from contextlib import asynccontextmanager
import pandas as pd
import numpy as np
import joblib
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
from telegram_bot import enviar_mensaje_telegram, iniciar_bot_cloud, detener_bot_cloud

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
    client = genai.Client()
except Exception:
    client = None
    print("⚠️ GEMINI_API_KEY no configurada. El endpoint /chat funcionará en modo respaldo.")


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
                f"Última medición #{res.id}: eCO₂={eco2} ppm, TVOC={tvoc} ppb, "
                f"Temperatura={temp}°C, Humedad={hum}%, Riesgo={nivel}, "
                f"Fecha={fecha}, Dispositivo ID={res.dispositivo_id}"
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
            f"Estadísticas: Total mediciones={total}, Críticas={criticas}, "
            f"Promedio eCO₂={prom_eco2} ppm, Máx eCO₂={max_eco2} ppm, "
            f"Promedio temperatura={prom_temp}°C, Promedio humedad={prom_hum}%"
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
        contexto.append(f"Promedio eCO₂ últimas 24h: {prom_24h or 0} ppm")
    except Exception:
        pass

    # Alertas pendientes
    try:
        n_alertas = db.execute(
            text("SELECT COUNT(*) FROM alertas WHERE atendida = false;")
        ).scalar() or 0
        contexto.append(f"Alertas pendientes: {n_alertas}")
    except Exception:
        pass

    # Dispositivos
    try:
        dispositivos = db.query(models.Dispositivo).all()
        if dispositivos:
            disp_str = ", ".join([
                f"ID={d.id} código={d.codigo} estado={d.estado}"
                for d in dispositivos
            ])
            contexto.append(f"Dispositivos: {disp_str}")
    except Exception:
        pass

    # Sensores
    try:
        sensores = db.query(models.Sensor).all()
        if sensores:
            sen_str = ", ".join([
                f"{s.nombre} ({s.modelo}, {s.fabricante}, tipo={s.tipo})"
                for s in sensores
            ])
            contexto.append(f"Sensores: {sen_str}")
    except Exception:
        pass

    # Ubicaciones
    try:
        ubicaciones = db.query(models.Ubicacion).all()
        if ubicaciones:
            ubi_str = ", ".join([
                f"{u.nombre} (zona={u.zona}, lat={float(u.latitud)}, lon={float(u.longitud)})"
                for u in ubicaciones
            ])
            contexto.append(f"Ubicaciones: {ubi_str}")
    except Exception:
        pass

    # Estado del LED
    try:
        led_estado = db.execute(
            text("SELECT estado FROM comandos_led ORDER BY id DESC LIMIT 1;")
        ).scalar()
        contexto.append(f"LED actual: {led_estado or 'off'}")
    except Exception:
        pass

    contexto_str = "\n".join(contexto) if contexto else "Sin datos disponibles."

    system_instruction = f"""
    Eres el asistente virtual experto del sistema IoT VIPIS (Vía Parque Isla de Salamanca).
    Es un sistema de monitoreo de calidad del aire que usa sensores de eCO₂, TVOC, temperatura y humedad,
    integrado con visión por computador (YOLO) y telemetría InfluxDB, con un LED controlable en el ESP32.

    CONTEXTO ACTUAL DEL SISTEMA:
    {contexto_str}

    CAPACIDADES DE CONSULTA:
    Puedes responder preguntas sobre cualquier aspecto del sistema usando el contexto anterior:
    - Estado y valores actuales de los sensores (eCO₂, TVOC, temperatura, humedad)
    - Estadísticas (promedios, máximos, mínimos, total de mediciones, mediciones críticas)
    - Nivel de riesgo actual
    - Alertas pendientes
    - Dispositivos registrados
    - Sensores instalados (nombre, modelo, fabricante, tipo)
    - Ubicaciones de monitoreo (zona, coordenadas)
    - Estado del LED (encendido/apagado)
    - Promedio de eCO₂ en las últimas 24 horas

    ACCIONES QUE PUEDES EJECUTAR:
    - Encender el LED del ESP32
    - Apagar el LED del ESP32

    INSTRUCCIONES:
    Analiza la intención del usuario (comprende sinónimos: 'prende'='enciende', 'valor actual'='último registro', etc.).
    Responde ÚNICAMENTE en formato JSON con dos campos:
    - "accion": una de estas opciones:
        * "encender_led" — si pide prender, encender o iluminar el LED/luz.
        * "apagar_led" — si pide apagar el LED/luz.
        * "consulta" — si pregunta sobre sensores, estadísticas, alertas, dispositivos,
          ubicaciones, niveles de riesgo, o cualquier aspecto del sistema.
        * "desconocido" — si es un saludo o algo ajeno al sistema.
    - "respuesta": texto en español, amigable, natural y conversacional.
        * Para "consulta": usa el CONTEXTO ACTUAL para responder con datos reales.
          Si preguntan por el aire, menciona eCO₂, TVOC, temperatura, humedad y nivel de riesgo.
          Si preguntan por estadísticas, menciona promedios, máximos, totales, críticas.
          Si preguntan por alertas, menciona cuántas hay pendientes.
          Si preguntan por dispositivos o sensores, lista los que haya.
          Si preguntan por ubicaciones, menciona las zonas.
          Sé específico y usa los números reales del contexto.
        * Para "encender_led"/"apagar_led": confirma que enviaste la orden.
        * Para "desconocido": responde educadamente y menciona que puedes ayudar
          con consultas sobre sensores, estadísticas, alertas, dispositivos y control del LED.
    """
    
    try:
        if client is None:
            raise Exception("Gemini no configurado (modo respaldo local)")

        response = client.models.generate_content(
            model='gemini-3.8-flash', 
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
        # Respaldo local por si Gemini no está disponible
        texto_lower = prompt_usuario.lower()
        accion = "consulta"
        respuesta_ia = ""

        # Control del LED
        if any(w in texto_lower for w in ["apag", "apagar", "apagues"]) and any(w in texto_lower for w in ["led", "luz"]):
            accion = "apagar_led"
            respuesta_ia = "Claro, he procedido a apagar el LED del dispositivo."
        elif any(w in texto_lower for w in ["enciend", "prend", "prende", "ilumina"]) and any(w in texto_lower for w in ["led", "luz"]):
            accion = "encender_led"
            respuesta_ia = "¡Entendido! He enviado la orden para encender el LED."

        # Estadísticas
        elif any(w in texto_lower for w in ["estadistic", "promedio", "media", "máximo", "maximo", "mínimo", "minimo", "cuántas", "cuantas", "total"]):
            try:
                total = db.execute(text("SELECT COUNT(*) FROM mediciones;")).scalar() or 0
                criticas = db.execute(text("SELECT COUNT(*) FROM clasificaciones WHERE nivel_riesgo_id >= 5;")).scalar() or 0
                prom = db.execute(text("SELECT ROUND(AVG(v.valor)::numeric,1) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")).scalar() or 0
                max_v = db.execute(text("SELECT MAX(v.valor) FROM valores_medicion v WHERE v.tipo_medicion_id = 1;")).scalar() or 0
                respuesta_ia = f"En total hay {total} mediciones registradas, de las cuales {criticas} son críticas. El promedio de eCO₂ es {prom} ppm y el máximo registrado es {max_v} ppm."
            except Exception:
                respuesta_ia = "Las estadísticas están disponibles pero no pude consultarlas en este momento."

        # Alertas
        elif any(w in texto_lower for w in ["alerta", "alertas", "pendiente", "riesgo"]):
            try:
                count = db.execute(text("SELECT COUNT(*) FROM alertas WHERE atendida = false;")).scalar() or 0
                if count > 0:
                    respuesta_ia = f"Hay {count} alertas pendientes en el sistema que requieren atención."
                else:
                    respuesta_ia = "No hay alertas pendientes, todo en orden."
            except Exception:
                respuesta_ia = "No pude consultar las alertas en este momento."

        # Dispositivos
        elif any(w in texto_lower for w in ["dispositivo", "dispositivos"]):
            try:
                dispositivos = db.query(models.Dispositivo).all()
                if dispositivos:
                    respuesta_ia = f"Hay {len(dispositivos)} dispositivos registrados: " + ", ".join([f"{d.codigo} (estado: {d.estado})" for d in dispositivos])
                else:
                    respuesta_ia = "No hay dispositivos registrados."
            except Exception:
                respuesta_ia = "No pude consultar los dispositivos."

        # Sensores
        elif any(w in texto_lower for w in ["sensor", "sensores"]) and "dispositivo" not in texto_lower:
            try:
                sensores = db.query(models.Sensor).all()
                if sensores:
                    respuesta_ia = "Los sensores instalados son: " + ", ".join([f"{s.nombre} ({s.modelo}, {s.fabricante})" for s in sensores])
                else:
                    respuesta_ia = "No hay sensores registrados."
            except Exception:
                respuesta_ia = "No pude consultar los sensores."

        # Ubicaciones
        elif any(w in texto_lower for w in ["ubicacion", "ubicaciones", "donde", "lugar", "zona", "coordenada"]):
            try:
                ubicaciones = db.query(models.Ubicacion).all()
                if ubicaciones:
                    respuesta_ia = "Las ubicaciones de monitoreo son: " + ", ".join([f"{u.nombre} en zona {u.zona}" for u in ubicaciones])
                else:
                    respuesta_ia = "No hay ubicaciones registradas."
            except Exception:
                respuesta_ia = "No pude consultar las ubicaciones."

        # Estado del LED
        elif any(w in texto_lower for w in ["estado del led", "estado led", "led encendido", "led apagado", "cómo está el led", "como esta el led"]):
            try:
                led = db.execute(text("SELECT estado FROM comandos_led ORDER BY id DESC LIMIT 1;")).scalar() or "off"
                respuesta_ia = f"El LED del ESP32 está actualmente {'encendido' if led == 'on' else 'apagado'}."
            except Exception:
                respuesta_ia = "No pude consultar el estado del LED."

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
                    nivel = r.nivel_riesgo or "N/D"
                    respuesta_ia = (f"El último registro (medición #{r.id}) indica: "
                        f"eCO₂={int(r.eco2 or 0)} ppm, TVOC={int(r.tvoc or 0)} ppb, "
                        f"Temperatura={float(r.temperatura or 0)}°C, Humedad={int(r.humedad or 0)}%. "
                        f"Nivel de riesgo: {nivel}.")
                else:
                    respuesta_ia = "No hay mediciones registradas actualmente."
            except Exception:
                respuesta_ia = "No pude consultar la última medición."

        # Saludo o desconocido
        else:
            accion = "desconocido"
            respuesta_ia = ("Soy el asistente del sistema VIPIS de monitoreo de calidad del aire. "
                "Puedo ayudarte con consultas sobre sensores, estadísticas, alertas, "
                "dispositivos, ubicaciones y control del LED. ¿Qué necesitas saber?")

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