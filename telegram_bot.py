import os
import re
import requests
from io import BytesIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VIPIS_API_URL = os.getenv(
    "VIPIS_API_URL",
    f"http://127.0.0.1:{os.getenv('PORT', '8000')}"
)


# ============================================================
# FUNCIONES AUXILIARES DE RESPUESTA Y TECLADOS
# ============================================================

def teclado_menu_principal() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Última medición", callback_data="ultima"),
            InlineKeyboardButton("📋 Mediciones", callback_data="mediciones")
        ],
        [
            InlineKeyboardButton("📈 Estadísticas", callback_data="menu_estadisticas"),
            InlineKeyboardButton("🚨 Alertas", callback_data="alertas")
        ],
        [
            InlineKeyboardButton("📡 Dispositivos", callback_data="dispositivos"),
            InlineKeyboardButton("🤖 Ayuda", callback_data="ayuda")
        ],
        [
            InlineKeyboardButton("🔒 Control LED", callback_data="menu_led"),
            InlineKeyboardButton("📊 Gráficos", callback_data="menu_graficos")
        ]
    ])


def teclado_estadisticas() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 General", callback_data="stats_general"),
            InlineKeyboardButton("🕐 Promedio 24h", callback_data="stats_24h")
        ],
        [
            InlineKeyboardButton("📈 Max/Min día", callback_data="stats_maxmin"),
            InlineKeyboardButton("🔴 Días críticos", callback_data="stats_criticos")
        ],
        [InlineKeyboardButton("⬅️ Volver", callback_data="menu")]
    ])


def teclado_volver() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver al menú", callback_data="menu")]
    ])


async def enviar_respuesta(
    update: Update,
    texto: str,
    parse_mode: str = "Markdown",
    reply_markup=None
):
    if update.callback_query:
        await update.callback_query.answer()
        if reply_markup is None:
            reply_markup = teclado_volver()
        try:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except Exception:
            await update.callback_query.message.reply_text(
                texto,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
    else:
        await update.message.reply_text(
            texto,
            parse_mode=parse_mode,
            reply_markup=reply_markup
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
        "Bienvenido al sistema de monitoreo de la "
        "Vía Parque Isla de Salamanca.\n\n"
        "Selecciona una opción del menú o escribe "
        "tu consulta en lenguaje natural."
    )

    await enviar_respuesta(
        update,
        mensaje,
        reply_markup=teclado_menu_principal()
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

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /ultima: {e}")

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
                "❌ No fue posible obtener las mediciones."
            )

            return

        data = respuesta.json()

        mediciones_data = data.get(
            "mediciones",
            []
        )

        if not mediciones_data:

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /mediciones: {e}")

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
                "❌ No fue posible consultar las alertas."
            )

            return

        data = respuesta.json()

        if not data:

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(f"Error en /alertas: {e}")

        await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            "⚠️ Debes indicar el ID de la alerta.\n\n"
            "Ejemplo:\n"
            "/atender 2"
        )

        return

    alerta_id = context.args[0]

    try:

        alerta_id = int(alerta_id)

    except ValueError:

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
                f"✅ Alerta #{alerta_id} atendida correctamente.\n\n"
                f"Estado: {data.get('mensaje', 'Atendida')}"
            )

        elif respuesta.status_code == 404:

            await enviar_respuesta(update, 
                f"❌ No existe la alerta #{alerta_id}."
            )

        else:

            await enviar_respuesta(update, 
                f"❌ No fue posible atender la alerta #{alerta_id}."
            )

    except Exception as e:

        print(f"Error en /atender: {e}")

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo estadística específica: {e}"
        )

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo estadísticas: {e}"
        )

        await enviar_respuesta(update, 
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

            await enviar_respuesta(update, 
                "❌ No fue posible obtener los dispositivos."
            )

            return

        data = respuesta.json()

        if not data:

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 
            mensaje,
            parse_mode="Markdown"
        )

    except Exception as e:

        print(
            f"Error obteniendo dispositivos: {e}"
        )

        await enviar_respuesta(update, 
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# ESTADÍSTICAS ADICIONALES (PROMEDIO 24H, MAX/MIN DÍA, DÍAS CRÍTICOS)
# ============================================================

async def estadistica_promedio_24h(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/stats/promedio-24h",
            timeout=10
        )

        if respuesta.status_code != 200:

            await enviar_respuesta(
                update,
                "❌ No fue posible obtener el promedio de 24h."
            )

            return

        data = respuesta.json()

        mensaje = (
            "🕐 *PROMEDIO eCO₂ - ÚLTIMAS 24 HORAS*\n\n"
            f"📊 Promedio: {data.get('promedio_eco2', 'N/D')} ppm"
        )

        await enviar_respuesta(update, mensaje)

    except Exception as e:

        print(f"Error en promedio 24h: {e}")

        await enviar_respuesta(
            update,
            "❌ Error conectando con la API VIPIS."
        )


async def estadistica_max_min_dia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/stats/max-min-dia",
            timeout=10
        )

        if respuesta.status_code != 200:

            await enviar_respuesta(
                update,
                "❌ No fue posible obtener el máximo y mínimo del día."
            )

            return

        data = respuesta.json()

        mensaje = (
            "📈 *MÁXIMO Y MÍNIMO DE HOY (eCO₂)*\n\n"
            f"⬆️ Máximo: {data.get('maximo', 'N/D')} ppm\n"
            f"⬇️ Mínimo: {data.get('minimo', 'N/D')} ppm"
        )

        await enviar_respuesta(update, mensaje)

    except Exception as e:

        print(f"Error en max/min día: {e}")

        await enviar_respuesta(
            update,
            "❌ Error conectando con la API VIPIS."
        )


