# VIPIS — API de Monitoreo de Calidad del Aire

> API REST para VIPIS (Calidad del Aire Vía Parque Islas de Salamanca), un proyecto orientado al registro, almacenamiento y consulta de mediciones ambientales mediante una arquitectura backend desplegada en la nube.

## 🌐 API desplegada

El backend está desplegado en **Render** y utiliza **PostgreSQL en Neon** como base de datos.

**Swagger UI / documentación interactiva:**

https://vipis-air-quality-api.onrender.com/docs

> La documentación pública permite explorar los endpoints disponibles de la API y probar sus operaciones.

---

## 📌 ¿Qué es VIPIS?

**VIPIS (Calidad del Aire Vía Parque Islas de Salamanca)** es un proyecto práctico de desarrollo de software enfocado en el monitoreo de variables ambientales.

La solución integra:

- **ESP32 / Wokwi** para la adquisición y simulación de datos ambientales.
- **FastAPI** para construir la API REST.
- **SQLAlchemy** como ORM y capa de acceso a datos.
- **PostgreSQL** como base de datos relacional.
- **Neon** como servicio administrado de PostgreSQL.
- **Render** para el despliegue del backend.

El proyecto forma parte de un taller práctico de una asignatura de Inteligencia Artificial y está diseñado para evolucionar posteriormente con una aplicación de escritorio en Java, exportación de registros y análisis asistido por IA mediante Open WebUI.

---

## 🎯 Objetivos

El backend proporciona una base para gestionar información relacionada con:

- Ubicaciones de monitoreo.
- Sensores.
- Dispositivos.
- Mediciones ambientales.
- Valores de medición.
- Tipos de medición.
- Niveles y rangos de riesgo.
- Clasificaciones.
- Alertas.
- Calibraciones.
- Mantenimientos.
- Usuarios.
- Historial de mediciones.

El objetivo es centralizar las mediciones ambientales en una API REST que pueda ser consumida por diferentes clientes, incluyendo posteriormente una aplicación de escritorio en Java.

---

## 🧰 Stack tecnológico

| Área | Tecnología |
|---|---|
| Lenguaje | Python |
| Backend | FastAPI |
| API | REST |
| ORM | SQLAlchemy |
| Base de datos | PostgreSQL |
| Base de datos cloud | Neon |
| Despliegue | Render |
| IoT / simulación | ESP32 + Wokwi |
| Control de versiones | Git + GitHub |
| Cliente futuro | Java |
| IA futura | Open WebUI |

---

## 🏗️ Arquitectura

### Arquitectura actual

```text
┌───────────────────────┐
│     ESP32 / Wokwi     │
│ Datos ambientales     │
└───────────┬───────────┘
            │
            │ HTTP / REST
            ▼
┌───────────────────────┐
│        FastAPI        │
│       REST API        │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│   Repository Layer    │
│     Operaciones CRUD  │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│      SQLAlchemy       │
│          ORM          │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│ PostgreSQL / Neon     │
└───────────────────────┘
```

### Arquitectura prevista

La solución completa contempla posteriormente:

```text
ESP32 / Wokwi
      │
      ▼
FastAPI REST API
      │
      ▼
PostgreSQL / Neon
      │
      ├──────────────► Aplicación Java
      │                      │
      │                      ▼
      │               Exportación
      │               de mediciones
      │                      │
      │                      ▼
      │                     PDF
      │                      │
      │                      ▼
      │                 Open WebUI
      │                      │
      │                      ▼
      │                Modelo de IA
      │                      │
      │                      ▼
      │             Análisis del reporte
      │
      ▼
    Render
```

> **Importante:** la aplicación Java, la exportación a PDF y la integración con Open WebUI corresponden a etapas posteriores. No se presentan como funcionalidades terminadas del backend actual.

---

## 🚀 API REST

La API está desarrollada con FastAPI y expone recursos mediante HTTP.

Los recursos principales utilizan operaciones CRUD:

```text
GET     /<recurso>
GET     /<recurso>/{item_id}
POST    /<recurso>
PUT     /<recurso>/{item_id}
DELETE  /<recurso>/{item_id}
```

### Recursos

La API desplegada contempla recursos para:

- `ubicaciones`
- `sensores`
- `dispositivos`
- `dispositivo_sensor`
- `tipos_medicion`
- `mediciones`
- `valores_medicion`
- `niveles_riesgo`
- `rangos_riesgo`
- `clasificaciones`
- `alertas`
- `calibraciones`
- `mantenimientos`
- `usuarios`

