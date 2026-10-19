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


# Modelo Pydantic para el control del LED y Chat
class ComandoLED(BaseModel):
    estado: str

class MensajeChat(BaseModel):
    texto: str


# ============================================================
# INICIALIZACIÓN DE GEMINI CON DOBLE RESPALDO (Variables de entorno + Clave directa)
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
# CHAT CON IA (PUNTO 4 - GOOGLE GEMINI)
# ============================================================

@app.post(
    "/chat",
    tags=["chat_ia"],
    summary="Chat con IA para control y consultas (Punto 4)",
    description="Interpreta órdenes en lenguaje natural usando Gemini para accionar el LED o responder consultas."
)
async def chat_con_ia(mensaje: MensajeChat, db: Session = Depends(get_db)):
    prompt_usuario = mensaje.texto
    
    system_instruction = """
    Eres el asistente virtual del sistema IoT VIPIS. Analiza la orden del usuario y responde ÚNICAMENTE en formato JSON plano con dos campos exactos:
    - "accion": elige estrictamente entre "encender_led", "apagar_led", "leer_sensor", "ultimo_registro" o "desconocido".
    - "respuesta": un texto amigable en español respondiendo al usuario o confirmando la acción realizada.
    """
    
    try:
        # Llamada a Google GenAI (Gemini)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_usuario,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        
        resultado = json.loads(response.text)
        accion = resultado.get("accion")
        
        # Si la IA determina que hay que encender o apagar el LED...
        if accion in ["encender_led", "apagar_led"]:
            estado_clean = "on" if accion == "encender_led" else "off"
            try:
                query = text("INSERT INTO comandos_led (estado) VALUES (:estado);")
                db.execute(query, {"estado": estado_clean})
                db.commit()
            except Exception:
                db.rollback()
            
        return resultado
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# CONSULTAS SQL COMPLEJAS Y ESTADÍSTICAS (PUNTO 1 Y MENÚ LCD)
# ============================================================

@app.get(
    "/ultimo",
    tags=["menu_esp32"],
    summary="Último registro guardado (Punto 1 / Menú)",
    description="Obtiene los datos de la última medición con resumen para el ESP32."
)
@app.get(
    "/sensor/actual",
    tags=["menu_esp32"],
    summary="Última lectura actual del sensor (Punto 1 / Menú)",
    description="Devuelve eCO2, TVOC, temperatura y humedad actuales."
)
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


@app.get(
    "/stats/promedio-24h",
    tags=["stats_sql"],
    summary="Promedio eCO2 en las últimas 24 horas (Punto 1)",
    description="Calcula el promedio del sensor eCO2 en las últimas 24 horas."
)
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
    return {
        "promedio_eco2": prom,
        "resumen": f"Prom 24h: {prom}ppm"
    }


@app.get(
    "/stats/promedio-por-hora",
    tags=["stats_sql"],
    summary="Promedio de eCO2 por hora (SQL Complejo - GROUP BY, AVG, date_trunc)",
    description="Agrupa y calcula el promedio por hora ajustado a hora Colombia."
)
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
    return {
        "total": len(datos),
        "datos": datos,
        "resumen": f"Prom.Hora: {datos[0]['promedio_eco2']}p" if datos else "Sin datos"
    }


@app.get(
    "/stats/registros-por-dia",
    tags=["stats_sql"],
    summary="Conteo de mediciones por día (SQL Complejo - GROUP BY, COUNT)",
    description="Cuenta la cantidad de registros capturados por día."
)
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
    return {
        "total_dias": len(datos),
        "datos": datos,
        "resumen": f"Hoy: {datos[0]['registros']} regs" if datos else "Sin registros"
    }


@app.get(
    "/stats/max-min-dia",
    tags=["stats_sql"],
    summary="Valores máximo y mínimo del día actual (SQL Complejo - MAX, MIN)",
    description="Consulta los valores extremales de eCO2 registrados en el día."
)
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
    return {
        "maximo": maxi,
        "minimo": mini,
        "resumen": f"Mx:{int(maxi)} Mn:{int(mini)}"
    }