async def estadistica_dias_criticos(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        respuesta = requests.get(
            f"{VIPIS_API_URL}/stats/dias-criticos",
            timeout=10
        )

        if respuesta.status_code != 200:

            await enviar_respuesta(
                update,
                "❌ No fue posible obtener los días críticos."
            )

            return

        data = respuesta.json()

        total = data.get("total_dias_criticos", 0)

        if total == 0:

            await enviar_respuesta(
                update,
                "✅ No hay días críticos registrados."
            )

            return

        mensaje = f"🔴 *DÍAS CRÍTICOS ({total})*\n\n"

        for dia in data.get("dias_criticos", []):

            mensaje += (
                f"📅 {dia.get('dia', 'N/D')}\n"
                f"📊 Promedio: {dia.get('promedio', 'N/D')} ppm\n\n"
            )

        await enviar_respuesta(update, mensaje)

    except Exception as e:

        print(f"Error en días críticos: {e}")

        await enviar_respuesta(
            update,
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# AYUDA
# ============================================================

async def mostrar_ayuda(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mensaje = (
        "🤖 *Asistente VIPIS*\n\n"
        "Puedes preguntarme o usar los botones:\n\n"
        "📊 ¿Cuál es la última medición?\n"
        "🌿 ¿Cuál es la calidad del aire ahora?\n"
        "📈 ¿Cuál es el promedio de eCO₂?\n"
        "📋 Muéstrame las últimas mediciones\n"
        "🚨 ¿Hay alertas pendientes?\n"
        "📡 ¿Qué dispositivos hay registrados?\n"
        "🔧 Atiende la alerta 2\n"
        "💡 Enciende el LED\n"
        "🌑 Apaga el LED\n"
        "📊 Muéstrame un gráfico de eCO₂\n"
        "📈 Dibuja la tendencia de eCO₂\n\n"
        "Cualquier otra consulta será interpretada por IA."
    )

    await enviar_respuesta(update, mensaje)


async def comando_led(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mensaje = "🔒 *CONTROL DEL LED*\n\nSelecciona una acción:"

    await enviar_respuesta(update, mensaje, reply_markup=teclado_led())


async def comando_graficos(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mensaje = "📊 *GRÁFICOS VIPIS*\n\nSelecciona un gráfico:"

    await enviar_respuesta(update, mensaje, reply_markup=teclado_graficos())


# ============================================================
# CONTROL DEL LED (ESP32)
# ============================================================

def teclado_led() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Encender", callback_data="led_on"),
            InlineKeyboardButton("🌑 Apagar", callback_data="led_off")
        ],
        [
            InlineKeyboardButton("📋 Ver estado", callback_data="led_estado"),
            InlineKeyboardButton("⬅️ Volver", callback_data="menu")
        ]
    ])


def teclado_graficos() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 eCO₂ por hora", callback_data="grafico_hora"),
            InlineKeyboardButton("📊 Registros por día", callback_data="grafico_dia")
        ],
        [
            InlineKeyboardButton("📉 Tendencia eCO₂", callback_data="grafico_tendencia"),
            InlineKeyboardButton("⬅️ Volver", callback_data="menu")
        ]
    ])


