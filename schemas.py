from pydantic import BaseModel, Field


class MedicionCreate(BaseModel):
    dispositivo_id: int = Field(..., gt=0)

    eco2: float = Field(..., ge=0)
    tvoc: float = Field(..., ge=0)
    temperatura: float
    humedad: float = Field(..., ge=0, le=100)


class MedicionResponse(BaseModel):
    medicion_id: int
    dispositivo_id: int

    eco2: float
    tvoc: float
    temperatura: float
    humedad: float

    nivel_riesgo: str | None = None
    
    # ============================================================
# ESQUEMAS PARA INFLUXDB, YOLO Y FUSIÓN SENSORIAL (TALLER 2)
# ============================================================

class TelemetriaInflux(BaseModel):
    timestamp: str | None = None
    dispositivo: str = "esp32_01"
    eco2: float | None = None
    tvoc: float | None = None
    temperatura: float | None = None
    humedad: float | None = None

class DeteccionYOLO(BaseModel):
    clase: str
    confianza: float
    bbox: list[float] | None = None

class FusionSensorialRespuesta(BaseModel):
    alerta_activa: bool
    nivel_riesgo: str
    mensaje: str

class MonitoreoFusionadoResponse(BaseModel):
    timestamp: str
    telemetria: TelemetriaInflux
    detecciones_yolo: list[DeteccionYOLO]
    fusion_sensorial: FusionSensorialRespuesta