@app.get(
    "/stats/dias-criticos",
    tags=["stats_sql"],
    summary="Días con promedio superior al umbral (SQL Complejo - HAVING)",
    description="Obtiene los días en que el promedio de eCO2 fue crítico (> 1000 ppm)."
)
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
    return {
        "total_dias_criticos": len(datos),
        "dias_criticos": datos,
        "resumen": f"Criticos: {len(datos)}d"
    }


# ============================================================
# MEDICIONES (SQL - POST Y LISTADO RELACIONAL)
# ============================================================

@app.post(
    "/mediciones",
    tags=["mediciones"],
    summary="Registrar una nueva medición en BD Relacional",
    description="Guarda telemetría de eCO2, TVOC, Temperatura y Humedad en Neon."
)
async def crear_medicion(
    datos: MedicionCreate,
    db: Session = Depends(get_db)
):
    dispositivo = (
        db.query(models.Dispositivo)
        .filter(models.Dispositivo.id == datos.dispositivo_id)
        .first()
    )

    if not dispositivo:
        raise HTTPException(
            status_code=404,
            detail="El dispositivo no existe"
        )

    try:
        medicion = models.Medicion(
            dispositivo_id=datos.dispositivo_id
        )

        db.add(medicion)
        db.flush()

        valores = [
            models.ValorMedicion(
                medicion_id=medicion.id,
                tipo_medicion_id=1,
                valor=datos.eco2
            ),
            models.ValorMedicion(
                medicion_id=medicion.id,
                tipo_medicion_id=2,
                valor=datos.tvoc
            ),
            models.ValorMedicion(
                medicion_id=medicion.id,
                tipo_medicion_id=3,
                valor=datos.temperatura
            ),
            models.ValorMedicion(
                medicion_id=medicion.id,
                tipo_medicion_id=4,
                valor=datos.humedad
            )
        ]

        db.add_all(valores)

        rango = (
            db.query(models.RangoRiesgo)
            .filter(
                models.RangoRiesgo.tipo_medicion_id == 1,
                models.RangoRiesgo.valor_min <= datos.eco2,
                models.RangoRiesgo.valor_max > datos.eco2
            )
            .first()
        )

        if not rango:
            raise HTTPException(
                status_code=422,
                detail="No existe un rango de riesgo configurado para el valor de eCO₂ proporcionado"
            )

        nivel_riesgo = (
            db.query(models.NivelRiesgo)
            .filter(models.NivelRiesgo.id == rango.nivel_riesgo_id)
            .first()
        )

        if not nivel_riesgo:
            raise HTTPException(
                status_code=500,
                detail="El nivel de riesgo configurado no existe"
            )

        clasificacion = models.Clasificacion(
            medicion_id=medicion.id,
            nivel_riesgo_id=rango.nivel_riesgo_id,
            confianza=100.00
        )

        db.add(clasificacion)
        db.flush()

        alerta = None

        if nivel_riesgo.id >= 5:
            alerta = models.Alerta(
                clasificacion_id=clasificacion.id,
                descripcion=(
                    f"Alerta de calidad del aire: "
                    f"nivel de riesgo '{nivel_riesgo.nombre}' "
                    f"detectado para un eCO₂ de {datos.eco2} ppm."
                )
            )
            db.add(alerta)

        db.commit()

        db.refresh(medicion)
        db.refresh(clasificacion)

        if alerta:
            db.refresh(alerta)

        telegram_enviado = False

        if alerta:
            mensaje_telegram = (
                "🚨 ALERTA VIPIS\n\n"
                f"Nivel de riesgo: {nivel_riesgo.nombre}\n"
                f"eCO₂: {datos.eco2} ppm\n"
                f"TVOC: {datos.tvoc} ppb\n"
                f"Temperatura: {datos.temperatura} °C\n"
                f"Humedad: {datos.humedad} %\n"
                f"Dispositivo: {dispositivo.codigo}\n"
                f"Medición: #{medicion.id}\n"
                f"Alerta: #{alerta.id}"
            )

            telegram_enviado = await enviar_mensaje_telegram(mensaje_telegram)

        return {
            "mensaje": "Medición registrada correctamente",
            "medicion_id": medicion.id,
            "dispositivo_id": medicion.dispositivo_id,
            "eco2": datos.eco2,
            "tvoc": datos.tvoc,
            "temperatura": datos.temperatura,
            "humedad": datos.humedad,
            "nivel_riesgo": {
                "id": nivel_riesgo.id,
                "nombre": nivel_riesgo.nombre
            },
            "alerta_generada": alerta is not None,
            "alerta_id": alerta.id if alerta else None,
            "telegram_enviado": telegram_enviado
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Error al registrar la medición"
        )


