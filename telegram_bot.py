import os
import re
import requests

from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VIPIS_API_URL = os.getenv(
    "VIPIS_API_URL",
    "http://127.0.0.1:8000"
)


# ============================================================
# ENVÍO DE ALERTAS AUTOMÁTICAS
# ============================================================

async def enviar_mensaje_telegram(mensaje: str) -> bool:

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram no está configurado.")
        return False

    ids = [
        chat_id.strip()
        for chat_id in TELEGRAM_CHAT_ID.split(",")
        if chat_id.strip()
    ]

    try:

        from telegram import Bot

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        for chat_id in ids:

            await bot.send_message(
                chat_id=chat_id,
                text=mensaje
            )

        print("Mensaje enviado correctamente a Telegram.")

        return True

    except Exception as e:

        print(f"Error enviando mensaje a Telegram: {e}")

        return False


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mensaje = (
        "🤖 *VIPIS - Calidad del Aire*\n\n"
        "Bienvenido al sistema de monitoreo.\n\n"
        "Puedes realizar consultas utilizando lenguaje natural.\n\n"
        "Ejemplos:\n"
        "📊 ¿Cuál es la última medición?\n"
        "🌿 ¿Cuál es la calidad del aire ahora?\n"
        "🌿 ¿Cómo está el aire hoy?\n"
        "📊 Dame el último valor del sensor\n"
        "📈 ¿Cuál es el promedio de las mediciones?\n"
        "🚨 ¿Hay alertas pendientes?\n"
        "📋 Muéstrame las últimas mediciones\n"
        "📡 ¿Qué dispositivos hay registrados?\n"
        "🔧 Atiende la alerta 2"
    )

    await update.message.reply_text(
        mensaje,
        parse_mode="Markdown"
    )


# ============================================================
# /ULTIMA
# ============================================================

async def ultima(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/mediciones/ultima",
            timeout=10
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible obtener la última medición."
            )

            return

        data = respuesta.json()

        mensaje = (
            "📊 *ÚLTIMA MEDICIÓN VIPIS*\n\n"
            f"🆔 Medición: {data['medicion_id']}\n"
            f"📡 Dispositivo: {data['dispositivo_id']}\n"
            f"📅 Fecha: {data['fecha_hora']}\n\n"
            f"🌫️ eCO₂: {data['eco2']} ppm\n"
            f"🧪 TVOC: {data['tvoc']} ppb\n"
            f"🌡️ Temperatura: {data['temperatura']} °C\n"
            f"💧 Humedad: "
            f"{data['humedad'] if data['humedad'] is not None else 'N/D'} %\n\n"
            f"⚠️ Riesgo: *{data['nivel_riesgo'] or 'N/D'}*"
        )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /ultima: {e}")

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# /MEDICIONES
# ============================================================

async def mediciones(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/mediciones?limit=10",
            timeout=10
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible obtener las mediciones."
            )

            return

        data = respuesta.json()

        mediciones_data = data.get(
            "mediciones",
            []
        )

        if not mediciones_data:

            await update.message.reply_text(
                "📭 No hay mediciones registradas."
            )

            return

        mensaje = "📋 *ÚLTIMAS MEDICIONES VIPIS*\n\n"

        for medicion in mediciones_data:

            mensaje += (
                f"🆔 *#{medicion['medicion_id']}*\n"
                f"🌫️ eCO₂: {medicion['eco2']} ppm\n"
                f"🧪 TVOC: {medicion['tvoc']} ppb\n"
                f"🌡️ Temp: {medicion['temperatura']} °C\n"
                f"💧 Humedad: "
                f"{medicion['humedad'] if medicion['humedad'] is not None else 'N/D'} %\n"
                f"⚠️ Riesgo: "
                f"{medicion['nivel_riesgo'] or 'N/D'}\n"
                f"📅 {medicion['fecha_hora']}\n\n"
            )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /mediciones: {e}")

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# /ALERTAS
# ============================================================

