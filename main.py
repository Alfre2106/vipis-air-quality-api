from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from schemas import MedicionCreate
from database import get_db
from repository import Repository
import models
from telegram_bot import enviar_mensaje_telegram


app = FastAPI(
    title="VIPIS - API de Calidad del Aire",
    description="API para el registro y monitoreo de calidad del aire de la Vía Parque Isla de Salamanca",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "mensaje": "API VIPIS funcionando correctamente",
        "proyecto": "Calidad del Aire - Vía Parque Isla de Salamanca"
    }


# ============================================================
# DISPOSITIVOS
# ============================================================

@app.get(
    "/dispositivos",
    tags=["dispositivos"],
    summary="Listar dispositivos",
    description="Devuelve todos los dispositivos IoT registrados en el sistema."
)
def listar_dispositivos(
    db: Session = Depends(get_db)
):
    dispositivos = (
        db.query(models.Dispositivo)
        .order_by(models.Dispositivo.id)
        .all()
    )

    resultado = []

    for dispositivo in dispositivos:
        resultado.append({
            "id": dispositivo.id,
            "codigo": dispositivo.codigo,
            "ubicacion_id": dispositivo.ubicacion_id,
            "usuario_id": dispositivo.usuario_id
        })

    return resultado


# ============================================================
# SENSORES
# ============================================================

@app.get(
    "/sensores",
    tags=["sensores"],
    summary="Listar sensores registrados",
    description="Devuelve todos los sensores registrados en el sistema."
)
def listar_sensores(
    db: Session = Depends(get_db)
):
    sensores = (
        db.query(models.Sensor)
        .order_by(models.Sensor.id)
        .all()
    )

    resultado = []

    for sensor in sensores:
        resultado.append({
            "id": sensor.id,
            "nombre": sensor.nombre,
            "modelo": sensor.modelo,
            "fabricante": sensor.fabricante,
            "tipo": sensor.tipo,
            "interfaz": sensor.interfaz
        })

    return resultado


# ============================================================
# USUARIOS
# ============================================================

@app.get(
    "/usuarios",
    tags=["usuarios"],
    summary="Listar usuarios registrados",
    description=(
        "Devuelve los usuarios registrados en el sistema VIPIS. "
        "Incluye nombre, correo, rol y fecha de registro. "
        "Por seguridad, nunca devuelve la contraseña almacenada."
    )
)
def listar_usuarios(
    db: Session = Depends(get_db)
):
    usuarios = (
        db.query(models.Usuario)
        .order_by(models.Usuario.id)
        .all()
    )

    resultado = []

    for usuario in usuarios:
        resultado.append({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "rol": usuario.rol,
            "fecha_registro": usuario.fecha_registro
        })

    return resultado


# ============================================================
# UBICACIONES
# ============================================================

@app.get(
    "/ubicaciones",
    tags=["ubicaciones"],
    summary="Listar ubicaciones registradas",
    description=(
        "Devuelve las ubicaciones registradas en el sistema VIPIS, "
        "incluyendo nombre, zona, coordenadas y descripción."
    )
)
def listar_ubicaciones(
    db: Session = Depends(get_db)
):
    ubicaciones = (
        db.query(models.Ubicacion)
        .order_by(models.Ubicacion.id)
        .all()
    )

    resultado = []

    for ubicacion in ubicaciones:
        resultado.append({
            "id": ubicacion.id,
            "nombre": ubicacion.nombre,
            "zona": ubicacion.zona,
            "latitud": float(ubicacion.latitud),
            "longitud": float(ubicacion.longitud),
            "descripcion": ubicacion.descripcion
        })

    return resultado


# ============================================================
# MEDICIONES
# ============================================================