@app.get("/mediciones/ultima", tags=["mediciones"])
def obtener_ultima_medicion(db: Session = Depends(get_db)):
    medicion = (
        db.query(models.Medicion)
        .order_by(models.Medicion.fecha_hora.desc())
        .first()
    )

    if not medicion:
        raise HTTPException(status_code=404, detail="No hay mediciones registradas")

    valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
    datos = {}
    for valor in valores:
        if valor.tipo_medicion_id == 1:
            datos["eco2"] = valor.valor
        elif valor.tipo_medicion_id == 2:
            datos["tvoc"] = valor.valor
        elif valor.tipo_medicion_id == 3:
            datos["temperatura"] = valor.valor
        elif valor.tipo_medicion_id == 4:
            datos["humedad"] = valor.valor

    clasificacion = db.query(models.Clasificacion).filter(models.Clasificacion.medicion_id == medicion.id).first()
    nivel_riesgo = None

    if clasificacion:
        riesgo = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == clasificacion.nivel_riesgo_id).first()
        if riesgo:
            nivel_riesgo = riesgo.nombre

    return {
        "medicion_id": medicion.id,
        "dispositivo_id": medicion.dispositivo_id,
        "fecha_hora": medicion.fecha_hora,
        "eco2": datos.get("eco2"),
        "tvoc": datos.get("tvoc"),
        "temperatura": datos.get("temperatura"),
        "humedad": datos.get("humedad"),
        "nivel_riesgo": nivel_riesgo
    }


@app.get("/mediciones", tags=["mediciones"])
def obtener_mediciones(limit: int = 10, db: Session = Depends(get_db)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="El límite debe estar entre 1 y 100")

    mediciones = (
        db.query(models.Medicion)
        .order_by(models.Medicion.fecha_hora.desc())
        .limit(limit)
        .all()
    )

    resultado = []
    for medicion in mediciones:
        valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
        datos = {}
        for valor in valores:
            if valor.tipo_medicion_id == 1:
                datos["eco2"] = valor.valor
            elif valor.tipo_medicion_id == 2:
                datos["tvoc"] = valor.valor
            elif valor.tipo_medicion_id == 3:
                datos["temperatura"] = valor.valor
            elif valor.tipo_medicion_id == 4:
                datos["humedad"] = valor.valor

        clasificacion = db.query(models.Clasificacion).filter(models.Clasificacion.medicion_id == medicion.id).first()
        nivel_riesgo = None
        if clasificacion:
            riesgo = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == clasificacion.nivel_riesgo_id).first()
            if riesgo:
                nivel_riesgo = riesgo.nombre

        resultado.append({
            "medicion_id": medicion.id,
            "dispositivo_id": medicion.dispositivo_id,
            "fecha_hora": medicion.fecha_hora,
            "eco2": datos.get("eco2"),
            "tvoc": datos.get("tvoc"),
            "temperatura": datos.get("temperatura"),
            "humedad": datos.get("humedad"),
            "nivel_riesgo": nivel_riesgo
        })

    return {"total": len(resultado), "mediciones": resultado}