async def alertas(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/alertas/pendientes",
            timeout=10
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible consultar las alertas."
            )

            return

        data = respuesta.json()

        if not data:

            await update.message.reply_text(
                "✅ No hay alertas pendientes."
            )

            return

        mensaje = "🚨 *ALERTAS PENDIENTES*\n\n"

        for alerta in data:

            valores = alerta.get(
                "valores",
                {}
            )

            riesgo = alerta.get(
                "nivel_riesgo",
                {}
            )

            mensaje += (
                f"🔴 *Alerta #{alerta['alerta_id']}*\n"
                f"📊 Medición: {alerta['medicion_id']}\n"
                f"🌫️ eCO₂: "
                f"{valores.get('eco2', 'N/D')} ppm\n"
                f"🧪 TVOC: "
                f"{valores.get('tvoc', 'N/D')} ppb\n"
                f"⚠️ Riesgo: "
                f"*{riesgo.get('nombre', 'N/D')}*\n"
                f"📝 {alerta.get('descripcion', '')}\n\n"
            )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /alertas: {e}")

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# /ATENDER ID
# ============================================================

async def atender(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "⚠️ Debes indicar el ID de la alerta.\n\n"
            "Ejemplo:\n"
            "/atender 2"
        )

        return

    alerta_id = context.args[0]

    try:

        alerta_id = int(alerta_id)

    except ValueError:

        await update.message.reply_text(
            "❌ El ID de la alerta debe ser un número."
        )

        return

    try:

        respuesta = requests.put(
            f"{VIPIS_API_URL}/alertas/{alerta_id}/atender",
            timeout=10
        )

        if respuesta.status_code == 200:

            data = respuesta.json()

            await update.message.reply_text(
                f"✅ Alerta #{alerta_id} atendida correctamente.\n\n"
                f"Estado: {data.get('mensaje', 'Atendida')}"
            )

        elif respuesta.status_code == 404:

            await update.message.reply_text(
                f"❌ No existe la alerta #{alerta_id}."
            )

        else:

            await update.message.reply_text(
                f"❌ No fue posible atender la alerta #{alerta_id}."
            )

    except Exception as e:

        print(f"Error en /atender: {e}")

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# ESTADÍSTICA ESPECÍFICA
# ============================================================

async def obtener_estadistica_especifica(
    update: Update,
    tipo: str,
    operacion: str
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/mediciones/estadisticas",
            timeout=30
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible obtener las estadísticas."
            )

            return

        data = respuesta.json()

        # --------------------------------------------------------
        # Normalizar operación
        # --------------------------------------------------------

        operacion = operacion.lower().strip()

        equivalencias = {

            "promedio": "promedio",
            "media": "promedio",

            "maximo": "maximo",
            "máximo": "maximo",
            "maxima": "maximo",
            "máxima": "maximo",

            "minimo": "minimo",
            "mínimo": "minimo",
            "minima": "minimo",
            "mínima": "minimo"
        }

        operacion = equivalencias.get(
            operacion
        )

        if operacion is None:

            await update.message.reply_text(
                "❌ No pude identificar si solicitas "
                "el promedio, máximo o mínimo."
            )

            return

        configuracion = {

            "eco2": {

                "nombre": "eCO₂",
                "unidad": "ppm",

                "promedio":
                    "promedio_eco2_todas_las_mediciones",

                "maximo":
                    "maximo_eco2_todas_las_mediciones",

                "minimo":
                    "minimo_eco2_todas_las_mediciones"
            },

            "tvoc": {

                "nombre": "TVOC",
                "unidad": "ppb",

                "promedio":
                    "promedio_tvoc_todas_las_mediciones",

                "maximo":
                    "maximo_tvoc_todas_las_mediciones",

                "minimo":
                    "minimo_tvoc_todas_las_mediciones"
            },

            "temperatura": {

                "nombre": "temperatura",
                "unidad": "°C",

                "promedio":
                    "promedio_temperatura_todas_las_mediciones",

                "maximo":
                    "maximo_temperatura_todas_las_mediciones",

                "minimo":
                    "minimo_temperatura_todas_las_mediciones"
            },

            "humedad": {

                "nombre": "humedad",
                "unidad": "%",

                "promedio":
                    "promedio_humedad_todas_las_mediciones",

                "maximo":
                    "maximo_humedad_todas_las_mediciones",

                "minimo":
                    "minimo_humedad_todas_las_mediciones"
            }
        }

        if tipo not in configuracion:

            await update.message.reply_text(
                "❌ No pude identificar el tipo de medición solicitado."
            )

            return

        datos = configuracion[tipo]

        valor = data.get(
            datos[operacion],
            "N/D"
        )

        total = data.get(
            "total_mediciones",
            "N/D"
        )

        nombres_operacion = {

            "promedio": "promedio",
            "maximo": "máximo",
            "minimo": "mínimo"
        }

        nombre_operacion = nombres_operacion[
            operacion
        ]

        mensaje = (
            f"📊 *{datos['nombre'].upper()}*\n\n"
            f"El {nombre_operacion} de "
            f"{datos['nombre']} "
            f"en las {total} mediciones "
            f"registradas es:\n\n"
            f"📌 *{valor} {datos['unidad']}*"
        )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo estadística específica: {e}"
        )

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# ESTADÍSTICAS PARA TELEGRAM
# ============================================================

