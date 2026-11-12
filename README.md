# Sistema de Auditoría de Registros por OCR (PDFs y MySQL)

Sistema de alta velocidad y precisión para auditar archivos PDF de inscripciones registrales (`[Delegacion]_[Año]_[Registro].pdf`), detectar errores de nombramiento causados por herramientas OCR previas (que tomaron números de secciones secundarias o antecedentes en vez del número real de inscripción) y proponer la nomenclatura correcta mediante validación cruzada espacial.

---

## Características Principales

1. **Segmentación Espacial Inteligente**:
   - **Recuadro Superior (Encabezado)**: Extrae el número de registro oficial (`14055`) y la fecha registral (`2011`).
   - **Pie de Página (Margen Inferior)**: Extrae el número de confirmación inferior (`14055`), omitiendo numeración de páginas (`Pagina 1 de 2`).
   - **Aislamiento de "ANTECEDENTES" (Anti-Trampa)**: Detecta y etiqueta explícitamente cualquier registro previo (como `Registro: 283`) para evitar falsos positivos.

2. **Validación Cruzada**:
   - Si el registro del encabezado coincide con el del pie de página (`14055 == 14055`), la certeza es del **100%**.

3. **Operación en 1-Clic**:
   - `instalar.bat`: Instala dependencias de Python y prepara la base de datos limpia en MySQL.
   - `ejecutar.bat`: Verifica/inicia MySQL de Laragon, levanta el servidor web y abre automáticamente el navegador en `http://localhost:8000`.

4. **Base de Datos MySQL**:
   - Estructura limpia y optimizada con índices en `documentos_auditados` y `lotes_auditoria`.
   - Herramientas integradas en la interfaz para inicializar, reparar o vaciar tablas con un solo clic.

5. **Web Dashboard Moderno**:
   - KPIs en tiempo real: Total auditados, correctos, con discrepancias, tasa de error.
   - Barra de progreso en vivo con velocidad (documentos por segundo).
   - Tabla interactiva con filtros: *Solo Discrepancias*, *Correctos*, *Errores*.
   - **Inspección Visual**: Modal con la página 1 del PDF y cajas delimitadoras coloreadas:
     - 🟩 **Verde**: Registro oficial en encabezado.
     - 🟦 **Azul**: Registro de confirmación en pie de página.
     - 🟥 **Rojo**: Antecedente aislado (la trampa).
   - Exportación de auditoría completa a **Excel (.xlsx)** y **CSV**.
   - Herramienta segura para renombrar archivos individuales o copiar el nombre propuesto.

---

## Inicio Rápido

### 1. Instalación (1-Clic)
Haz doble clic en el archivo:
```bat
instalar.bat
```
Este script verificará Python, instalará las dependencias necesarias y creará la base de datos `auditoria_registros` con sus tablas limpias.

### 2. Ejecución (1-Clic)
Haz doble clic en el archivo:
```bat
ejecutar.bat
```
El script comprobará el servicio MySQL de Laragon, levantará el servidor web local y abrirá tu navegador predeterminado en `http://127.0.0.1:8000`.

---

## Configuración (`.env`)

Puedes personalizar la conexión y la ruta por defecto editando el archivo `.env`:

```ini
# Base de datos MySQL (Valores estándar de Laragon)
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=auditoria_registros

# Ruta predeterminada de escaneo (Soporta red UNC o local)
DEFAULT_SCAN_PATH=\\172.40.5.84\ssdirec\COPIA_REGISTROS

# Servidor Web
WEB_HOST=127.0.0.1
WEB_PORT=8000

# Concurrencia y Rendimiento
MAX_WORKERS=4
OCR_LANG=es
```

---

## Estructura del Código

```
c:\laragon\www\auditar_registros\
├── config\
│   └── settings.py          # Configuración y variables de entorno
├── core\
│   ├── ocr_engine.py        # Motor OCR nativo de Windows (WinOCR)
│   ├── document_analyzer.py # Análisis espacial, validación cruzada y anti-trampa
│   └── auditor.py           # Orquestador concurrente multihilo y seguimiento
├── database\
│   ├── connection.py        # Conector MySQL
│   ├── schema.sql           # Definición DDL de tablas e índices
│   └── db_manager.py        # Consultas, persistencia y gestión de lotes
├── web\
│   ├── app.py               # API REST FastAPI y generador de previews
│   ├── static\              # Frontend (app.js, styles.css)
│   └── templates\
│       └── index.html       # Dashboard con Tailwind CSS y FontAwesome
├── scripts\
│   └── init_db.py           # CLI para inicializar / limpiar la BD
├── tests\
│   ├── test_system.py       # Suite completa de pruebas automatizadas
│   └── muestra_directorio\  # PDFs de prueba listos para escaneo
├── requirements.txt         # Dependencias
├── instalar.bat             # Instalador en 1 clic
├── ejecutar.bat             # Lanzador en 1 clic
└── README.md
```

---

## Pruebas Automatizadas

Para ejecutar la suite de verificación completa:
```bash
python tests/test_system.py
```
Valida la conexión a MySQL, la creación de tablas limpias, la detección OCR de la muestra `01_2011_233.pdf` (obteniendo `14055` al 100% de confianza y aislando el antecedente `283`), la persistencia en base de datos y la generación de vistas previas visuales.
