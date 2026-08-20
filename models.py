from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class Ubicacion(Base):
    __tablename__ = "ubicaciones"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    zona = Column(String(100), nullable=False)
    latitud = Column(Numeric(9, 6), nullable=False)
    longitud = Column(Numeric(9, 6), nullable=False)
    descripcion = Column(Text)


class Sensor(Base):
    __tablename__ = "sensores"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(50), nullable=False)
    modelo = Column(String(50), nullable=False)
    fabricante = Column(String(50), nullable=False)
    tipo = Column(String(50), nullable=False)
    interfaz = Column(String(20), nullable=False)


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    correo = Column(String(100), nullable=False, unique=True)
    rol = Column(String(30), nullable=False)
    contrasena_hash = Column(String(255), nullable=False)
    fecha_registro = Column(DateTime, server_default=func.now())


class Dispositivo(Base):
    __tablename__ = "dispositivos"
    id = Column(Integer, primary_key=True)
    codigo = Column(String(20), nullable=False, unique=True)
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_instalacion = Column(Date, nullable=False)
    estado = Column(String(20), nullable=False)


class DispositivoSensor(Base):
    __tablename__ = "dispositivo_sensores"
    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos.id"), nullable=False)
    sensor_id = Column(Integer, ForeignKey("sensores.id"), nullable=False)
    fecha_instalacion = Column(Date, nullable=False)
    __table_args__ = (UniqueConstraint("dispositivo_id", "sensor_id"),)


class TipoMedicion(Base):
    __tablename__ = "tipos_medicion"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(50), nullable=False)
    unidad = Column(String(20), nullable=False)
    origen = Column(String(20), nullable=False)


class Medicion(Base):
    __tablename__ = "mediciones"
    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos.id"), nullable=False)
    fecha_hora = Column(DateTime, server_default=func.now())


class ValorMedicion(Base):
    __tablename__ = "valores_medicion"
    id = Column(Integer, primary_key=True)
    medicion_id = Column(Integer, ForeignKey("mediciones.id"), nullable=False)
    tipo_medicion_id = Column(Integer, ForeignKey("tipos_medicion.id"), nullable=False)
    valor = Column(Numeric(10, 3), nullable=False)
    __table_args__ = (UniqueConstraint("medicion_id", "tipo_medicion_id"),)


class NivelRiesgo(Base):
    __tablename__ = "niveles_riesgo"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(50), nullable=False)
    color = Column(String(20), nullable=False)
    descripcion = Column(Text)


class RangoRiesgo(Base):
    __tablename__ = "rangos_riesgo"
    id = Column(Integer, primary_key=True)
    tipo_medicion_id = Column(Integer, ForeignKey("tipos_medicion.id"), nullable=False)
    nivel_riesgo_id = Column(Integer, ForeignKey("niveles_riesgo.id"), nullable=False)
    valor_min = Column(Numeric(10, 3), nullable=False)
    valor_max = Column(Numeric(10, 3), nullable=False)


class Clasificacion(Base):
    __tablename__ = "clasificaciones"
    id = Column(Integer, primary_key=True)
    medicion_id = Column(Integer, ForeignKey("mediciones.id"), nullable=False, unique=True)
    nivel_riesgo_id = Column(Integer, ForeignKey("niveles_riesgo.id"), nullable=False)
    confianza = Column(Numeric(5, 2), nullable=False)
    fecha_clasificacion = Column(DateTime, server_default=func.now())


class Alerta(Base):
    __tablename__ = "alertas"
    id = Column(Integer, primary_key=True)
    clasificacion_id = Column(Integer, ForeignKey("clasificaciones.id"), nullable=False)
    fecha_generada = Column(DateTime, server_default=func.now())
    atendida = Column(Boolean, default=False)
    descripcion = Column(Text, nullable=False)


class Calibracion(Base):
    __tablename__ = "calibraciones"
    id = Column(Integer, primary_key=True)
    dispositivo_sensor_id = Column(Integer, ForeignKey("dispositivo_sensores.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    valor_offset = Column(Numeric(6, 3), nullable=False)
    responsable_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)


class Mantenimiento(Base):
    __tablename__ = "mantenimientos"
    id = Column(Integer, primary_key=True)
    dispositivo_id = Column(Integer, ForeignKey("dispositivos.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    tipo = Column(String(30), nullable=False)
    descripcion = Column(Text, nullable=False)
    responsable_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