async def obtener_estadisticas_telegram(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/mediciones/estadisticas",
            timeout=30
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible obtener las estadísticas."
            )

            return

        data = respuesta.json()

        mensaje = (
            "📈 *ESTADÍSTICAS VIPIS*\n\n"

            f"📊 Total de mediciones: "
            f"{data.get('total_mediciones', 'N/D')}\n"

            f"🚨 Mediciones críticas: "
            f"{data.get('mediciones_criticas', 'N/D')}\n\n"

            "🌫️ *eCO₂*\n"

            f"Promedio: "
            f"{data.get('promedio_eco2_todas_las_mediciones', 'N/D')} ppm\n"

            f"Máximo: "
            f"{data.get('maximo_eco2_todas_las_mediciones', 'N/D')} ppm\n"

            f"Mínimo: "
            f"{data.get('minimo_eco2_todas_las_mediciones', 'N/D')} ppm\n\n"

            "🧪 *TVOC*\n"

            f"Promedio: "
            f"{data.get('promedio_tvoc_todas_las_mediciones', 'N/D')} ppb\n"

            f"Máximo: "
            f"{data.get('maximo_tvoc_todas_las_mediciones', 'N/D')} ppb\n"

            f"Mínimo: "
            f"{data.get('minimo_tvoc_todas_las_mediciones', 'N/D')} ppb\n\n"

            "🌡️ *Temperatura*\n"

            f"Promedio: "
            f"{data.get('promedio_temperatura_todas_las_mediciones', 'N/D')} °C\n"

            f"Máximo: "
            f"{data.get('maximo_temperatura_todas_las_mediciones', 'N/D')} °C\n"

            f"Mínimo: "
            f"{data.get('minimo_temperatura_todas_las_mediciones', 'N/D')} °C\n\n"

            "💧 *Humedad*\n"

            f"Promedio: "
            f"{data.get('promedio_humedad_todas_las_mediciones', 'N/D')} %\n"

            f"Máximo: "
            f"{data.get('maximo_humedad_todas_las_mediciones', 'N/D')} %\n"

            f"Mínimo: "
            f"{data.get('minimo_humedad_todas_las_mediciones', 'N/D')} %"
        )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo estadísticas: {e}"
        )

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# DISPOSITIVOS PARA TELEGRAM
# ============================================================

