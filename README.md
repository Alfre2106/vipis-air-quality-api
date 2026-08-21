# VIPIS — API de Monitoreo de Calidad del Aire

> API REST para el sistema VIPIS (Calidad del Aire Vía Parque Islas de Salamanca), orientado al registro, almacenamiento y consulta de mediciones ambientales.

## 📌 Descripción

**VIPIS (Calidad del Aire Vía Parque Islas de Salamanca)** es un proyecto práctico de desarrollo de software enfocado en el monitoreo de variables ambientales mediante una arquitectura que integra una fuente de datos basada en ESP32/Wokwi, una API REST, una base de datos PostgreSQL y servicios de despliegue en la nube.

El backend está desarrollado con **Python y FastAPI**, utiliza **SQLAlchemy** para la interacción con la base de datos y **PostgreSQL** como sistema de gestión de datos. La base de datos del proyecto utiliza **Neon** y el backend se encuentra preparado para su despliegue mediante **Render**.

El proyecto forma parte de un taller práctico de una asignatura de Inteligencia Artificial y está planteado para evolucionar hacia una solución que también incluya una aplicación de escritorio desarrollada en Java, exportación de registros y análisis asistido por IA mediante Open WebUI.

---

## 🎯 Objetivos del proyecto

La API tiene como objetivo proporcionar un backend centralizado para gestionar información relacionada con:

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

---

## 🏗️ Arquitectura

La arquitectura actual del backend puede representarse de la siguiente manera:

```text
                 ┌──────────────────────┐
                 │     ESP32 / Wokwi    │
                 │ Simulación de datos   │
                 │    ambientales       │
                 └──────────┬───────────┘
                            │
                            │ HTTP / REST
                            ▼
                 ┌──────────────────────┐
                 │       FastAPI        │
                 │       REST API       │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Capa Repository    │
                 │   Operaciones CRUD   │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │      SQLAlchemy      │
                 │         ORM          │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │      PostgreSQL      │
                 │         Neon         │
                 └──────────────────────┘
```

La arquitectura general prevista para el proyecto incluye posteriormente:

```text
ESP32 / Wokwi
      │
      ▼
FastAPI REST API
      │
      ▼
PostgreSQL / Neon
      │
      ├──────────────► Aplicación de escritorio Java
      │                         │
      │                         ▼
      │                    Exportación
      │                      de registros
      │                         │
      │                         ▼
      │                       PDF
      │                         │
      │                         ▼
      │                    Open WebUI
      │                         │
      │                         ▼
      │                 Análisis asistido por IA
      │
      ▼
Render
```

> **Nota:** la aplicación Java, la exportación a PDF y la integración con Open WebUI corresponden a etapas posteriores del desarrollo y no se presentan como funcionalidades terminadas del backend actual.

---

## 🛠️ Tecnologías utilizadas

### Backend

- Python
- FastAPI
- SQLAlchemy
- REST API

### Base de datos

- PostgreSQL
- Neon
- SQLAlchemy ORM

### Desarrollo y herramientas

- Git
- GitHub
- Python
- Variables de entorno
- Postman
- Visual Studio Code

### Despliegue

- Render

### Simulación / IoT

- ESP32
- Wokwi
- Sensores ambientales

---

## 📂 Estructura del proyecto

La estructura principal del backend es:

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

Es el punto de entrada de la aplicación FastAPI.

Se encarga principalmente de:

- Crear la aplicación FastAPI.
- Registrar las rutas.
- Configurar los endpoints CRUD.
- Crear las tablas mediante SQLAlchemy.
- Exponer endpoints específicos para consultas de historial y rangos.

### `database.py`

Contiene la configuración relacionada con la conexión a la base de datos y la configuración de SQLAlchemy.

### `models.py`

Define los modelos utilizados para representar las entidades de la aplicación y su estructura en la base de datos.

### `repository.py`

Implementa la capa Repository utilizada para realizar operaciones CRUD sobre las entidades almacenadas.

### `render.yaml`

Contiene la configuración relacionada con el despliegue del proyecto en Render.

---

