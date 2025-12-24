# Creality Cloud Bot - Sistema Completo de Upload

Bot automatizado para descargar, procesar y subir modelos 3D a Creality Cloud con integración real de Alibaba Cloud OSS.

## 🚀 Características

- **Autenticación OAuth2** completa con Creality Cloud
- **Descarga automatizada** de modelos 3D (archivos 3MF)
- **Procesamiento inteligente** con plantillas multi-impresora
- **Redimensionamiento de imágenes** automático (400x400px)
- **Upload real a OSS** usando credenciales STS de Alibaba Cloud
- **Base de datos JSON** para tracking de modelos procesados
- **Sistema de firma HMAC-SHA1** para autenticación OSS
- **Upload multipart** para archivos grandes

## 📁 Estructura del Proyecto

```
f:\Proyectos\Creality_bot\
├── login.py                    # Sistema de autenticación OAuth2
├── models.py                   # Motor principal del bot
├── main.py                     # Script original (referencia)
├── bot_creality.py            # Bot original (métodos integrados)
├── test_upload_completo.py    # Tests completos de funcionalidad
├── test_rapido.py             # Test rápido de funciones básicas
├── models_db.json             # Base de datos de modelos
├── .env                       # Variables de entorno (email/password)
└── README.md                  # Este archivo

# Directorios de trabajo (en E:\ por espacio)
E:\descargas\                  # Archivos 3MF descargados
E:\creality_bot\tmp\           # Archivos temporales (se limpian automáticamente)
E:\creality_bot\plantillas\    # Plantillas para diferentes impresoras
```

## ⚙️ Configuración

### 1. Variables de entorno

Crea un archivo `.env` con tus credenciales:

```env
CREALITY_EMAIL=tu_email@ejemplo.com
CREALITY_PASSWORD=tu_password_aqui
```

### 2. Dependencias

```bash
pip install requests pillow python-dotenv
```

### 3. Estructura de directorios

Los directorios se crean automáticamente, pero puedes crearlos manualmente:

```bash
# En E:\ (o cambiar en models.py si prefieres otra ubicación)
mkdir E:\descargas
mkdir E:\creality_bot\tmp
mkdir E:\creality_bot\plantillas
```

## 🔧 Uso

### Ejecutar el bot completo

```bash
python ejecutar_bot.py
```

El bot automáticamente:
1. Obtiene modelos populares de Creality Cloud
2. Descarga los archivos 3MF
3. Los procesa para diferentes impresoras
4. Sube los perfiles procesados
5. **Limpia archivos temporales automáticamente**

### Test Rápido

```bash
# Ya no disponible - archivos de test eliminados para producción
```

### Test Completo

```bash
python test_upload_completo.py
```

El test completo incluye:
1. **Test de credenciales OSS** - Verifica la obtención de tokens STS
2. **Test de subida de imagen** - Prueba upload de imagen a OSS
3. **Test de flujo completo** - Descarga, procesa y sube un modelo completo

### Uso Programático

```python
from login import login
from models import *

# Autenticación
login_result = login("email@ejemplo.com", "password")

# Listar modelos trending
models = list_trending_models(login_result, page=1, page_size=10)

# Proceso completo de un modelo
db = ModelDatabase()
resultado = proceso_completo_con_subida(
    login_result=login_result,
    model_name="nombre_del_modelo",
    db=db,
    subir_archivos=True  # True para subir realmente
)
```

## 🏗️ Arquitectura Técnica

### Flujo de Upload OSS

El sistema implementa el flujo exacto usado por Creality Cloud:

1. **Obtener credenciales STS**
   ```
   POST /api/cxy/account/v2/getAliyunInfo
   → AccessKeyId, AccessKeySecret, SecurityToken
   ```

2. **Upload de archivo 3MF (Multipart)**
   ```
   POST internal-creality-usa.oss-us-east-1.aliyuncs.com (Iniciar)
   PUT  internal-creality-usa.oss-us-east-1.aliyuncs.com (Upload)
   POST internal-creality-usa.oss-us-east-1.aliyuncs.com (Completar)
   ```

3. **Upload de imagen**
   ```
   PUT pic2-creality.oss-us-east-1.aliyuncs.com
   ```

4. **Registrar modelo en Creality**
   ```
   POST /api/cxy/v3/model/upload3mf
   POST /api/cxy/v3/model/modelGroupDetail
   ```

### Sistema de Firmas OSS