Además, dispone de endpoints específicos para consultas:

```text
GET /historial
GET /rangos
```

### Ejemplo de CRUD

```text
GET     /mediciones
POST    /mediciones
GET     /mediciones/{item_id}
PUT     /mediciones/{item_id}
DELETE  /mediciones/{item_id}
```

La documentación interactiva de FastAPI permite consultar los esquemas, parámetros, respuestas y operaciones disponibles.

---

## 📊 Historial de mediciones

El backend incluye:

```text
GET /historial
```

Este endpoint está destinado a consultar información histórica de las mediciones registradas.

El historial permite servir como fuente de información para los clientes que posteriormente consumirán la API.

---

## 📈 Rangos

La API incluye:

```text
GET /rangos
```

Este endpoint permite consultar los rangos utilizados por el sistema para representar los niveles asociados a las mediciones.

---

## 🗄️ Base de datos

VIPIS utiliza **PostgreSQL** como sistema gestor de base de datos.

La base de datos se encuentra alojada en **Neon**, mientras que el backend se ejecuta en **Render**.

```text
             Render
                │
                │ conexión PostgreSQL
                ▼
              Neon
                │
                ▼
          PostgreSQL
```

### Modelos principales

#### Monitoreo

- `Ubicacion`
- `Sensor`
- `Dispositivo`
- `DispositivoSensor`

#### Mediciones

- `TipoMedicion`
- `Medicion`
- `ValorMedicion`

#### Gestión de riesgo

- `NivelRiesgo`
- `RangoRiesgo`
- `Clasificacion`
- `Alerta`

#### Mantenimiento

- `Calibracion`
- `Mantenimiento`

#### Usuarios

- `Usuario`

---

## 📁 Estructura del proyecto

```text
vipis-air-quality-api/
│
├── main.py
├── database.py
├── models.py
├── repository.py
├── requirements.txt
├── render.yaml
├── .env.example
├── .gitignore
└── README.md
```

### `main.py`

Punto de entrada de la aplicación FastAPI.

Contiene la configuración de la aplicación y las rutas de la API.

### `database.py`

Contiene la configuración de la conexión con PostgreSQL y los componentes relacionados con SQLAlchemy.

### `models.py`

Define los modelos utilizados por la aplicación y su representación en la base de datos.

### `repository.py`

Implementa operaciones de acceso y manipulación de datos mediante una capa Repository.

### `render.yaml`

Contiene la configuración utilizada para el despliegue del servicio en Render.

### `requirements.txt`

Define las dependencias Python necesarias para ejecutar el backend.

### `.env.example`

Sirve como referencia para configurar las variables de entorno sin publicar credenciales reales.

---

## 📚 Documentación de la API

FastAPI genera automáticamente documentación basada en OpenAPI.

### Swagger UI

Localmente:

```text
http://127.0.0.1:8000/docs
```

En producción:

https://vipis-air-quality-api.onrender.com/docs

### ReDoc

Localmente:

```text
http://127.0.0.1:8000/redoc
```

La documentación permite explorar la API sin necesidad de consultar manualmente cada ruta del código.

---

## 🔌 ESP32 y Wokwi

La propuesta utiliza **ESP32** como plataforma para la adquisición de datos ambientales.

Durante el desarrollo se utiliza **Wokwi** para simular el comportamiento del dispositivo y enviar datos hacia el backend.

Las variables contempladas incluyen:

- Calidad del aire.
- Temperatura.
- Humedad.

Los sensores considerados en la propuesta son:

- **MQ-135** — calidad del aire.
- **DHT11** — temperatura y humedad.
- **DHT22** — temperatura y humedad.

Flujo de integración:

```text
ESP32 / Wokwi
      │
      │ Datos ambientales
      ▼
FastAPI
      │
      ▼
PostgreSQL / Neon
```

---

## ☁️ Despliegue

El backend se encuentra desplegado en **Render**.

La arquitectura de despliegue es:

```text
Internet
   │
   ▼
┌───────────────┐
│    Render     │
│    FastAPI    │
└───────┬───────┘
        │
        │ PostgreSQL
        ▼
┌───────────────┐
│     Neon      │
│  PostgreSQL   │
└───────────────┘
```

El archivo:

```text
render.yaml
```

contiene la configuración asociada al despliegue.