## 🗄️ Modelo de datos

El backend contempla entidades relacionadas con diferentes componentes del sistema de monitoreo.

### Monitoreo

- `Ubicacion`
- `Sensor`
- `Dispositivo`
- `DispositivoSensor`

### Mediciones

- `TipoMedicion`
- `Medicion`
- `ValorMedicion`

### Gestión de riesgos

- `NivelRiesgo`
- `RangoRiesgo`
- `Clasificacion`
- `Alerta`

### Mantenimiento

- `Calibracion`
- `Mantenimiento`

### Usuarios

- `Usuario`

La información de ubicación contempla coordenadas geográficas para asociar los puntos de monitoreo con una posición determinada.

---

## 🚀 API REST

El backend utiliza FastAPI para exponer los recursos mediante HTTP.

Para los principales modelos se implementan operaciones CRUD:

```text
GET     /<recurso>
GET     /<recurso>/{id}
POST    /<recurso>
PUT     /<recurso>/{id}
DELETE  /<recurso>/{id}
```

Por ejemplo:

```text
GET /sensores
GET /sensores/1

POST /sensores

PUT /sensores/1

DELETE /sensores/1
```

Los recursos disponibles corresponden a los modelos registrados en la aplicación.

---

## 📊 Historial de mediciones

El backend incluye un endpoint específico para consultar el historial:

```text
GET /historial
```

Este endpoint permite obtener información relacionada con las mediciones registradas, incluyendo datos como:

- Identificador de la medición.
- Fecha y hora.
- Dispositivo.
- Valores registrados.
- Nivel de riesgo.

La respuesta se entrega en formato JSON.

---

## 📈 Rangos de riesgo

La API también dispone del endpoint:

```text
GET /rangos
```

Este recurso permite consultar la configuración de rangos asociados a los tipos de medición y sus niveles de riesgo.

---

## 📚 Documentación automática de la API

FastAPI genera documentación interactiva automáticamente.

### Swagger UI

```text
/docs
```

En una ejecución local:

```text
http://127.0.0.1:8000/docs
```

### ReDoc

```text
/redoc
```

En una ejecución local:

```text
http://127.0.0.1:8000/redoc
```

Estas interfaces permiten explorar los endpoints disponibles y realizar pruebas sobre la API.

---

## ⚙️ Variables de entorno

La configuración de la base de datos debe manejarse mediante variables de entorno.

Se utiliza:

```text
.env
```

y se proporciona:

```text
.env.example
```

como referencia para la configuración.

Las credenciales y cadenas de conexión no deben almacenarse directamente en el código fuente ni publicarse en GitHub.

---

## 💻 Ejecución local

### 1. Clonar el repositorio

```bash
git clone https://github.com/Alfre2106/vipis-air-quality-api.git
```

Entrar al proyecto:

```bash
cd vipis-air-quality-api
```

### 2. Crear un entorno virtual

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

### 4. Configurar las variables de entorno

Crear un archivo:

```text
.env
```

tomando como referencia:

```text
.env.example
```

Configurar allí la conexión correspondiente a PostgreSQL.

### 5. Ejecutar la aplicación

```bash
uvicorn main:app --reload
```

La API estará disponible localmente en:

```text
http://127.0.0.1:8000
```

La documentación interactiva estará disponible en:

```text
http://127.0.0.1:8000/docs
```

---

## ☁️ Despliegue en la nube

El proyecto utiliza:

- **Render** para el despliegue del backend.
- **Neon** para PostgreSQL.

La arquitectura de despliegue es:

```text
                 Internet
                    │
                    ▼
              ┌───────────┐
              │  Render   │
              │  FastAPI  │
              └─────┬─────┘
                    │
                    │ conexión PostgreSQL
                    ▼
              ┌───────────┐
              │   Neon    │
              │ PostgreSQL│
              └───────────┘
```

La configuración específica del servicio de Render se encuentra en:

```text
render.yaml
```

Las credenciales y variables sensibles deben configurarse directamente en el entorno de despliegue.

---

## 🔌 Integración con ESP32 y Wokwi