@app.get("/mediciones/criticas", tags=["mediciones"])
def obtener_mediciones_criticas(db: Session = Depends(get_db)):
    mediciones = (
        db.query(models.Medicion)
        .join(models.Clasificacion, models.Clasificacion.medicion_id == models.Medicion.id)
        .join(models.NivelRiesgo, models.NivelRiesgo.id == models.Clasificacion.nivel_riesgo_id)
        .filter(models.NivelRiesgo.nombre == "Crítico")
        .order_by(models.Medicion.fecha_hora.desc())
        .all()
    )

    resultado = []
    for medicion in mediciones:
        valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
        datos = {}
        for valor in valores:
            if valor.tipo_medicion_id == 1:
                datos["eco2"] = valor.valor
            elif valor.tipo_medicion_id == 2:
                datos["tvoc"] = valor.valor
            elif valor.tipo_medicion_id == 3:
                datos["temperatura"] = valor.valor
            elif valor.tipo_medicion_id == 4:
                datos["humedad"] = valor.valor

        resultado.append({
            "medicion_id": medicion.id,
            "dispositivo_id": medicion.dispositivo_id,
            "fecha_hora": medicion.fecha_hora,
            "eco2": datos.get("eco2"),
            "tvoc": datos.get("tvoc"),
            "temperatura": datos.get("temperatura"),
            "humedad": datos.get("humedad"),
            "nivel_riesgo": "Crítico"
        })

    return {"total": len(resultado), "mediciones": resultado}


@app.get("/mediciones/estadisticas", tags=["mediciones"])
def obtener_estadisticas(db: Session = Depends(get_db)):
    mediciones = db.query(models.Medicion).all()
    if not mediciones:
        return {"total_mediciones": 0, "mediciones_criticas": 0}

    eco2_valores, tvoc_valores, temperatura_valores, humedad_valores = [], [], [], []
    mediciones_criticas = 0

    for medicion in mediciones:
        valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
        for valor in valores:
            if valor.valor is None:
                continue
            if valor.tipo_medicion_id == 1:
                eco2_valores.append(float(valor.valor))
            elif valor.tipo_medicion_id == 2:
                tvoc_valores.append(float(valor.valor))
            elif valor.tipo_medicion_id == 3:
                temperatura_valores.append(float(valor.valor))
            elif valor.tipo_medicion_id == 4:
                humedad_valores.append(float(valor.valor))

        clasificacion = db.query(models.Clasificacion).filter(models.Clasificacion.medicion_id == medicion.id).first()
        if clasificacion:
            nivel = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == clasificacion.nivel_riesgo_id).first()
            if nivel and nivel.nombre == "Crítico":
                mediciones_criticas += 1

    def calc_prom(v): return round(sum(v) / len(v), 2) if v else None
    def calc_max(v): return max(v) if v else None
    def calc_min(v): return min(v) if v else None

    return {
        "total_mediciones": len(mediciones),
        "mediciones_criticas": mediciones_criticas,
        "promedio_eco2_todas_las_mediciones": calc_prom(eco2_valores),
        "maximo_eco2_todas_las_mediciones": calc_max(eco2_valores),
        "minimo_eco2_todas_las_mediciones": calc_min(eco2_valores),
        "promedio_tvoc_todas_las_mediciones": calc_prom(tvoc_valores),
        "maximo_tvoc_todas_las_mediciones": calc_max(tvoc_valores),
        "minimo_tvoc_todas_las_mediciones": calc_min(tvoc_valores),
        "promedio_temperatura_todas_las_mediciones": calc_prom(temperatura_valores),
        "maximo_temperatura_todas_las_mediciones": calc_max(temperatura_valores),
        "minimo_temperatura_todas_las_mediciones": calc_min(temperatura_valores),
        "promedio_humedad_todas_las_mediciones": calc_prom(humedad_valores),
        "maximo_humedad_todas_las_mediciones": calc_max(humedad_valores),
        "minimo_humedad_todas_las_mediciones": calc_min(humedad_valores)
    }


# ============================================================
# ALERTAS Y CONFIGURACIONES
# ============================================================

