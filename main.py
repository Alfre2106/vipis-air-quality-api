from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from schemas import MedicionCreate
from database import get_db
from repository import Repository
import models


app = FastAPI(
    title="API Calidad del Aire - Vía Parque Isla de Salamanca",
    description="API para gestión y consulta del sistema VIPIS.",
    version="1.0.0",
)


# ============================================================
# DISPOSITIVOS
# ============================================================

@app.get("/dispositivos", tags=["dispositivos"])
def listar_dispositivos(
    db: Session = Depends(get_db)
):
    repo = Repository(models.Dispositivo)

    return repo.get_all(db)


@app.get("/dispositivos/{item_id}", tags=["dispositivos"])
def obtener_dispositivo(
    item_id: int,
    db: Session = Depends(get_db)
):
    repo = Repository(models.Dispositivo)

    dispositivo = repo.get_by_id(db, item_id)

    if not dispositivo:
        raise HTTPException(
            status_code=404,
            detail="Dispositivo no encontrado"
        )

    return dispositivo


# ============================================================
# UBICACIONES
# ============================================================

@app.get("/ubicaciones", tags=["ubicaciones"])
def listar_ubicaciones(
    db: Session = Depends(get_db)
):
    repo = Repository(models.Ubicacion)

    return repo.get_all(db)


@app.get("/ubicaciones/{item_id}", tags=["ubicaciones"])
def obtener_ubicacion(
    item_id: int,
    db: Session = Depends(get_db)
):
    repo = Repository(models.Ubicacion)

    ubicacion = repo.get_by_id(db, item_id)

    if not ubicacion:
        raise HTTPException(
            status_code=404,
            detail="Ubicación no encontrada"
        )

    return ubicacion


# ============================================================
# SENSORES
# ============================================================

@app.get("/sensores", tags=["sensores"])
def listar_sensores(
    db: Session = Depends(get_db)
):
    repo = Repository(models.Sensor)

    return repo.get_all(db)


@app.get("/sensores/{item_id}", tags=["sensores"])
def obtener_sensor(
    item_id: int,
    db: Session = Depends(get_db)
):
    repo = Repository(models.Sensor)

    sensor = repo.get_by_id(db, item_id)

    if not sensor:
        raise HTTPException(
            status_code=404,
            detail="Sensor no encontrado"
        )

    return sensor


# ============================================================
# TIPOS DE MEDICIÓN
# ============================================================

@app.get("/tipos-medicion", tags=["tipos de medición"])
def listar_tipos_medicion(
    db: Session = Depends(get_db)
):
    repo = Repository(models.TipoMedicion)

    return repo.get_all(db)


@app.get("/tipos-medicion/{item_id}", tags=["tipos de medición"])
def obtener_tipo_medicion(
    item_id: int,
    db: Session = Depends(get_db)
):
    repo = Repository(models.TipoMedicion)

    tipo = repo.get_by_id(db, item_id)

    if not tipo:
        raise HTTPException(
            status_code=404,
            detail="Tipo de medición no encontrado"
        )

    return tipo


# ============================================================
# NIVELES DE RIESGO
# ============================================================

@app.get("/niveles-riesgo", tags=["riesgo"])
def listar_niveles_riesgo(
    db: Session = Depends(get_db)
):
    repo = Repository(models.NivelRiesgo)

    return repo.get_all(db)


# ============================================================
# MEDICIONES
# ============================================================

@app.post("/mediciones", tags=["mediciones"])
def crear_medicion(
    datos: MedicionCreate,
    db: Session = Depends(get_db)
):
    # --------------------------------------------------------
    # 1. Verificar que el dispositivo exista
    # --------------------------------------------------------

    dispositivo = (
        db.query(models.Dispositivo)
        .filter(
            models.Dispositivo.id == datos.dispositivo_id
        )
        .first()
    )

    if not dispositivo:
        raise HTTPException(
            status_code=404,
            detail="El dispositivo no existe"
        )

    try:
        # ----------------------------------------------------
        # 2. Crear la medición
        # ----------------------------------------------------

        medicion = models.Medicion(
            dispositivo_id=datos.dispositivo_id
        )

        db.add(medicion)
        db.flush()

        # ----------------------------------------------------
        # 3. Guardar los valores de la medición
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 4. Buscar el rango de riesgo para eCO₂
        # ----------------------------------------------------

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
                detail=(
                    "No existe un rango de riesgo configurado "
                    "para el valor de eCO₂ proporcionado"
                )
            )

        # ----------------------------------------------------
        # 5. Obtener el nivel de riesgo
        # ----------------------------------------------------

        nivel_riesgo = (
            db.query(models.NivelRiesgo)
            .filter(
                models.NivelRiesgo.id == rango.nivel_riesgo_id
            )
            .first()
        )

        if not nivel_riesgo:
            raise HTTPException(
                status_code=500,
                detail="El nivel de riesgo configurado no existe"
            )

        # ----------------------------------------------------
        # 6. Crear la clasificación
        # ----------------------------------------------------

        clasificacion = models.Clasificacion(
            medicion_id=medicion.id,
            nivel_riesgo_id=rango.nivel_riesgo_id,
            confianza=100.00
        )

        db.add(clasificacion)
        db.flush()

        # ----------------------------------------------------
        # 7. Generar alerta si el nivel es >= 5
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 8. Confirmar toda la transacción
        # ----------------------------------------------------

        db.commit()

        db.refresh(medicion)
        db.refresh(clasificacion)

        if alerta:
            db.refresh(alerta)

        # ----------------------------------------------------
        # 9. Respuesta
        # ----------------------------------------------------

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
            "alerta_id": alerta.id if alerta else None
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