@app.post(
    "/mediciones",
    tags=["mediciones"],
    summary="Registrar una nueva medición",
    description=(
        "Recibe eCO2, TVOC, temperatura y humedad de un dispositivo, "
        "calcula el nivel de riesgo, y genera una alerta por Telegram "
        "si el riesgo es alto."
    )
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

        # --------------------------------------------------------
        # 1. Crear la medición
        # --------------------------------------------------------

        medicion = models.Medicion(
            dispositivo_id=datos.dispositivo_id
        )

        db.add(medicion)
        db.flush()

        # --------------------------------------------------------
        # 2. Guardar los valores de la medición
        #
        # Tipo 1 = eCO₂
        # Tipo 2 = TVOC
        # Tipo 3 = Temperatura
        # Tipo 4 = Humedad
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 3. Buscar el rango de riesgo según el eCO₂
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 4. Obtener el nivel de riesgo
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 5. Crear clasificación
        # --------------------------------------------------------

        clasificacion = models.Clasificacion(
            medicion_id=medicion.id,
            nivel_riesgo_id=rango.nivel_riesgo_id,
            confianza=100.00
        )

        db.add(clasificacion)
        db.flush()

        # --------------------------------------------------------
        # 6. Crear alerta si el nivel de riesgo es >= 5
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # 7. Guardar todo en Neon
        # --------------------------------------------------------

        db.commit()

        # --------------------------------------------------------
        # 8. Actualizar objetos después del commit
        # --------------------------------------------------------

        db.refresh(medicion)
        db.refresh(clasificacion)

        if alerta:
            db.refresh(alerta)

        # --------------------------------------------------------
        # 9. Enviar alerta a Telegram
        #
        # IMPORTANTE:
        # Esto ocurre DESPUÉS del commit.
        #
        # Si Telegram falla, la información ya quedó
        # guardada en Neon.
        # --------------------------------------------------------

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

            telegram_enviado = await enviar_mensaje_telegram(
                mensaje_telegram
            )

        # --------------------------------------------------------
        # 10. Respuesta
        # --------------------------------------------------------

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

    # ------------------------------------------------------------
    # Manejo de errores HTTP
    # ------------------------------------------------------------

    except HTTPException:
        db.rollback()
        raise

    # ------------------------------------------------------------
    # Manejo de errores generales
    # ------------------------------------------------------------

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Error al registrar la medición"
        )


# ============================================================
# CONSULTAR ÚLTIMA MEDICIÓN
# ============================================================

@app.get(
    "/mediciones/ultima",
    tags=["mediciones"],
    summary="Obtener la última medición registrada",
    description=(
        "Devuelve eCO2, TVOC, temperatura, humedad y nivel de riesgo "
        "de la medición más reciente."
    )
)
def obtener_ultima_medicion(
    db: Session = Depends(get_db)
):

    medicion = (
        db.query(models.Medicion)
        .order_by(models.Medicion.fecha_hora.desc())
        .first()
    )

    if not medicion:
        raise HTTPException(
            status_code=404,
            detail="No hay mediciones registradas"
        )

    valores = (
        db.query(models.ValorMedicion)
        .filter(
            models.ValorMedicion.medicion_id == medicion.id
        )
        .all()
    )

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

    clasificacion = (
        db.query(models.Clasificacion)
        .filter(
            models.Clasificacion.medicion_id == medicion.id
        )
        .first()
    )

    nivel_riesgo = None

    if clasificacion:

        riesgo = (
            db.query(models.NivelRiesgo)
            .filter(
                models.NivelRiesgo.id == clasificacion.nivel_riesgo_id
            )
            .first()
        )

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


# ============================================================
# LISTAR MEDICIONES RECIENTES
# ============================================================