async def controlar_led(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    accion: str
):
    try:
        if accion == "estado":
            respuesta = requests.get(
                f"{VIPIS_API_URL}/led",
                timeout=10
            )
            if respuesta.status_code == 200:
                data = respuesta.json()
                estado = data.get("estado", "N/D")
                emoji = "💡" if estado == "on" else "🌑"
                mensaje = (
                    f"🔒 *ESTADO DEL LED*\n\n"
                    f"{emoji} El LED está *{estado.upper()}*"
                )
                await enviar_respuesta(update, mensaje)
            else:
                await enviar_respuesta(
                    update,
                    "❌ No fue posible consultar el estado del LED."
                )
        else:
            respuesta = requests.post(
                f"{VIPIS_API_URL}/led",
                json={"estado": accion},
                timeout=10
            )
            if respuesta.status_code == 200:
                if accion == "on":
                    mensaje = "✅ LED *ENCENDIDO* correctamente."
                else:
                    mensaje = "✅ LED *APAGADO* correctamente."
                await enviar_respuesta(update, mensaje)
            else:
                await enviar_respuesta(
                    update,
                    "❌ No fue posible cambiar el estado del LED."
                )
    except Exception as e:
        print(f"Error controlando LED: {e}")
        await enviar_respuesta(
            update,
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# GRÁFICOS CON MATPLOTLIB
# ============================================================

async def enviar_foto(
    update: Update,
    bio: BytesIO,
    caption: str = None
):
    bio.name = "grafico.png"
    bio.seek(0)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_photo(
            photo=bio,
            caption=caption
        )
    else:
        await update.message.reply_photo(
            photo=bio,
            caption=caption
        )


async def generar_grafico_eco2_hora(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        respuesta = requests.get(
            f"{VIPIS_API_URL}/stats/promedio-por-hora",
            timeout=15
        )
        if respuesta.status_code != 200:
            await enviar_respuesta(
                update,
                "❌ No fue posible obtener los datos."
            )
            return

        data = respuesta.json()
        datos = data.get("datos", [])

        if not datos:
            await enviar_respuesta(
                update,
                "📭 No hay datos suficientes para generar el gráfico."
            )
            return

        datos = list(reversed(datos))
        valores = [d["promedio_eco2"] for d in datos]
        etiquetas = []
        for d in datos:
            hora_str = d.get("hora", "")
            etiquetas.append(
                hora_str.split("T")[1][:5] if "T" in hora_str else hora_str[:5]
            )

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(
            range(len(valores)),
            valores,
            marker='o',
            linewidth=2,
            color='#2196F3'
        )
        ax.fill_between(
            range(len(valores)),
            valores,
            alpha=0.15,
            color='#2196F3'
        )
        ax.set_title(
            "Promedio eCO₂ por hora (ppm)",
            fontsize=14,
            fontweight='bold'
        )
        ax.set_xlabel("Hora")
        ax.set_ylabel("eCO₂ (ppm)")

        n = max(1, len(etiquetas) // 6)
        ax.set_xticks(range(0, len(etiquetas), n))
        ax.set_xticklabels(
            etiquetas[::n],
            rotation=45,
            ha='right'
        )

        ax.grid(True, alpha=0.3)
        ax.axhline(
            y=1000,
            color='red',
            linestyle='--',
            alpha=0.5,
            label='Crítico (1000 ppm)'
        )
        ax.legend()

        plt.tight_layout()

        bio = BytesIO()
        fig.savefig(bio, format='png', dpi=100)
        plt.close(fig)

        await enviar_foto(
            update,
            bio,
            "📈 Promedio de eCO₂ por hora"
        )

    except Exception as e:
        print(f"Error generando gráfico eCO2 por hora: {e}")
        await enviar_respuesta(
            update,
            "❌ Error generando el gráfico."
        )


async def generar_grafico_registros_dia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        respuesta = requests.get(
            f"{VIPIS_API_URL}/stats/registros-por-dia",
            timeout=15
        )
        if respuesta.status_code != 200:
            await enviar_respuesta(
                update,
                "❌ No fue posible obtener los datos."
            )
            return

        data = respuesta.json()
        datos = data.get("datos", [])

        if not datos:
            await enviar_respuesta(
                update,
                "📭 No hay datos suficientes para generar el gráfico."
            )
            return

        datos = list(reversed(datos))
        dias = [d["dia"] for d in datos]
        registros = [d["registros"] for d in datos]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(
            range(len(registros)),
            registros,
            color='#4CAF50',
            alpha=0.8
        )
        ax.set_title(
            "Registros por día",
            fontsize=14,
            fontweight='bold'
        )
        ax.set_xlabel("Día")
        ax.set_ylabel("Cantidad de registros")

        n = max(1, len(dias) // 8)
        ax.set_xticks(range(0, len(dias), n))
        ax.set_xticklabels(
            [d[:10] for d in dias[::n]],
            rotation=45,
            ha='right'
        )

        ax.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        bio = BytesIO()
        fig.savefig(bio, format='png', dpi=100)
        plt.close(fig)

        await enviar_foto(
            update,
            bio,
            "📊 Registros por día"
        )

    except Exception as e:
        print(f"Error generando gráfico registros por día: {e}")
        await enviar_respuesta(
            update,
            "❌ Error generando el gráfico."
        )


async def generar_grafico_tendencia(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        respuesta = requests.get(
            f"{VIPIS_API_URL}/mediciones?limit=50",
            timeout=15
        )
        if respuesta.status_code != 200:
            await enviar_respuesta(
                update,
                "❌ No fue posible obtener los datos."
            )
            return

        data = respuesta.json()
        mediciones = data.get("mediciones", [])

        if not mediciones:
            await enviar_respuesta(
                update,
                "📭 No hay datos suficientes para generar el gráfico."
            )
            return

        mediciones = list(reversed(mediciones))
        eco2 = [
            m["eco2"] for m in mediciones
            if m.get("eco2") is not None
        ]

        if not eco2:
            await enviar_respuesta(
                update,
                "📭 No hay datos de eCO₂ para graficar."
            )
            return

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(
            range(len(eco2)),
            eco2,
            marker='.',
            linewidth=1.5,
            color='#FF5722'
        )
        ax.fill_between(
            range(len(eco2)),
            eco2,
            alpha=0.15,
            color='#FF5722'
        )
        ax.set_title(
            "Tendencia eCO₂ - Últimas 50 mediciones (ppm)",
            fontsize=14,
            fontweight='bold'
        )
        ax.set_xlabel("Mediciones (cronológico)")
        ax.set_ylabel("eCO₂ (ppm)")
        ax.grid(True, alpha=0.3)
        ax.axhline(
            y=1000,
            color='red',
            linestyle='--',
            alpha=0.5,
            label='Crítico (1000 ppm)'
        )
        ax.legend()

        plt.tight_layout()

        bio = BytesIO()
        fig.savefig(bio, format='png', dpi=100)
        plt.close(fig)

        await enviar_foto(
            update,
            bio,
            "📉 Tendencia de eCO₂"
        )

    except Exception as e:
        print(f"Error generando gráfico tendencia: {e}")
        await enviar_respuesta(
            update,
            "❌ Error generando el gráfico."
        )


# ============================================================
# CONSULTA CON IA (GEMINI)
# ============================================================

async def consultar_gemini(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str
):
    try:
        respuesta = requests.post(
            f"{VIPIS_API_URL}/chat",
            json={"texto": texto},
            timeout=30
        )

        if respuesta.status_code == 200:
            data = respuesta.json()
            respuesta_ia = data.get("respuesta", "")
            if respuesta_ia:
                await enviar_respuesta(update, f"🤖 {respuesta_ia}")
            else:
                await enviar_respuesta(
                    update,
                    "🤖 No pude interpretar tu consulta. "
                    "Escribe /ayuda para ver las opciones disponibles."
                )
        else:
            await enviar_respuesta(
                update,
                "🤖 No pude procesar tu consulta en este momento."
            )
    except Exception as e:
        print(f"Error consultando Gemini: {e}")
        await enviar_respuesta(
            update,
            "❌ Error conectando con la API VIPIS."
        )


# ============================================================
# MANEJO DE BOTONES INTERACTIVOS (CALLBACKS)
# ============================================================

async def manejar_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # Volver al menú principal
    if data == "menu":

        mensaje = (
            "🤖 *VIPIS - Calidad del Aire*\n\n"
            "Selecciona una opción del menú:"
        )

        await query.edit_message_text(
            mensaje,
            parse_mode="Markdown",
            reply_markup=teclado_menu_principal()
        )

        return

    # Sub-menú de estadísticas
    if data == "menu_estadisticas":

        await query.edit_message_text(
            "📈 *ESTADÍSTICAS VIPIS*\n\n"
            "Selecciona el tipo de estadística:",
            parse_mode="Markdown",
            reply_markup=teclado_estadisticas()
        )

        return

    # Datos: última medición
    if data == "ultima":

        await ultima(update, context)

        return

    # Datos: últimas mediciones
    if data == "mediciones":

        await mediciones(update, context)

        return

    # Datos: alertas pendientes
    if data == "alertas":

        await alertas(update, context)

        return

    # Datos: dispositivos
    if data == "dispositivos":

        await obtener_dispositivos_telegram(update, context)

        return

    # Datos: ayuda
    if data == "ayuda":

        await mostrar_ayuda(update, context)

        return

    # Datos: estadística general
    if data == "stats_general":

        await obtener_estadisticas_telegram(update, context)

        return

    # Datos: promedio 24h
    if data == "stats_24h":

        await estadistica_promedio_24h(update, context)

        return

    # Datos: max/min del día
    if data == "stats_maxmin":

        await estadistica_max_min_dia(update, context)

        return

    # Datos: días críticos
    if data == "stats_criticos":

        await estadistica_dias_criticos(update, context)

        return

    # Sub-menú LED
    if data == "menu_led":

        await query.edit_message_text(
            "🔒 *CONTROL DEL LED*\n\n"
            "Selecciona una acción:",
            parse_mode="Markdown",
            reply_markup=teclado_led()
        )

        return

    if data == "led_on":

        await controlar_led(update, context, "on")

        return

    if data == "led_off":

        await controlar_led(update, context, "off")

        return

    if data == "led_estado":

        await controlar_led(update, context, "estado")

        return

    # Sub-menú Gráficos
    if data == "menu_graficos":

        await query.edit_message_text(
            "📊 *GRÁFICOS VIPIS*\n\n"
            "Selecciona un gráfico:",
            parse_mode="Markdown",
            reply_markup=teclado_graficos()
        )

        return

    if data == "grafico_hora":

        await generar_grafico_eco2_hora(update, context)

        return

    if data == "grafico_dia":

        await generar_grafico_registros_dia(update, context)

        return

    if data == "grafico_tendencia":

        await generar_grafico_tendencia(update, context)

        return


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

            await enviar_respuesta(update, 
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

                await enviar_respuesta(update, 
                    f"✅ Alerta #{alerta_id} "
                    f"atendida correctamente.\n\n"
                    f"Estado: "
                    f"{data.get('mensaje', 'Atendida')}"
                )

            elif respuesta.status_code == 404:

                await enviar_respuesta(update, 
                    f"❌ No existe la alerta #{alerta_id}."
                )

            else:

                await enviar_respuesta(update, 
                    f"❌ No fue posible atender "
                    f"la alerta #{alerta_id}."
                )

        except Exception as e:

            print(
                f"Error atendiendo alerta: {e}"
            )

            await enviar_respuesta(update, 
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

        await enviar_respuesta(update, 

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
    # CONTROL DEL LED (LENGUAJE NATURAL)
    # ========================================================

    if (
        any(p in texto for p in ["enciende", "encender", "prende", "prender", "ilumina"])
        and any(p in texto for p in ["led", "luz", "bombillo"])
    ):

        await controlar_led(update, context, "on")

        return

    if (
        any(p in texto for p in ["apaga", "apagar", "apague"])
        and any(p in texto for p in ["led", "luz", "bombillo"])
    ):

        await controlar_led(update, context, "off")

        return

    if (
        "led" in texto
        and any(p in texto for p in ["estado", "cómo está", "como esta", "encendido", "apagado"])
    ):

        await controlar_led(update, context, "estado")

        return

    # ========================================================
    # GRÁFICOS (LENGUAJE NATURAL)
    # ========================================================

    if any(p in texto for p in ["gráfico", "grafico", "dibuja"]):

        if any(p in texto for p in ["hora", "horas", "por hora"]):

            await generar_grafico_eco2_hora(update, context)

            return

        if any(p in texto for p in ["registro", "registros", "día", "dia", "por día", "por dia"]):

            await generar_grafico_registros_dia(update, context)

            return

        if any(p in texto for p in ["tendencia", "evolución", "evolucion"]):

            await generar_grafico_tendencia(update, context)

            return

        mensaje = "📊 *GRÁFICOS VIPIS*\n\nSelecciona un gráfico:"

        await enviar_respuesta(update, mensaje, reply_markup=teclado_graficos())

        return

    # ========================================================
    # CONSULTA CON IA (GEMINI) - FALLBACK INTELIGENTE
    # ========================================================

    await consultar_gemini(update, context, texto_original)


# ============================================================
# INICIAR BOT
# ============================================================

def _construir_aplicacion():
    """Construye y configura la Application del bot con todos los handlers."""

    if not TELEGRAM_BOT_TOKEN:
        return None

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "Iniciar el bot"),
            BotCommand("ultima", "Última medición"),
            BotCommand("mediciones", "Últimas mediciones"),
            BotCommand("alertas", "Alertas pendientes"),
            BotCommand("estadisticas", "Estadísticas generales"),
            BotCommand("dispositivos", "Dispositivos registrados"),
            BotCommand("ayuda", "Ayuda"),
            BotCommand("led", "Control del LED"),
            BotCommand("graficos", "Gráficos"),
        ])

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ultima", ultima))
    application.add_handler(CommandHandler("mediciones", mediciones))
    application.add_handler(CommandHandler("alertas", alertas))
    application.add_handler(CommandHandler("atender", atender))
    application.add_handler(CommandHandler("estadisticas", obtener_estadisticas_telegram))
    application.add_handler(CommandHandler("dispositivos", obtener_dispositivos_telegram))
    application.add_handler(CommandHandler("ayuda", mostrar_ayuda))
    application.add_handler(CommandHandler("led", comando_led))
    application.add_handler(CommandHandler("graficos", comando_graficos))

    application.add_handler(CallbackQueryHandler(manejar_callback))

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            procesar_mensaje
        )
    )

    return application


def iniciar_bot():
    """Inicia el bot en modo local (bloqueante)."""

    application = _construir_aplicacion()

    if not application:
        print("❌ TELEGRAM_BOT_TOKEN no está configurado.")
        return

    print("🤖 Bot de Telegram iniciado.")
    print("💬 Modo de lenguaje natural activado.")
    print("🔘 Botones interactivos activados.")

    application.run_polling()


# ============================================================
# MODO NUBE (NO BLOQUEANTE, PARA RENDER)
# ============================================================

_bot_aplicacion = None


async def iniciar_bot_cloud():
    """Inicia el bot en modo no-bloqueante para correr junto con la API."""

    global _bot_aplicacion

    _bot_aplicacion = _construir_aplicacion()

    if not _bot_aplicacion:
        print("⚠️ TELEGRAM_BOT_TOKEN no configurado. Bot nube deshabilitado.")
        return

    await _bot_aplicacion.initialize()
    await _bot_aplicacion.start()
    await _bot_aplicacion.updater.start_polling(drop_pending_updates=True)

    print("🤖 Bot de Telegram iniciado (modo nube).")
    print("💬 Lenguaje natural activado.")
    print("🔘 Botones interactivos activados.")


async def detener_bot_cloud():
    """Detiene el bot correctamente al apagar la API."""

    global _bot_aplicacion

    if _bot_aplicacion:
        await _bot_aplicacion.updater.stop()
        await _bot_aplicacion.stop()
        await _bot_aplicacion.shutdown()
        print("🤖 Bot de Telegram detenido.")


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    iniciar_bot()