import os
import requests

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
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

    try:
        from telegram import Bot

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    mensaje = (
        "🤖 *VIPIS - Calidad del Aire*\n\n"
        "Bienvenido al sistema de monitoreo.\n\n"
        "Comandos disponibles:\n\n"
        "📊 /ultima - Última medición\n"
        "📋 /mediciones - Últimas mediciones\n"
        "🚨 /alertas - Alertas pendientes\n"
        "✅ /atender ID - Atender una alerta\n"
    )

    await update.message.reply_text(
        mensaje,
        parse_mode="Markdown"
    )


# ============================================================
# /ULTIMA
# ============================================================

async def ultima(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
            f"💧 Humedad: {data['humedad'] if data['humedad'] is not None else 'N/D'} %\n\n"
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

async def mediciones(update: Update, context: ContextTypes.DEFAULT_TYPE):

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

        mediciones_data = data.get("mediciones", [])

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
                f"💧 Humedad: {medicion['humedad'] if medicion['humedad'] is not None else 'N/D'} %\n"
                f"⚠️ Riesgo: {medicion['nivel_riesgo'] or 'N/D'}\n"
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

async def alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):

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

            valores = alerta.get("valores", {})
            riesgo = alerta.get("nivel_riesgo", {})

            mensaje += (
                f"🔴 *Alerta #{alerta['alerta_id']}*\n"
                f"📊 Medición: {alerta['medicion_id']}\n"
                f"🌫️ eCO₂: {valores.get('eco2', 'N/D')} ppm\n"
                f"🧪 TVOC: {valores.get('tvoc', 'N/D')} ppb\n"
                f"⚠️ Riesgo: *{riesgo.get('nombre', 'N/D')}*\n"
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

async def atender(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
# INICIAR BOT
# ============================================================

def iniciar_bot():

    if not TELEGRAM_BOT_TOKEN:

        print("❌ TELEGRAM_BOT_TOKEN no está configurado.")
        return

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("ultima", ultima)
    )

    application.add_handler(
        CommandHandler("mediciones", mediciones)
    )

    application.add_handler(
        CommandHandler("alertas", alertas)
    )

    application.add_handler(
        CommandHandler("atender", atender)
    )

    print("🤖 Bot de Telegram iniciado.")

    application.run_polling()
       
       
if __name__ == "__main__":
    iniciar_bot()