@app.get(
    "/mediciones",
    tags=["mediciones"],
    summary="Listar mediciones recientes",
    description=(
        "Obtiene las mediciones recientes de VIPIS. "
        "USAR ÚNICAMENTE cuando el usuario solicite las últimas N "
        "mediciones o necesite consultar valores individuales de "
        "mediciones recientes. "
        "El parámetro 'limit' es obligatorio y debe ser un número "
        "entero entre 1 y 100. Nunca enviar limit=null."
    )
)
def obtener_mediciones(
    limit: int = 10,
    db: Session = Depends(get_db)
):

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="El límite debe estar entre 1 y 100"
        )

    mediciones = (
        db.query(models.Medicion)
        .order_by(models.Medicion.fecha_hora.desc())
        .limit(limit)
        .all()
    )

    resultado = []

    for medicion in mediciones:

        valores = (
            db.query(models.ValorMedicion)
            .filter(
                models.ValorMedicion.medicion_id == medicion.id
            )
            .all()
        )

        datos = {}

        # --------------------------------------------------------
        # Mapear valores según el tipo de medición
        # --------------------------------------------------------

        for valor in valores:

            if valor.tipo_medicion_id == 1:
                datos["eco2"] = valor.valor

            elif valor.tipo_medicion_id == 2:
                datos["tvoc"] = valor.valor

            elif valor.tipo_medicion_id == 3:
                datos["temperatura"] = valor.valor

            elif valor.tipo_medicion_id == 4:
                datos["humedad"] = valor.valor

        # --------------------------------------------------------
        # Obtener clasificación
        # --------------------------------------------------------

        clasificacion = (
            db.query(models.Clasificacion)
            .filter(
                models.Clasificacion.medicion_id == medicion.id
            )
            .first()
        )

        nivel_riesgo = None

        if clasificacion:

            riesgo = (
                db.query(models.NivelRiesgo)
                .filter(
                    models.NivelRiesgo.id
                    == clasificacion.nivel_riesgo_id
                )
                .first()
            )

            if riesgo:
                nivel_riesgo = riesgo.nombre

        # --------------------------------------------------------
        # Agregar medición al resultado
        # --------------------------------------------------------

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

    return {
        "total": len(resultado),
        "mediciones": resultado
    }


# ============================================================
# MEDICIONES CRÍTICAS
# ============================================================

@app.get(
    "/mediciones/criticas",
    tags=["mediciones"],
    summary="Listar mediciones críticas",
    description=(
        "Obtiene TODAS las mediciones que VIPIS ha clasificado con "
        "nivel de riesgo 'Crítico'. USAR cuando el usuario solicite "
        "identificar, listar o consultar las mediciones críticas "
        "históricas. "
        "No utilizar esta herramienta para calcular promedios, "
        "máximos, mínimos u otras estadísticas generales."
    )
)
def obtener_mediciones_criticas(
    db: Session = Depends(get_db)
):

    # --------------------------------------------------------
    # Buscar todas las mediciones con nivel de riesgo Crítico
    # --------------------------------------------------------

    mediciones = (
        db.query(models.Medicion)
        .join(
            models.Clasificacion,
            models.Clasificacion.medicion_id == models.Medicion.id
        )
        .join(
            models.NivelRiesgo,
            models.NivelRiesgo.id
            == models.Clasificacion.nivel_riesgo_id
        )
        .filter(
            models.NivelRiesgo.nombre == "Crítico"
        )
        .order_by(
            models.Medicion.fecha_hora.desc()
        )
        .all()
    )

    resultado = []

    # --------------------------------------------------------
    # Obtener valores de cada medición
    # --------------------------------------------------------

    for medicion in mediciones:

        valores = (
            db.query(models.ValorMedicion)
            .filter(
                models.ValorMedicion.medicion_id == medicion.id
            )
            .all()
        )

        datos = {}

        # ----------------------------------------------------
        # Mapear valores por tipo
        # ----------------------------------------------------

        for valor in valores:

            if valor.tipo_medicion_id == 1:
                datos["eco2"] = valor.valor

            elif valor.tipo_medicion_id == 2:
                datos["tvoc"] = valor.valor

            elif valor.tipo_medicion_id == 3:
                datos["temperatura"] = valor.valor

            elif valor.tipo_medicion_id == 4:
                datos["humedad"] = valor.valor

        # ----------------------------------------------------
        # Agregar resultado
        # ----------------------------------------------------

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

    # --------------------------------------------------------
    # Respuesta
    # --------------------------------------------------------

    return {
        "total": len(resultado),
        "mediciones": resultado
    }


