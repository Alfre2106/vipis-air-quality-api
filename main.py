from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import inspect
from database import Base, engine, get_db
from repository import Repository
import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="API Calidad del Aire - Vía Parque Isla de Salamanca")

MODELOS = [
    models.Ubicacion, models.Sensor, models.Usuario, models.Dispositivo,
    models.DispositivoSensor, models.TipoMedicion, models.Medicion,
    models.ValorMedicion, models.NivelRiesgo, models.RangoRiesgo,
    models.Clasificacion, models.Alerta, models.Calibracion, models.Mantenimiento,
]


def registrar_rutas(app: FastAPI, model):
    nombre = model.__tablename__
    repo = Repository(model)
    columnas = [c.key for c in inspect(model).columns if c.key != "id"]

    @app.get(f"/{nombre}", tags=[nombre])
    def listar(db: Session = Depends(get_db)):
        return repo.get_all(db)

    @app.get(f"/{nombre}/{{item_id}}", tags=[nombre])
    def obtener(item_id: int, db: Session = Depends(get_db)):
        obj = repo.get_by_id(db, item_id)
        if not obj:
            raise HTTPException(status_code=404, detail="No encontrado")
        return obj

    @app.post(f"/{nombre}", tags=[nombre])
    def crear(payload: dict, db: Session = Depends(get_db)):
        data = {k: v for k, v in payload.items() if k in columnas}
        return repo.create(db, data)

    @app.put(f"/{nombre}/{{item_id}}", tags=[nombre])
    def actualizar(item_id: int, payload: dict, db: Session = Depends(get_db)):
        data = {k: v for k, v in payload.items() if k in columnas}
        obj = repo.update(db, item_id, data)
        if not obj:
            raise HTTPException(status_code=404, detail="No encontrado")
        return obj

    @app.delete(f"/{nombre}/{{item_id}}", tags=[nombre])
    def eliminar(item_id: int, db: Session = Depends(get_db)):
        if not repo.delete(db, item_id):
            raise HTTPException(status_code=404, detail="No encontrado")
        return {"eliminado": True}


for modelo in MODELOS:
    registrar_rutas(app, modelo)


@app.get("/historial", tags=["historial"])
def historial(db: Session = Depends(get_db)):
    resultado = []
    mediciones = db.query(models.Medicion).order_by(models.Medicion.fecha_hora.desc()).all()
    for m in mediciones:
        valores = db.query(models.ValorMedicion).filter(models.ValorMedicion.medicion_id == m.id).all()
        clasificacion = db.query(models.Clasificacion).filter(models.Clasificacion.medicion_id == m.id).first()
        nivel = None
        if clasificacion:
            nivel = db.query(models.NivelRiesgo).filter(models.NivelRiesgo.id == clasificacion.nivel_riesgo_id).first()
        dispositivo = db.query(models.Dispositivo).filter(models.Dispositivo.id == m.dispositivo_id).first()
        resultado.append({
            "medicion_id": m.id,
            "fecha_hora": m.fecha_hora,
            "dispositivo": dispositivo.codigo if dispositivo else None,
            "valores": [{"tipo_id": v.tipo_medicion_id, "valor": float(v.valor)} for v in valores],
            "nivel_riesgo": nivel.nombre if nivel else None,
        })
    return resultado


@app.get("/rangos", tags=["historial"])
def rangos(db: Session = Depends(get_db)):
    tipos = db.query(models.TipoMedicion).all()
    rangos_riesgo = db.query(models.RangoRiesgo).all()
    niveles = {n.id: n.nombre for n in db.query(models.NivelRiesgo).all()}
    resultado = []
    for t in tipos:
        rangos_tipo = [r for r in rangos_riesgo if r.tipo_medicion_id == t.id]
        resultado.append({
            "tipo": t.nombre,
            "unidad": t.unidad,
            "rangos": [{"nivel": niveles.get(r.nivel_riesgo_id), "min": float(r.valor_min), "max": float(r.valor_max)} for r in rangos_tipo],
        })
    return resultado
