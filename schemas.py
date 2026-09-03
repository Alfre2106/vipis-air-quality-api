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