# ============================================================
# ESTADÍSTICAS GENERALES DE MEDICIONES
# ============================================================

@app.get(
    "/mediciones/estadisticas",
    tags=["mediciones"],
    summary="Obtener estadísticas generales de VIPIS",
    description=(
        "HERRAMIENTA PRINCIPAL PARA ESTADÍSTICAS DE VIPIS. "
        "Utiliza esta herramienta OBLIGATORIAMENTE cuando el usuario "
        "pregunte por estadísticas generales de las mediciones."
        "\n\n"
        "Esta herramienta devuelve directamente los cálculos "
        "realizados por la API y NO requiere parámetros."
        "\n\n"
        "IMPORTANTE: el campo 'mediciones_criticas' contiene "
        "directamente la cantidad TOTAL de mediciones clasificadas "
        "como 'Crítico'. "
        "NO es necesario consultar /mediciones/criticas para obtener "
        "esta cantidad."
        "\n\n"
        "IMPORTANTE: el campo "
        "'promedio_eco2_todas_las_mediciones' contiene directamente "
        "el promedio de eCO2 de TODAS las mediciones históricas "
        "registradas. "
        "NO calcular este promedio manualmente y NO utilizar "
        "/mediciones/criticas para calcularlo."
        "\n\n"
        "Usar esta herramienta para: "
        "promedios, máximos, mínimos, cantidad total de mediciones, "
        "cantidad de mediciones críticas y estadísticas generales."
        "\n\n"
        "Si el usuario pregunta cuántas mediciones críticas existen, "
        "usar directamente el campo 'mediciones_criticas'."
        "\n\n"
        "Si el usuario pregunta el promedio de eCO2 de todas las "
        "mediciones, usar directamente el campo "
        "'promedio_eco2_todas_las_mediciones'."
        "\n\n"
        "NO requiere parámetros de entrada."
    )
)
def obtener_estadisticas(
    db: Session = Depends(get_db)
):

    # --------------------------------------------------------
    # Obtener TODAS las mediciones
    # --------------------------------------------------------

    mediciones = (
        db.query(models.Medicion)
        .all()
    )

    # --------------------------------------------------------
    # Si no existen mediciones
    # --------------------------------------------------------

    if not mediciones:
        return {
            "total_mediciones": 0,
            "mediciones_criticas": 0,
            "promedio_eco2_todas_las_mediciones": None,
            "maximo_eco2_todas_las_mediciones": None,
            "minimo_eco2_todas_las_mediciones": None,
            "promedio_tvoc_todas_las_mediciones": None,
            "maximo_tvoc_todas_las_mediciones": None,
            "minimo_tvoc_todas_las_mediciones": None,
            "promedio_temperatura_todas_las_mediciones": None,
            "maximo_temperatura_todas_las_mediciones": None,
            "minimo_temperatura_todas_las_mediciones": None,
            "promedio_humedad_todas_las_mediciones": None,
            "maximo_humedad_todas_las_mediciones": None,
            "minimo_humedad_todas_las_mediciones": None
        }

    # --------------------------------------------------------
    # Listas de valores
    # --------------------------------------------------------

    eco2_valores = []
    tvoc_valores = []
    temperatura_valores = []
    humedad_valores = []

    mediciones_criticas = 0

    # --------------------------------------------------------
    # Recorrer todas las mediciones
    # --------------------------------------------------------

    for medicion in mediciones:

        valores = (
            db.query(models.ValorMedicion)
            .filter(
                models.ValorMedicion.medicion_id == medicion.id
            )
            .all()
        )

        for valor in valores:

            if valor.valor is None:
                continue

            if valor.tipo_medicion_id == 1:
                eco2_valores.append(
                    float(valor.valor)
                )

            elif valor.tipo_medicion_id == 2:
                tvoc_valores.append(
                    float(valor.valor)
                )

            elif valor.tipo_medicion_id == 3:
                temperatura_valores.append(
                    float(valor.valor)
                )

            elif valor.tipo_medicion_id == 4:
                humedad_valores.append(
                    float(valor.valor)
                )

        # ----------------------------------------------------
        # Buscar clasificación de riesgo
        # ----------------------------------------------------

        clasificacion = (
            db.query(models.Clasificacion)
            .filter(
                models.Clasificacion.medicion_id
                == medicion.id
            )
            .first()
        )

        if clasificacion:

            nivel = (
                db.query(models.NivelRiesgo)
                .filter(
                    models.NivelRiesgo.id
                    == clasificacion.nivel_riesgo_id
                )
                .first()
            )

            if nivel and nivel.nombre == "Crítico":
                mediciones_criticas += 1

    # --------------------------------------------------------
    # Funciones estadísticas
    # --------------------------------------------------------

    def calcular_promedio(valores):

        if not valores:
            return None

        return round(
            sum(valores) / len(valores),
            2
        )

    def calcular_maximo(valores):

        if not valores:
            return None

        return max(valores)

    def calcular_minimo(valores):

        if not valores:
            return None

        return min(valores)

    # --------------------------------------------------------
    # Respuesta
    # --------------------------------------------------------

    return {
        "total_mediciones": len(mediciones),

        "mediciones_criticas": mediciones_criticas,

        # ====================================================
        # eCO2
        # ====================================================

        "promedio_eco2_todas_las_mediciones":
            calcular_promedio(eco2_valores),

        "maximo_eco2_todas_las_mediciones":
            calcular_maximo(eco2_valores),

        "minimo_eco2_todas_las_mediciones":
            calcular_minimo(eco2_valores),

        # ====================================================
        # TVOC
        # ====================================================

        "promedio_tvoc_todas_las_mediciones":
            calcular_promedio(tvoc_valores),

        "maximo_tvoc_todas_las_mediciones":
            calcular_maximo(tvoc_valores),

        "minimo_tvoc_todas_las_mediciones":
            calcular_minimo(tvoc_valores),

        # ====================================================
        # TEMPERATURA
        # ====================================================

        "promedio_temperatura_todas_las_mediciones":
            calcular_promedio(temperatura_valores),

        "maximo_temperatura_todas_las_mediciones":
            calcular_maximo(temperatura_valores),

        "minimo_temperatura_todas_las_mediciones":
            calcular_minimo(temperatura_valores),

        # ====================================================
        # HUMEDAD
        # ====================================================

        "promedio_humedad_todas_las_mediciones":
            calcular_promedio(humedad_valores),

        "maximo_humedad_todas_las_mediciones":
            calcular_maximo(humedad_valores),

        "minimo_humedad_todas_las_mediciones":
            calcular_minimo(humedad_valores)
    }