Las credenciales y variables sensibles deben configurarse mediante variables de entorno en el entorno de ejecución.

---

## 💻 Ejecución local

### 1. Clonar el repositorio

```bash
git clone https://github.com/Alfre2106/vipis-air-quality-api.git
cd vipis-air-quality-api
```

### 2. Crear el entorno virtual

En Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

En Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

Crear:

```text
.env
```

utilizando `.env.example` como referencia.

Configurar la conexión correspondiente a PostgreSQL.

### 5. Ejecutar FastAPI

```bash
uvicorn main:app --reload
```

La API estará disponible en:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

---

## 🔐 Seguridad

Las credenciales y configuraciones sensibles deben mantenerse fuera del código fuente.

No deben publicarse:

- Contraseñas.
- Cadenas de conexión privadas.
- Claves API.
- Tokens.
- Credenciales de servicios.

El proyecto utiliza variables de entorno para separar la configuración sensible del código.

Para una evolución posterior del sistema se pueden incorporar mecanismos adicionales de autenticación, autorización y control de acceso.

---

## 🖥️ Aplicación de escritorio en Java

Como siguiente componente del proyecto se está desarrollando una aplicación de escritorio en **Java**.

La aplicación consumirá la API REST de VIPIS para trabajar con la información almacenada en PostgreSQL.

Las funcionalidades previstas incluyen:

- Consulta de mediciones.
- Consulta del historial.
- Visualización de registros.
- Consumo de endpoints REST.
- Exportación de registros.

**Estado:** 🚧 En desarrollo.

---

## 🤖 Exportación, PDF y análisis con IA

Una etapa posterior contempla generar un reporte de las mediciones desde la aplicación Java y utilizarlo como entrada para un flujo de análisis mediante IA.

Flujo previsto:

```text
Mediciones
    │
    ▼
API / PostgreSQL
    │
    ▼
Aplicación Java
    │
    ▼
Exportación de registros
    │
    ▼
PDF
    │
    ▼
Open WebUI
    │
    ▼
Modelo de IA
    │
    ▼
Análisis del reporte
```

El objetivo es utilizar el documento generado a partir de las mediciones como fuente para realizar análisis asistidos por un modelo de IA mediante **Open WebUI**.

**Estado:** 🚧 En desarrollo.

---

## 🧪 Estado del proyecto

### Backend

- [x] API REST con FastAPI.
- [x] SQLAlchemy.
- [x] PostgreSQL.
- [x] Base de datos en Neon.
- [x] Capa Repository.
- [x] Operaciones CRUD.
- [x] Historial de mediciones.
- [x] Consulta de rangos.
- [x] Despliegue en Render.
- [x] Documentación automática con Swagger/OpenAPI.

### IoT

- [x] Arquitectura basada en ESP32.
- [x] Simulación mediante Wokwi.
- [x] Variables ambientales definidas.
- [x] Integración planteada para MQ-135, DHT11 y DHT22.

### Próximas etapas

- [ ] Aplicación de escritorio Java.
- [ ] Integración completa Java ↔ API.
- [ ] Consulta de registros desde Java.
- [ ] Exportación de mediciones.
- [ ] Generación de PDF.
- [ ] Integración con Open WebUI.
- [ ] Análisis de reportes mediante IA.

---

## 🎓 Contexto académico

VIPIS se desarrolla como un **taller práctico de una asignatura de Inteligencia Artificial**.

El proyecto integra diferentes áreas:

- Desarrollo backend.
- Diseño de APIs REST.
- Bases de datos relacionales.
- ORM con SQLAlchemy.
- Despliegue en la nube.
- Simulación IoT.
- Desarrollo de aplicaciones de escritorio.
- Exportación y procesamiento de datos.
- Integración de IA.

La propuesta tiene como eje el monitoreo de la **calidad del aire en el Vía Parque Islas de Salamanca**.

---

## 👨‍💻 Autor

**Alfredo Mercado Leal**

Estudiante de Ingeniería de Sistemas.

**GitHub:**

https://github.com/Alfre2106

**Repositorio:**

https://github.com/Alfre2106/vipis-air-quality-api

---

## 📌 Estado

**En desarrollo.**

La infraestructura principal **FastAPI + PostgreSQL + Neon + Render** se encuentra implementada. Las siguientes etapas ampliarán el sistema mediante la aplicación Java, la exportación de reportes y el análisis asistido por IA.