El proyecto utiliza **ESP32** como plataforma para la adquisición de datos ambientales.

Durante el desarrollo se utiliza **Wokwi** como simulador para generar y enviar datos antes de trabajar con sensores físicos.

Entre las variables contempladas por el proyecto se encuentran:

- Calidad del aire.
- Temperatura.
- Humedad.

Los sensores considerados en la propuesta incluyen:

- MQ-135.
- DHT11.
- DHT22.

El flujo esperado es:

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

## 🖥️ Aplicación de escritorio Java

Como siguiente componente del sistema se está desarrollando una aplicación de escritorio en **Java**.

La aplicación estará conectada con la API y la base de datos a través de los servicios disponibles del backend.

Entre las funcionalidades previstas se encuentran:

- Consulta de mediciones.
- Consulta del historial.
- Visualización de registros.
- Consumo de la API REST.
- Exportación de registros de mediciones.

> 🚧 **En desarrollo.**

---

## 📄 Exportación y análisis mediante IA

Una etapa posterior del proyecto contempla la exportación de los registros de mediciones desde la aplicación de escritorio.

El flujo previsto es:

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
Análisis de las mediciones
```

El objetivo es utilizar un modelo de IA mediante **Open WebUI** para analizar la información contenida en los reportes generados.

> 🚧 **Esta integración se encuentra en desarrollo y no se presenta como una funcionalidad terminada del backend actual.**

---

## 🔐 Consideraciones de seguridad

El proyecto utiliza variables de entorno para evitar almacenar directamente las credenciales de la base de datos en el código fuente.

No deben publicarse:

- Contraseñas.
- Cadenas de conexión privadas.
- Claves API.
- Tokens.
- Credenciales de servicios.

Para una versión de producción más completa se contempla posteriormente la incorporación de mecanismos adicionales como autenticación, autorización, validaciones de seguridad y controles de acceso.

---

## 🧪 Estado actual del proyecto

### Backend

- [x] API desarrollada con FastAPI.
- [x] Integración con SQLAlchemy.
- [x] Integración con PostgreSQL.
- [x] Base de datos en Neon.
- [x] Capa Repository.
- [x] Operaciones CRUD.
- [x] Endpoint de historial.
- [x] Endpoint de rangos.
- [x] Configuración de despliegue en Render.
- [x] Documentación automática mediante FastAPI.

### Integración IoT

- [x] Arquitectura basada en ESP32.
- [x] Simulación mediante Wokwi.
- [x] Definición de variables ambientales.
- [x] Consideración de sensores MQ-135, DHT11 y DHT22.

### Próximas etapas

- [ ] Aplicación de escritorio en Java.
- [ ] Integración completa Java ↔ API.
- [ ] Consulta de registros desde la aplicación.
- [ ] Exportación de mediciones.
- [ ] Generación de PDF.
- [ ] Integración con Open WebUI.
- [ ] Análisis de reportes mediante IA.

---

## 🎓 Contexto académico

VIPIS se desarrolla como un **taller práctico de una asignatura de Inteligencia Artificial**.

El proyecto busca integrar diferentes áreas de desarrollo tecnológico en una única solución:

- Desarrollo backend.
- Diseño y consumo de APIs REST.
- Bases de datos relacionales.
- Despliegue en la nube.
- Simulación de dispositivos IoT.
- Desarrollo de aplicaciones de escritorio.
- Exportación y procesamiento de datos.
- Integración de modelos de IA.

La propuesta tiene como eje el monitoreo de la **calidad del aire en el Vía Parque Islas de Salamanca**.

---

## 👨‍💻 Autor

**Alfredo Mercado Leal**

Estudiante de Ingeniería de Sistemas.

GitHub:

https://github.com/Alfre2106

Repositorio:

https://github.com/Alfre2106/vipis-air-quality-api

---

## 📌 Estado del proyecto

**En desarrollo.**

El backend y la infraestructura principal de API + PostgreSQL + Neon + Render forman la base actual del sistema. Las aplicaciones cliente, la exportación de reportes y el componente de análisis mediante IA se incorporarán progresivamente.