# ============================================================
# ALERTAS PENDIENTES
# ============================================================

@app.get(
    "/alertas/pendientes",
    tags=["alertas"],
    summary="Listar alertas pendientes",
    description=(
        "Devuelve todas las alertas de calidad del aire que aún "
        "no han sido atendidas, con su nivel de riesgo y valores "
        "de medición."
    )
)
def listar_alertas_pendientes(
    db: Session = Depends(get_db)
):

    resultados = (
        db.query(
            models.Alerta,
            models.Clasificacion,
            models.NivelRiesgo,
            models.Medicion
        )
        .join(
            models.Clasificacion,
            models.Alerta.clasificacion_id
            == models.Clasificacion.id
        )
        .join(
            models.NivelRiesgo,
            models.Clasificacion.nivel_riesgo_id
            == models.NivelRiesgo.id
        )
        .join(
            models.Medicion,
            models.Clasificacion.medicion_id
            == models.Medicion.id
        )
        .filter(
            models.Alerta.atendida == False
        )
        .order_by(
            models.Alerta.id.desc()
        )
        .all()
    )

    respuesta = []

    for alerta, clasificacion, nivel_riesgo, medicion in resultados:

        valores = (
            db.query(models.ValorMedicion)
            .filter(
                models.ValorMedicion.medicion_id == medicion.id
            )
            .all()
        )

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

            "nivel_riesgo": {
                "id": nivel_riesgo.id,
                "nombre": nivel_riesgo.nombre
            },

            "valores": {
                "eco2": datos_valores.get("eco2"),
                "tvoc": datos_valores.get("tvoc"),
                "temperatura": datos_valores.get("temperatura"),
                "humedad": datos_valores.get("humedad")
            }
        })

    return respuesta