```python
def calcular_signature_oss(method, resource, content_type, date, headers, secret):
    # Implementación HMAC-SHA1 para autenticación OSS
    string_to_sign = f"{method}\n\n{content_type}\n{date}\n{canonical_headers}{resource}"
    signature = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1)
    return base64.b64encode(signature.digest()).decode()
```

## 📊 Base de Datos

Sistema simple basado en JSON (`models_db.json`):

```json
{
    "nombre_modelo": {
        "url": "https://www.crealitycloud.com/model-detail/...",
        "visited": false,
        "download_date": null,
        "process_date": null,
        "upload_date": null,
        "cdn_urls": {},
        "model_group_id": null
    }
}
```

## 🔍 Funciones Principales

### `login.py`
- `login(email, password)` - Autenticación OAuth2 completa

### `models.py`
- `get_aliyun_credentials()` - Obtiene credenciales STS de OSS
- `calcular_signature_oss()` - Calcula firmas HMAC-SHA1 para OSS  
- `subir_archivo_3mf_oss()` - Upload multipart de archivos 3MF
- `subir_imagen_oss()` - Upload directo de imágenes
- `proceso_completo_con_subida()` - Flujo completo de procesamiento
- `list_trending_models()` - Lista modelos trending de Creality

## ⚠️ Consideraciones

- **Rate Limiting**: Respeta los límites de la API de Creality
- **Credenciales STS**: Los tokens expiran, se renuevan automáticamente  
- **Espacio en disco**: Los archivos 3MF pueden ser grandes
- **Plantillas**: Asegúrate de tener plantillas válidas en `/plantillas/`
- **Red**: Requiere conexión estable para uploads grandes

## 🐛 Debugging

### Logs detallados
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Variables de entorno para debug
```env
DEBUG_OSS=1        # Logs detallados de OSS
DEBUG_HTTP=1       # Logs de requests HTTP
```

### Errores comunes

1. **"Error obteniendo credenciales OSS"**
   - Verifica que el login sea exitoso
   - Check conectividad a `www.crealitycloud.com`

2. **"OSS Upload failed"**  
   - Verifica que las credenciales STS no hayan expirado
   - Check conectividad a `*.oss-us-east-1.aliyuncs.com`

3. **"Archivo 3MF no encontrado"**
   - Verifica que exista `E:\descargas\` y sea escribible
   - Check que la descarga del 3MF haya sido exitosa

## 🎯 Roadmap

- [ ] Interface web para monitoreo
- [ ] Procesamiento batch mejorado  
- [ ] Soporte para más tipos de archivo
- [ ] Integración con más plataformas

## 🚀 Despliegue en servidor (Orange Pi / Debian/Ubuntu)

Sigue estos pasos para que el bot se ejecute automáticamente al arrancar tu servidor.

### 1) Prerrequisitos

- Python 3 y Git instalados
- Acceso a Internet

### 2) Clonar y preparar entorno

```bash
sudo apt update
sudo apt install -y python3 python3-venv git

cd /home/orangepi
git clone https://github.com/adriviciano/3d_upload_bot.git
cd 3d_upload_bot

# Crear entorno virtual e instalar dependencias
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Crear archivo .env con valores por defecto (sustituye por los tuyos)
cat > .env << 'EOF'
CREALITY_ACCOUNT="tu_email@example.com"
CREALITY_PASSWORD="tu_password_segura"
EOF

# Prueba manual
python ejecutar_bot.py
```

### 3) Arranque automático con systemd

```bash
sudo tee /etc/systemd/system/creality-bot.service > /dev/null <<'EOF'
[Unit]
Description=Creality 3D Upload Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=orangepi
WorkingDirectory=/home/orangepi/3d_upload_bot
EnvironmentFile=/home/orangepi/3d_upload_bot/.env
ExecStart=/home/orangepi/3d_upload_bot/.venv/bin/python -u ejecutar_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable creality-bot.service
sudo systemctl start creality-bot.service

# Ver estado y logs
systemctl status creality-bot.service
journalctl -u creality-bot.service -f
```

### Notas

- El bot usa carpetas del proyecto: `tmp/` (temporal, se limpia) y `plantillas/`.
- Ajusta `User=` y rutas si tu usuario o ubicación del proyecto son diferentes.
- No subas `.env` al repositorio (ya está excluido en `.gitignore`).
- [ ] Sistema de cola distribuido

## 📝 Licencia

Proyecto de uso personal/educativo. Respeta los términos de servicio de Creality Cloud.

---

**¡Happy Printing! 🖨️✨**