# ============================================================
# ALERTAS PENDIENTES
# ============================================================

@app.get("/alertas/pendientes", tags=["alertas"])
def obtener_alertas_pendientes(
    db: Session = Depends(get_db)
):

    alertas = (
        db.query(
            models.Alerta,
            models.Clasificacion,
            models.NivelRiesgo,
            models.Medicion
        )
        .join(
            models.Clasificacion,
            models.Alerta.clasificacion_id == models.Clasificacion.id
        )
        .join(
            models.NivelRiesgo,
            models.Clasificacion.nivel_riesgo_id == models.NivelRiesgo.id
        )
        .join(
            models.Medicion,
            models.Clasificacion.medicion_id == models.Medicion.id
        )
        .filter(
            models.Alerta.atendida == False
        )
        .order_by(
            models.Alerta.fecha_generada.desc()
        )
        .all()
    )

    resultado = []

    for alerta, clasificacion, nivel_riesgo, medicion in alertas:

        valores = (
            db.query(models.ValorMedicion)
            .filter(
                models.ValorMedicion.medicion_id == medicion.id
            )
            .all()
        )

        datos = {}

        for valor in valores:
            datos[valor.tipo_medicion_id] = valor.valor

        resultado.append({
            "alerta_id": alerta.id,
            "clasificacion_id": clasificacion.id,
            "medicion_id": medicion.id,
            "fecha_generada": alerta.fecha_generada,
            "atendida": alerta.atendida,

            "nivel_riesgo": {
                "id": nivel_riesgo.id,
                "nombre": nivel_riesgo.nombre
            },

            "eco2": datos.get(1),
            "tvoc": datos.get(2),
            "temperatura": datos.get(3),
            "humedad": datos.get(4),

            "descripcion": alerta.descripcion
        })

    return resultado

# ============================================================
# ATENDER ALERTA
# ============================================================

@app.put("/alertas/{alerta_id}/atender", tags=["alertas"])
def atender_alerta(
    alerta_id: int,
    db: Session = Depends(get_db)
):

    alerta = (
        db.query(models.Alerta)
        .filter(
            models.Alerta.id == alerta_id
        )
        .first()
    )

    if not alerta:
        raise HTTPException(
            status_code=404,
            detail="Alerta no encontrada"
        )

    if alerta.atendida:
        return {
            "mensaje": "La alerta ya estaba atendida",
            "alerta_id": alerta.id,
            "atendida": True
        }

    try:
        alerta.atendida = True

        db.commit()
        db.refresh(alerta)

        return {
            "mensaje": "Alerta marcada como atendida",
            "alerta_id": alerta.id,
            "atendida": alerta.atendida
        }

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Error al actualizar la alerta"
        )


# ============================================================
# RANGOS DE RIESGO
# ============================================================

@app.get("/rangos", tags=["riesgo"])
def listar_rangos(
    db: Session = Depends(get_db)
):

    tipos = db.query(models.TipoMedicion).all()

    rangos_riesgo = (
        db.query(models.RangoRiesgo)
        .all()
    )

    niveles = {
        nivel.id: nivel.nombre
        for nivel in db.query(models.NivelRiesgo).all()
    }

    resultado = []

    for tipo in tipos:

        rangos_tipo = [
            rango
            for rango in rangos_riesgo
            if rango.tipo_medicion_id == tipo.id
        ]

        resultado.append({
            "tipo": tipo.nombre,
            "unidad": tipo.unidad,

            "rangos": [
                {
                    "nivel": niveles.get(rango.nivel_riesgo_id),
                    "min": float(rango.valor_min),
                    "max": float(rango.valor_max)
                }

                for rango in rangos_tipo
            ]
        })

    return resultado