# ============================================================
# ATENDER ALERTA
# ============================================================

@app.put(
    "/alertas/{alerta_id}/atender",
    tags=["alertas"],
    summary="Marcar una alerta como atendida",
    description=(
        "Cambia el estado de una alerta específica a 'atendida' "
        "usando su ID."
    )
)
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
            detail="La alerta no existe"
        )

    alerta.atendida = True

    db.commit()
    db.refresh(alerta)

    return {
        "mensaje": "Alerta marcada como atendida",
        "alerta_id": alerta.id,
        "atendida": alerta.atendida
    }


# ============================================================
# RANGOS DE RIESGO
# ============================================================

@app.get(
    "/rangos",
    tags=["rangos"],
    summary="Listar rangos de riesgo configurados",
    description=(
        "Devuelve los rangos de valores y niveles de riesgo "
        "(Excelente, Bueno, ..., Crítico) configurados por tipo "
        "de medición."
    )
)
def listar_rangos(
    db: Session = Depends(get_db)
):

    tipos = (
        db.query(models.TipoMedicion)
        .order_by(models.TipoMedicion.id)
        .all()
    )

    respuesta = []

    for tipo in tipos:

        rangos = (
            db.query(models.RangoRiesgo)
            .filter(
                models.RangoRiesgo.tipo_medicion_id == tipo.id
            )
            .order_by(
                models.RangoRiesgo.valor_min
            )
            .all()
        )

        rangos_respuesta = []

        for rango in rangos:

            nivel = (
                db.query(models.NivelRiesgo)
                .filter(
                    models.NivelRiesgo.id
                    == rango.nivel_riesgo_id
                )
                .first()
            )

            rangos_respuesta.append({
                "id": rango.id,
                "valor_min": rango.valor_min,
                "valor_max": rango.valor_max,
                "nivel_riesgo_id": rango.nivel_riesgo_id,
                "nivel_riesgo": (
                    nivel.nombre
                    if nivel
                    else None
                )
            })

        respuesta.append({
            "tipo_medicion_id": tipo.id,
            "nombre": tipo.nombre,
            "unidad": tipo.unidad,
            "rangos": rangos_respuesta
        })

    return respuesta


# ============================================================
# TIPOS DE MEDICIÓN
# ============================================================

@app.get(
    "/tipos-medicion",
    tags=["tipos_medicion"],
    summary="Listar tipos de medición",
    description="Devuelve todos los tipos de medición registrados en el sistema."
)
def listar_tipos_medicion(
    db: Session = Depends(get_db)
):

    tipos = (
        db.query(models.TipoMedicion)
        .order_by(models.TipoMedicion.id)
        .all()
    )

    resultado = []

    for tipo in tipos:

        resultado.append({
            "id": tipo.id,
            "nombre": tipo.nombre,
            "unidad": tipo.unidad,
            "origen": tipo.origen
        })

    return resultado