async def obtener_dispositivos_telegram(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/dispositivos",
            timeout=10
        )

        if respuesta.status_code != 200:

            await update.message.reply_text(
                "❌ No fue posible obtener los dispositivos."
            )

            return

        data = respuesta.json()

        if not data:

            await update.message.reply_text(
                "📭 No hay dispositivos registrados."
            )

            return

        mensaje = "📡 *DISPOSITIVOS VIPIS*\n\n"

        for dispositivo in data:

            mensaje += (
                f"🆔 ID: "
                f"{dispositivo.get('id', 'N/D')}\n"

                f"📡 Código: "
                f"{dispositivo.get('codigo', 'N/D')}\n"

                f"📍 Ubicación ID: "
                f"{dispositivo.get('ubicacion_id', 'N/D')}\n"

                f"👤 Usuario ID: "
                f"{dispositivo.get('usuario_id', 'N/D')}\n\n"
            )

        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo dispositivos: {e}"
        )

        await update.message.reply_text(
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# LENGUAJE NATURAL
# ============================================================

async def procesar_mensaje(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message or not update.message.text:
        return

    texto_original = update.message.text.strip()
    texto = texto_original.lower()

    print(
        f"📩 Mensaje recibido: {texto_original}"
    )

    print(
        f"🆔 chat_id: {update.effective_chat.id} | "
        f"usuario: {update.effective_user.first_name} "
        f"(@{update.effective_user.username})"
    )


    # ========================================================
    # CALIDAD DEL AIRE ACTUAL
    # ========================================================
    #
    # Estas preguntas se interpretan como una consulta
    # de la última medición registrada.
    #
    # Ejemplos:
    # ¿Cuál es la calidad del aire ahora?
    # ¿Cómo está el aire?
    # ¿Cómo está la calidad del aire hoy?
    # ¿Cuál es el estado actual del aire?
    # ========================================================

    palabras_calidad_aire = [

        "calidad del aire",

        "como esta el aire",
        "cómo está el aire",

        "como esta la calidad del aire",
        "cómo está la calidad del aire",

        "estado del aire",

        "estado actual del aire",

        "calidad actual del aire",

        "calidad del aire actual",

        "calidad del aire ahora",

        "calidad del aire hoy",

        "aire actualmente",

        "aire ahora",

        "aire hoy",

        "nivel de riesgo actual",

        "riesgo actual"
    ]

    if any(
        palabra in texto
        for palabra in palabras_calidad_aire
    ):

        await ultima(
            update,
            context
        )

        return


    # ========================================================
    # ÚLTIMA MEDICIÓN
    # ========================================================

    palabras_ultima = [

        "última medición",
        "ultima medicion",

        "último valor",
        "ultimo valor",

        "última lectura",
        "ultima lectura",

        "último registro",
        "ultimo registro",

        "últimos valores",
        "ultimos valores"
    ]

    if any(
        palabra in texto
        for palabra in palabras_ultima
    ):

        await ultima(
            update,
            context
        )

        return


    # ========================================================
    # ESTADÍSTICAS ESPECÍFICAS
    # ========================================================

    operaciones = [

        "promedio",
        "media",

        "máximo",
        "maximo",

        "máxima",
        "maxima",

        "mínimo",
        "minimo",

        "mínima",
        "minima"
    ]


    # ========================================================
    # eCO₂
    # ========================================================

    if (
        (
            "eco2" in texto
            or "ec02" in texto
            or "co2" in texto
            or "eco₂" in texto
        )
        and any(
            palabra in texto
            for palabra in operaciones
        )
    ):

        if (
            "promedio" in texto
            or "media" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "eco2",
                "promedio"
            )

            return

        if (
            "máximo" in texto
            or "maximo" in texto
            or "máxima" in texto
            or "maxima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "eco2",
                "maximo"
            )

            return

        if (
            "mínimo" in texto
            or "minimo" in texto
            or "mínima" in texto
            or "minima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "eco2",
                "minimo"
            )

            return


    # ========================================================
    # TVOC
    # ========================================================

    if (
        "tvoc" in texto
        and any(
            palabra in texto
            for palabra in operaciones
        )
    ):

        if (
            "promedio" in texto
            or "media" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "tvoc",
                "promedio"
            )

            return

        if (
            "máximo" in texto
            or "maximo" in texto
            or "máxima" in texto
            or "maxima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "tvoc",
                "maximo"
            )

            return

        if (
            "mínimo" in texto
            or "minimo" in texto
            or "mínima" in texto
            or "minima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "tvoc",
                "minimo"
            )

            return


    # ========================================================
    # TEMPERATURA
    # ========================================================

    if (
        (
            "temperatura" in texto
            or "temp" in texto
        )
        and any(
            palabra in texto
            for palabra in operaciones
        )
    ):

        if (
            "promedio" in texto
            or "media" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "temperatura",
                "promedio"
            )

            return

        if (
            "máximo" in texto
            or "maximo" in texto
            or "máxima" in texto
            or "maxima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "temperatura",
                "maximo"
            )

            return

        if (
            "mínimo" in texto
            or "minimo" in texto
            or "mínima" in texto
            or "minima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "temperatura",
                "minimo"
            )

            return


    # ========================================================
    # HUMEDAD
    # ========================================================

    if (
        "humedad" in texto
        and any(
            palabra in texto
            for palabra in operaciones
        )
    ):

        if (
            "promedio" in texto
            or "media" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "humedad",
                "promedio"
            )

            return

        if (
            "máximo" in texto
            or "maximo" in texto
            or "máxima" in texto
            or "maxima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "humedad",
                "maximo"
            )

            return

        if (
            "mínimo" in texto
            or "minimo" in texto
            or "mínima" in texto
            or "minima" in texto
        ):

            await obtener_estadistica_especifica(
                update,
                "humedad",
                "minimo"
            )

            return


    # ========================================================
    # ESTADÍSTICAS GENERALES
    # ========================================================

    palabras_estadisticas = [

        "promedio",
        "promedios",
        "media",

        "estadística",
        "estadisticas",
        "estadísticas",

        "máximo",
        "maximo",
        "máxima",
        "maxima",

        "mínimo",
        "minimo",
        "mínima",
        "minima"
    ]

    if any(
        palabra in texto
        for palabra in palabras_estadisticas
    ):

        await obtener_estadisticas_telegram(
            update,
            context
        )

        return


    # ========================================================
    # ALERTAS
    # ========================================================

    palabras_alertas = [

        "alerta",
        "alertas",

        "riesgo",
        "riesgos",

        "pendiente",
        "pendientes"
    ]

    if any(
        palabra in texto
        for palabra in palabras_alertas
    ):

        if not any(
            palabra in texto
            for palabra in [
                "atender",
                "atiende",
                "atendida",
                "atendido"
            ]
        ):

            await alertas(
                update,
                context
            )

            return


    # ========================================================
    # ATENDER ALERTA
    # ========================================================

    palabras_atender = [

        "atender",
        "atiende",
        "atendida",
        "atendido"
    ]

    if any(
        palabra in texto
        for palabra in palabras_atender
    ):

        numeros = re.findall(
            r"\d+",
            texto
        )

        if not numeros:

            await update.message.reply_text(
                "⚠️ Indica el número de la alerta "
                "que deseas atender.\n\n"
                "Ejemplo: Atiende la alerta 2"
            )

            return

        alerta_id = numeros[0]

        try:

            respuesta = requests.put(
                f"{VIPIS_API_URL}/alertas/"
                f"{alerta_id}/atender",
                timeout=10
            )

            if respuesta.status_code == 200:

                data = respuesta.json()

                await update.message.reply_text(
                    f"✅ Alerta #{alerta_id} "
                    f"atendida correctamente.\n\n"
                    f"Estado: "
                    f"{data.get('mensaje', 'Atendida')}"
                )

            elif respuesta.status_code == 404:

                await update.message.reply_text(
                    f"❌ No existe la alerta #{alerta_id}."
                )

            else:

                await update.message.reply_text(
                    f"❌ No fue posible atender "
                    f"la alerta #{alerta_id}."
                )

        except Exception as e:

            print(
                f"Error atendiendo alerta: {e}"
            )

            await update.message.reply_text(
                "❌ Error conectando con la API VIPIS."
            )

        return


    # ========================================================
    # ÚLTIMAS MEDICIONES
    # ========================================================

    palabras_mediciones = [

        "mediciones",
        "medición",
        "medicion",

        "registros",
        "registro",

        "lecturas",
        "lectura"
    ]

    if any(
        palabra in texto
        for palabra in palabras_mediciones
    ):

        await mediciones(
            update,
            context
        )

        return


    # ========================================================
    # DISPOSITIVOS / SENSORES
    # ========================================================

    palabras_dispositivos = [

        "dispositivo",
        "dispositivos",

        "sensor",
        "sensores"
    ]

    if any(
        palabra in texto
        for palabra in palabras_dispositivos
    ):

        await obtener_dispositivos_telegram(
            update,
            context
        )

        return


    # ========================================================
    # AYUDA
    # ========================================================

    palabras_ayuda = [

        "ayuda",

        "qué puedo preguntar",
        "que puedo preguntar",

        "qué puedes hacer",
        "que puedes hacer"
    ]

    if any(
        palabra in texto
        for palabra in palabras_ayuda
    ):

        await update.message.reply_text(

            "🤖 *Asistente VIPIS*\n\n"

            "Puedes preguntarme, por ejemplo:\n\n"

            "📊 ¿Cuál es la última medición?\n"
            "🌿 ¿Cuál es la calidad del aire ahora?\n"
            "🌿 ¿Cómo está el aire hoy?\n"
            "📊 Dame el último valor del sensor\n"
            "📈 ¿Cuál es el promedio de eCO₂?\n"
            "📈 ¿Cuál es la temperatura mínima?\n"
            "📈 ¿Cuál es la temperatura máxima?\n"
            "📈 Dame las estadísticas\n"
            "📋 Muéstrame las últimas mediciones\n"
            "🚨 ¿Hay alertas pendientes?\n"
            "📡 ¿Qué dispositivos hay registrados?\n"
            "🔧 Atiende la alerta 2",

            parse_mode="Markdown"
        )

        return


    # ========================================================
    # MENSAJE NO RECONOCIDO
    # ========================================================

    await update.message.reply_text(

        "🤖 No pude interpretar la consulta.\n\n"

        "Puedes preguntarme cosas como:\n\n"

        "• ¿Cuál es la última medición?\n"
        "• ¿Cuál es la calidad del aire ahora?\n"
        "• ¿Cómo está el aire hoy?\n"
        "• Dame el promedio de las mediciones\n"
        "• ¿Cuál es la temperatura mínima?\n"
        "• ¿Cuál es la temperatura máxima?\n"
        "• ¿Hay alertas pendientes?\n"
        "• ¿Qué dispositivos hay registrados?\n"
        "• Atiende la alerta 2"
    )


# ============================================================
# INICIAR BOT
# ============================================================

def iniciar_bot():

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN no está configurado."
        )

        return

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )


    # ========================================================
    # COMANDOS EXISTENTES
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "ultima",
            ultima
        )
    )

    application.add_handler(
        CommandHandler(
            "mediciones",
            mediciones
        )
    )

    application.add_handler(
        CommandHandler(
            "alertas",
            alertas
        )
    )

    application.add_handler(
        CommandHandler(
            "atender",
            atender
        )
    )


    # ========================================================
    # LENGUAJE NATURAL
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            procesar_mensaje
        )
    )


    print(
        "🤖 Bot de Telegram iniciado."
    )

    print(
        "💬 Modo de lenguaje natural activado."
    )

    application.run_polling()


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    iniciar_bot()