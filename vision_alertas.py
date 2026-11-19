"""Lógica de alertas para la detección de fuego/humo (YOLO).

Reglas (todas configurables por variables de entorno):
- Una detección cuenta como crítica si su clase contiene alguna palabra de
  VISION_CLASES_ALERTA y su confianza >= VISION_UMBRAL_ALERTA.
- Se dispara la alerta solo tras VISION_FRAMES_CONSECUTIVOS frames críticos seguidos.
- Después de una alerta, no se repite hasta pasados VISION_ENFRIAMIENTO_SEG segundos.
- Si el LED lo encendió la visión, se apaga solo tras VISION_LED_AUTO_OFF_SEG
  segundos sin detecciones críticas (0 = no se apaga solo).
"""
import os
import time


def _lista(nombre, defecto):
    return [x.strip().lower() for x in os.getenv(nombre, defecto).split(",") if x.strip()]


CLASES_ALERTA = _lista("VISION_CLASES_ALERTA", "fuego,fire,humo,smoke,llama,flame,incendio")
UMBRAL_ALERTA = float(os.getenv("VISION_UMBRAL_ALERTA", "0.60"))
FRAMES_CONSECUTIVOS = int(os.getenv("VISION_FRAMES_CONSECUTIVOS", "3"))
ENFRIAMIENTO_SEG = int(os.getenv("VISION_ENFRIAMIENTO_SEG", "300"))
LED_AUTO_OFF_SEG = int(os.getenv("VISION_LED_AUTO_OFF_SEG", "60"))


class EvaluadorVision:
    def __init__(self):
        self.racha = 0
        self.ultima_alerta = None
        self.ultima_critica = None
        self.led_por_vision = False

    @staticmethod
    def criticas(preds):
        out = []
        for p in preds:
            clase = str(p.get("class", "")).lower()
            if float(p.get("confidence", 0)) >= UMBRAL_ALERTA and any(c in clase for c in CLASES_ALERTA):
                out.append(p)
        return out

    def evaluar(self, preds, ahora=None):
        ahora = time.time() if ahora is None else ahora
        crit = self.criticas(preds)
        if crit:
            self.racha += 1
            self.ultima_critica = ahora
        else:
            self.racha = 0

        alerta = False
        if self.racha >= FRAMES_CONSECUTIVOS and (
            self.ultima_alerta is None or ahora - self.ultima_alerta >= ENFRIAMIENTO_SEG
        ):
            alerta = True
            self.ultima_alerta = ahora

        mejor = max(crit, key=lambda p: p["confidence"]) if crit else None
        return {"alerta": alerta, "racha": self.racha, "criticas": len(crit), "mejor": mejor}

    def marcar_led_encendido(self):
        self.led_por_vision = True

    def marcar_led_apagado(self):
        self.led_por_vision = False

    def debe_apagar_led(self, ahora=None):
        ahora = time.time() if ahora is None else ahora
        if not self.led_por_vision or LED_AUTO_OFF_SEG <= 0 or self.ultima_critica is None:
            return False
        return ahora - self.ultima_critica >= LED_AUTO_OFF_SEG


evaluador_vision = EvaluadorVision()