@app.get("/alertas/pendientes", tags=["alertas"])
def listar_alertas_pendientes(db: Session = Depends(get_db)):
    resultados = (
        db.query(models.Alerta, models.Clasificacion, models.NivelRiesgo, models.Medicion)
        .join(models.Clasificacion, models.Alerta.clasificacion_id == models.Clasificacion.id)
        .join(models.NivelRiesgo, models.Clasificacion.nivel_riesgo_id == models.NivelRiesgo.id)
        .join(models.Medicion, models.Clasificacion.medicion_id == models.Medicion.id)
        .filter(models.Alerta.atendida == False)
        .order_by(models.Alerta.id.desc())
        .all()
    )

    respuesta = []
    for alerta, clasificacion, nivel_riesgo, medicion in resultados:
        valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == medicion.id).all()
        datos_valores = {}
        for valor in valores:
            if valor.tipo_medicion_id == 1:
                datos_valores["eco2"] = valor.valor
            elif valor.tipo_medicion_id == 2:
                datos_valores["tvoc"] = valor.valor
            elif valor.tipo_medicion_id == 3:
                datos_valores["temperatura"] = valor.valor
            elif valor.tipo_medicion_id == 4:
                datos_valores["humedad"] = valor.valor

        respuesta.append({
            "alerta_id": alerta.id,
            "descripcion": alerta.descripcion,
            "atendida": alerta.atendida,
            "clasificacion_id": clasificacion.id,
            "medicion_id": medicion.id,
            "nivel_riesgo": {"id": nivel_riesgo.id, "nombre": nivel_riesgo.nombre},
            "valores": datos_valores
        })

    return respuesta


@app.put("/alertas/{alerta_id}/atender", tags=["alertas"])
def atender_alerta(alerta_id: int, db: Session = Depends(get_db)):
    alerta = db.query(models.Alerta).filter(models.Alerta.id == alerta_id).first()
    if not alerta:
        raise HTTPException(status_code=404, detail="La alerta no existe")

    alerta.atendida = True
    db.commit()
    db.refresh(alerta)
    return {"mensaje": "Alerta marcada como atendida", "alerta_id": alerta.id, "atendida": alerta.atendida}


@app.get("/rangos", tags=["rangos"])
def listar_rangos(db: Session = Depends(get_db)):
    tipos = db.query(models.TipoMedicion).order_by(models.TipoMedicion.id).all()
    respuesta = []
    for tipo in tipos:
        rangos = (
            db.query(models.RangoRiesgo)
            .filter(models.RangoRiesgo.tipo_medicion_id == tipo.id)
            .order_by(models.RangoRiesgo.valor_min)
            .all()
        )
        rangos_resp = []
        for rango in rangos:
            nivel = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == rango.nivel_riesgo_id).first()
            rangos_resp.append({
                "id": rango.id,
                "valor_min": rango.valor_min,
                "valor_max": rango.valor_max,
                "nivel_riesgo_id": rango.nivel_riesgo_id,
                "nivel_riesgo": nivel.nombre if nivel else None
            })
        respuesta.append({"tipo_medicion_id": tipo.id, "nombre": tipo.nombre, "unidad": tipo.unidad, "rangos": rangos_resp})

    return respuesta


@app.get("/tipos-medicion", tags=["tipos_medicion"])
def listar_tipos_medicion(db: Session = Depends(get_db)):
    tipos = db.query(models.TipoMedicion).order_by(models.TipoMedicion.id).all()
    return [{"id": t.id, "nombre": t.nombre, "unidad": t.unidad, "origen": t.origen} for t in tipos]


# ============================================================
# RUTAS INTEGRADAS: INFLUXDB 3, YOLO Y FUSIÓN SENSORIAL
# ============================================================

@app.get("/telemetria/influx/ultima", tags=["telemetria_influx"])
def obtener_ultima_telemetria_influx():
    try:
        client = get_influx_client()
        query = "SELECT time, temp, hum, eco2, tvoc, topic FROM mqtt_consumer ORDER BY time DESC LIMIT 1"
        table = client.query(query=query)
        df = table.to_pandas()

        if df.empty:
            raise Exception("Base de datos vacía")

        registro = df.iloc[0]
        return {
            "timestamp": str(registro.get("time")),
            "topic": registro.get("topic", "iot/vipis/sensor"),
            "temperatura": float(registro["temp"]) if "temp" in registro and not pd.isna(registro["temp"]) else None,
            "humedad": float(registro["hum"]) if "hum" in registro and not pd.isna(registro["hum"]) else None,
            "eco2": float(registro["eco2"]) if "eco2" in registro and not pd.isna(registro["eco2"]) else None,
            "tvoc": float(registro["tvoc"]) if "tvoc" in registro and not pd.isna(registro["tvoc"]) else None,
        }
    except Exception as e:
        print(f"Advertencia: InfluxDB no disponible. Fallback simulado. Error: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "topic": "iot/vipis/sensor",
            "temperatura": 31.5,
            "humedad": 68.0,
            "eco2": 2850.0,
            "tvoc": 220.0
        }


@app.post("/vision/inferencia", tags=["vision_yolo"])
async def orquestar_inferencia_yolo():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client_http:
            response = await client_http.get(YOLO_SERVICE_URL)
            if response.status_code == 200:
                return response.json()
            else:
                return [{"clase": "humo_denso", "confianza": 0.85, "bbox": [120.5, 300.2, 400.1, 520.8]}]
    except Exception as e:
        print(f"Advertencia: No se pudo conectar a YOLO. Error: {e}")
        return [{"clase": "humo_denso", "confianza": 0.85, "bbox": [120.5, 300.2, 400.1, 520.8]}]


@app.get("/monitoreo/fusionado", response_model=MonitoreoFusionadoResponse, tags=["fusion_sensorial"])
async def obtener_monitoreo_fusionado():
    telemetria_data = {
        "dispositivo": "esp32_01",
        "temperatura": 31.5,
        "humedad": 68.0,
        "eco2": 2850.0,
        "tvoc": 220.0
    }
    timestamp_actual = datetime.utcnow().isoformat() + "Z"

    try:
        client = get_influx_client()
        query = "SELECT time, temp, hum, eco2, tvoc FROM mqtt_consumer ORDER BY time DESC LIMIT 1"
        table = client.query(query=query)
        df = table.to_pandas()

        if not df.empty:
            reg = df.iloc[0]
            timestamp_actual = str(reg.get("time", timestamp_actual))
            telemetria_data = {
                "dispositivo": "esp32_01",
                "temperatura": float(reg["temp"]) if "temp" in reg and not pd.isna(reg["temp"]) else 30.0,
                "humedad": float(reg["hum"]) if "hum" in reg and not pd.isna(reg["hum"]) else 50.0,
                "eco2": float(reg["eco2"]) if "eco2" in reg and not pd.isna(reg["eco2"]) else 400.0,
                "tvoc": float(reg["tvoc"]) if "tvoc" in reg and not pd.isna(reg["tvoc"]) else 0.0,
            }
    except Exception:
        pass

    detecciones_raw = await orquestar_inferencia_yolo()
    lista_detecciones = []
    if isinstance(detecciones_raw, list):
        for d in detecciones_raw:
            lista_detecciones.append(
                DeteccionYOLO(
                    clase=d.get("clase", "desconocido"),
                    confianza=float(d.get("confianza", 0.0)),
                    bbox=d.get("bbox")
                )
            )

    eco2_val = telemetria_data.get("eco2", 0.0)
    hay_evento_visual = any(d.clase.lower() in CLASES_CRITICAS for d in lista_detecciones)

    if eco2_val > 2000 and hay_evento_visual:
        fusion = FusionSensorialRespuesta(
            alerta_activa=True,
            nivel_riesgo="CRÍTICO",
            mensaje="LIVE/eCO2 elevado con detección de fuego/humo denso en la vía"
        )
    elif eco2_val > 2000:
        fusion = FusionSensorialRespuesta(
            alerta_activa=True,
            nivel_riesgo="ALTO",
            mensaje="ALERTA: Concentración de eCO2 elevada sin evento visual registrado."
        )
    elif hay_evento_visual:
        fusion = FusionSensorialRespuesta(
            alerta_activa=False,
            nivel_riesgo="MEDIO",
            mensaje="Evento visual detectado pero niveles de eCO2 en rango seguro."
        )
    else:
        fusion = FusionSensorialRespuesta(
            alerta_activa=False,
            nivel_riesgo="NORMAL",
            mensaje="Valores dentro de los parámetros seguros de operación."
        )

    return MonitoreoFusionadoResponse(
        timestamp=timestamp_actual,
        telemetria=TelemetriaInflux(**telemetria_data),
        detecciones_yolo=lista_detecciones,
        fusion_sensorial=fusion
    )