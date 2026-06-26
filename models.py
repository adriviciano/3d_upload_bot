import requests
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from login import LoginResult
import os
import shutil
import zipfile
import glob
import datetime
import re
import time
from PIL import Image
import tempfile
import uuid
import hashlib
import base64
import hmac
from datetime import datetime
import xml.etree.ElementTree as ET
from tqdm import tqdm
from dimensiones import (
    obtener_dimensiones_modelo,
    obtener_dimensiones_cama,
    modelo_cabe_en_cama,
    MARGEN_SEGURIDAD_MM,
)


def _crear_placeholder_plate(dest_path: str) -> None:
    """Crea una imagen placeholder 400x400 cuando no existe plate_1.png."""
    img = Image.new("RGB", (400, 400), color=(64, 64, 64))
    img.save(dest_path, format="PNG")


def _sanear_nombre_modelo(nombre: str) -> str:
    """Normaliza el nombre para rutas y archivos."""
    return nombre.strip().replace("/", "_").replace("\\", "_")

CLOUD_BASE_URL = "https://www.crealitycloud.com"
OSS_3MF_BASE_URL = "https://internal-creality-usa.oss-us-east-1.aliyuncs.com"
OSS_IMAGE_BASE_URL = "https://pic2-creality.oss-us-east-1.aliyuncs.com"
CDN_IMAGE_BASE_URL = "https://pic2-cdn.creality.com/crealityCloud/upload"


class DailyLimitReached(Exception):
    """Se alcanzó el límite diario de operaciones de subida de Creality."""
    pass


def _es_limite_diario(msg: str) -> bool:
    """Detecta el mensaje de límite diario de operaciones de Creality."""
    if not msg:
        return False
    msg_lower = msg.lower()
    return (
        "operations has reached the limit" in msg_lower
        or "limit of today" in msg_lower
        or "come again tomorrow" in msg_lower
    )


@dataclass
class ModelInfo:
    id: str
    name: str
    description: Optional[str]
    author: Optional[str]
    download_count: int
    like_count: int
    price: float
    is_free: bool
    thumbnail_url: Optional[str]
    created_at: Optional[str]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModelInfo':
        # Extraer URL del thumbnail de la primera imagen en covers
        thumbnail_url = None
        if data.get('covers') and len(data['covers']) > 0:
            thumbnail_url = data['covers'][0].get('url')
        
        return cls(
            id=str(data.get('id', '')),
            name=data.get('groupName', ''),  # El nombre del modelo está en 'groupName'
            description=data.get('userInfo', {}).get('introduction'),  # Descripción del autor
            author=data.get('userInfo', {}).get('nickName'),  # Nombre del autor
            download_count=int(data.get('downloadCount', 0)),
            like_count=int(data.get('likeCount', 0)),
            price=float(data.get('totalPrice', 0)),
            is_free=data.get('isPay') == False,  # isPay: false = gratis
            thumbnail_url=thumbnail_url,
            created_at=str(data.get('createTime', ''))
        )


@dataclass
class AliyunCredentials:
    """Credenciales de Alibaba Cloud STS para OSS."""
    access_key_id: str
    secret_access_key: str
    session_token: str
    expired_time: int
    life_time: int
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AliyunCredentials':
        return cls(
            access_key_id=data.get('accessKeyId', ''),
            secret_access_key=data.get('secretAccessKey', ''),
            session_token=data.get('sessionToken', ''),
            expired_time=int(data.get('expiredTime', 0)),
            life_time=int(data.get('lifeTime', 0))
        )
    
    def is_expired(self) -> bool:
        """Verifica si las credenciales han expirado."""
        import time
        return time.time() > self.expired_time


@dataclass
class ModelEntry:
    """Entrada de modelo en la base de datos local."""
    name: str
    url: str
    model_id: str
    visited: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "model_id": self.model_id,
            "visited": self.visited
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModelEntry':
        return cls(
            name=data.get("name", ""),
            url=data.get("url", ""),
            model_id=data.get("model_id", ""),
            visited=data.get("visited", False)
        )


class ModelDatabase:
    """Base de datos local para modelos de Creality Cloud."""
    
    def __init__(self, db_path: str = "models_db.json"):
        self.db_path = Path(db_path)
        self.models: Dict[str, ModelEntry] = {}
        self.load_database()
    
    def load_database(self) -> None:
        """Cargar la base de datos desde archivo."""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.models = {}
                    for name, entry in data.items():
                        # Manejar formato antiguo sin model_id
                        if isinstance(entry, dict) and 'model_id' not in entry:
                            # Extraer model_id de la URL
                            url = entry.get('url', '')
                            if '/model-detail/' in url:
                                model_id = url.split('/model-detail/')[-1]
                                entry['model_id'] = model_id
                        self.models[name] = ModelEntry.from_dict(entry)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error cargando base de datos: {e}. Iniciando con base vacía.")
                self.models = {}
    
    def save_database(self) -> None:
        """Guardar la base de datos en archivo."""
        data = {name: entry.to_dict() for name, entry in self.models.items()}
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add_model(self, name: str, model_id: str, visited: bool = False) -> None:
        """Agregar o actualizar un modelo en la base de datos."""
        url = f"https://www.crealitycloud.com/model-detail/{model_id}"
        self.models[name] = ModelEntry(name=name, url=url, model_id=model_id, visited=visited)
    
    def mark_as_visited(self, name: str) -> bool:
        """Marcar un modelo como visitado."""
        if name in self.models:
            self.models[name].visited = True
            return True
        return False
    
    def get_unvisited_models(self) -> Dict[str, ModelEntry]:
        """Obtener todos los modelos no visitados."""
        return {name: entry for name, entry in self.models.items() if not entry.visited}
    
    def get_visited_models(self) -> Dict[str, ModelEntry]:
        """Obtener todos los modelos visitados."""
        return {name: entry for name, entry in self.models.items() if entry.visited}
    
    def get_model(self, name: str) -> Optional[ModelEntry]:
        """Obtener un modelo específico por nombre."""
        return self.models.get(name)
    
    def get_all_models(self) -> Dict[str, ModelEntry]:
        """Obtener todos los modelos."""
        return self.models.copy()
    
    def count_models(self) -> tuple[int, int, int]:
        """Contar modelos (total, visitados, no visitados)."""
        total = len(self.models)
        visited = sum(1 for entry in self.models.values() if entry.visited)
        unvisited = total - visited
        return total, visited, unvisited


def obtener_modelos_populares(
    login_result: LoginResult,
    db: 'ModelDatabase',
    max_paginas: int = 5
) -> List[str]:
    """
    Obtiene modelos populares no visitados.
    Busca en múltiples páginas hasta encontrar modelos sin procesar.

    Returns:
        Lista de nombres de modelos sin procesar (strings)
    """
    for pagina in range(1, max_paginas + 1):
        modelos_nuevos = []
        modelos = list_trending_models(
            login_result=login_result,
            page=pagina,
            page_size=20,
            is_pay=2,
            save_to_db=False
        )
        for modelo in modelos:
            entrada = db.get_model(modelo.name)
            # Si no existe en BD o existe pero no visitado
            if not entrada or not entrada.visited:
                db.add_model(modelo.name, modelo.id, visited=False)
                modelos_nuevos.append(modelo.name)

        # Si encontró modelos sin procesar, retornar
        if modelos_nuevos:
            db.save_database()
            return modelos_nuevos

        # Si última página, parar
        if len(modelos) < 20:
            break

    db.save_database()
    return []


def list_trending_models(
    login_result: LoginResult,
    page: int = 1,
    page_size: int = 20,
    trend_type: int = 3,
    filter_type: int = 10,
    is_pay: int = 2,
    is_exclusive: int = 0,
    promo_type: int = 0,
    is_vip: int = 0,
    multi_mark: int = 0,
    has_cfg_file: int = 0,
    has_cube_me_model: int = 1,
    is_pick_model: int = 0,
    is_print_always_success: int = 0,
    timeout: int = 15,
    save_to_db: bool = True,
    db_path: str = "models_db.json"
) -> List[ModelInfo]:
    """
    Obtiene la lista de modelos trending de Creality Cloud.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        page: Número de página (empezando por 1)
        page_size: Cantidad de modelos por página
        trend_type: Tipo de tendencia (1 = trending)
        filter_type: Tipo de filtro
        is_pay: 2 = gratis, 1 = pago, 0 = todos
        is_exclusive: 0 = todos, 1 = exclusivos
        promo_type: Tipo de promoción
        is_vip: 0 = todos, 1 = solo VIP
        multi_mark: Marcas múltiples
        has_cfg_file: Tiene archivo de configuración
        timeout: Timeout en segundos
    
    Returns:
        Lista de objetos ModelInfo con la información de los modelos
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id. Asegúrate de hacer login primero.")
    
    # Configurar headers específicos para la API de modelos
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "__cxy_token_": login_result.model_token,
        "__cxy_uid_": str(login_result.model_user_id),
        "__cxy_brand_": "creality",
        "__cxy_os_lang_": "0",  # Español según la petición original
        "__cxy_app_ver_": "6.0.0",
        "__cxy_app_ch_": "Chrome 142.0.0.0",
        "__cxy_os_ver_": "Windows 10",
        "__cxy_timezone_": "3600",
        "__cxy_app_id_": "creality_model",
        "__cxy_platform_": "2",
        "Origin": CLOUD_BASE_URL,
        "Referer": f"{CLOUD_BASE_URL}/es/",
    }
    
    # Preparar el payload de la petición
    payload = {
        "page": page,
        "pageSize": page_size,
        "trendType": trend_type,
        "filterType": filter_type,
        "isPay": is_pay,
        "isExclusive": is_exclusive,
        "promoType": promo_type,
        "isVip": is_vip,
        "multiMark": multi_mark,
        "hasCfgFile": has_cfg_file,
        "hasCubeMeModel": has_cube_me_model,
        "isPickModel": is_pick_model,
        "isPrintAlwaysSuccess": is_print_always_success
    }
    
    # Realizar la petición
    response = login_result.session.post(
        f"{CLOUD_BASE_URL}/api/cxy/v3/model/listTrend",
        json=payload,
        headers=headers,
        timeout=timeout
    )
    response.raise_for_status()
    
    # Procesar la respuesta
    try:
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Error en la API: {data.get('msg', 'Error desconocido')}")
        
        models_data = data.get("result", {}).get("list", [])
        models = [ModelInfo.from_dict(model) for model in models_data]
        
        # Guardar modelos en la base de datos si está habilitado
        if save_to_db:
            db = ModelDatabase(db_path)
            for model_data in models_data:
                model_name = model_data.get('groupName', '')
                model_id = model_data.get('id', '')
                if model_name and model_id:
                    db.add_model(model_name, model_id)
            db.save_database()
        
        return models
        
    except ValueError as e:
        raise RuntimeError(f"Respuesta JSON inválida: {e}")


def list_free_models(login_result: LoginResult, page: int = 1, page_size: int = 20, save_to_db: bool = True, db_path: str = "models_db.json") -> List[ModelInfo]:
    """Obtiene solo los modelos gratuitos."""
    return list_trending_models(
        login_result=login_result,
        page=page,
        page_size=page_size,
        is_pay=2,  # 2 = solo modelos gratis
        save_to_db=save_to_db,
        db_path=db_path
    )


def list_paid_models(login_result: LoginResult, page: int = 1, page_size: int = 20, save_to_db: bool = True, db_path: str = "models_db.json") -> List[ModelInfo]:
    """Obtiene solo los modelos de pago."""
    return list_trending_models(
        login_result=login_result,
        page=page,
        page_size=page_size,
        is_pay=1,  # 1 = solo modelos de pago
        save_to_db=save_to_db,
        db_path=db_path
    )


def search_models_by_name(models: List[ModelInfo], search_term: str) -> List[ModelInfo]:
    """Filtra los modelos por nombre (búsqueda local)."""
    search_term = search_term.lower()
    return [model for model in models if search_term in model.name.lower()]


@dataclass
class Model3MFInfo:
    """Información de un archivo 3MF de un modelo específico."""
    id: str
    name: str
    second_name: str
    size: int
    thumbnail: str
    layer_height: str
    infill_density: str
    wall_loops: str
    printer_name: str
    print_time: int
    filament_length: float
    filament_weight: float
    download_count: int
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Model3MFInfo':
        return cls(
            id=str(data.get('id', '')),
            name=data.get('name', ''),
            second_name=data.get('secondName', ''),
            size=int(data.get('size', 0)),
            thumbnail=data.get('thumbnail', ''),
            layer_height=data.get('layerHeight', ''),
            infill_density=data.get('sparseInfillDensity', ''),
            wall_loops=data.get('wallLoops', ''),
            printer_name=data.get('printerName', ''),
            print_time=int(data.get('printTime', 0)),
            filament_length=float(data.get('filamentLen', 0.0)),
            filament_weight=float(data.get('filamentWeight', 0.0)),
            download_count=int(data.get('downloadCount', 0))
        )


def get_model_3mf_list(
    login_result: LoginResult,
    model_id: str,
    page: int = 1,
    page_size: int = 10,
    filter_type: int = 3,
    timeout: int = 15
) -> Optional[Model3MFInfo]:
    """
    Obtiene la lista de archivos 3MF de un modelo específico y retorna el primero.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        model_id: ID del modelo (el que está en la URL del modelo)
        page: Número de página
        page_size: Tamaño de página
        filter_type: Tipo de filtro
        timeout: Timeout en segundos
    
    Returns:
        Model3MFInfo del primer archivo 3MF encontrado, o None si no hay archivos
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id. Asegúrate de hacer login primero.")
    
    # Configurar headers específicos para la API de 3MF
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "__cxy_token_": login_result.model_token,
        "__cxy_uid_": str(login_result.model_user_id),
        "__cxy_brand_": "creality",
        "__cxy_os_lang_": "0",
        "__cxy_app_ver_": "6.0.0",
        "__cxy_app_ch_": "Chrome 142.0.0.0",
        "__cxy_os_ver_": "Windows 10",
        "__cxy_timezone_": "3600",
        "__cxy_app_id_": "creality_model",
        "__cxy_platform_": "2",
        "Origin": CLOUD_BASE_URL,
        "Referer": f"{CLOUD_BASE_URL}/es/",
    }
    
    # Preparar el payload
    payload = {
        "modelGroupId": model_id,
        "pageSize": page_size,
        "page": page,
        "filterType": filter_type
    }
    
    # Realizar la petición
    response = login_result.session.post(
        f"{CLOUD_BASE_URL}/api/cxy/v3/model/3mfList",
        json=payload,
        headers=headers,
        timeout=timeout
    )
    response.raise_for_status()
    
    # Procesar la respuesta
    try:
        data = response.json()
        
        if data.get("code") != 0:
            raise RuntimeError(f"Error en la API: {data.get('msg', 'Error desconocido')}")
        
        files_list = data.get("result", {}).get("list", [])
        
        # Retornar el primer elemento si existe
        if files_list:
            return Model3MFInfo.from_dict(files_list[0])
        
        return None
        
    except ValueError as e:
        raise RuntimeError(f"Respuesta JSON inválida: {e}")


def download_3mf_file(
    login_result: LoginResult,
    file_3mf_id: str,
    timeout: int = 30
) -> Optional[str]:
    """
    Descarga un archivo 3MF específico.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        file_3mf_id: ID del archivo 3MF (obtenido de get_model_3mf_list)
        timeout: Timeout en segundos
    
    Returns:
        URL de descarga del archivo o None si falla
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id. Asegúrate de hacer login primero.")
    
    # Configurar headers específicos para la API de descarga
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "__cxy_token_": login_result.model_token,
        "__cxy_uid_": str(login_result.model_user_id),
        "__cxy_brand_": "creality",
        "__cxy_os_lang_": "0",
        "__cxy_app_ver_": "6.0.0",
        "__cxy_app_ch_": "Chrome 142.0.0.0",
        "__cxy_os_ver_": "Windows 10",
        "__cxy_timezone_": "3600",
        "__cxy_app_id_": "creality_model",
        "__cxy_platform_": "2",
        "Origin": CLOUD_BASE_URL,
        "Referer": f"{CLOUD_BASE_URL}/es/",
    }
    
    # Preparar el payload
    payload = {
        "id": file_3mf_id
    }
    
    # Realizar la petición
    response = login_result.session.post(
        f"{CLOUD_BASE_URL}/api/cxy/v3/model/3mfDownload",
        json=payload,
        headers=headers,
        timeout=timeout
    )
    response.raise_for_status()
    
    # Procesar la respuesta
    try:
        data = response.json()
        
        if data.get("code") != 0:
            raise RuntimeError(f"Error en la API: {data.get('msg', 'Error desconocido')}")
        
        # Retornar la URL de descarga si existe
        download_url = data.get("result", {}).get("downloadUrl")
        return download_url
        
    except ValueError as e:
        raise RuntimeError(f"Respuesta JSON inválida: {e}")


def process_model_complete(
    login_result: LoginResult,
    model_name: str,
    db: ModelDatabase,
    timeout: int = 30
) -> Optional[tuple[Model3MFInfo, str]]:
    """
    Proceso completo: obtiene la información 3MF de un modelo y la URL de descarga.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        model_name: Nombre del modelo en la base de datos
        db: Base de datos de modelos
        timeout: Timeout en segundos
    
    Returns:
        Tupla (Model3MFInfo, download_url) o None si falla
    """
    
    # Obtener el modelo de la base de datos
    model_entry = db.get_model(model_name)
    if not model_entry:
        print(f"❌ Modelo '{model_name}' no encontrado en la base de datos")
        return None
    
    print(f"📋 Procesando modelo: {model_name}")
    print(f"🆔 ID del modelo: {model_entry.model_id}")
    
    try:
        # Obtener información del primer archivo 3MF
        print("🔍 Obteniendo información de archivos 3MF...")
        model_3mf_info = get_model_3mf_list(login_result, model_entry.model_id, timeout=timeout)
        
        if not model_3mf_info:
            print("❌ No se encontraron archivos 3MF para este modelo")
            return None
        
        print(f"✅ Archivo 3MF encontrado:")
        print(f"   📁 Nombre: {model_3mf_info.name}")
        print(f"   📄 Configuración: {model_3mf_info.second_name}")
        print(f"   📏 Tamaño: {model_3mf_info.size:,} bytes")
        print(f"   🖨️ Impresora: {model_3mf_info.printer_name}")
        
        # Obtener URL de descarga
        print("⬇️ Obteniendo URL de descarga...")
        download_url = download_3mf_file(login_result, model_3mf_info.id, timeout=timeout)
        
        if not download_url:
            print("❌ No se pudo obtener la URL de descarga")
            return None
        
        print(f"✅ URL de descarga obtenida: {download_url}")
        
        # Marcar el modelo como visitado
        db.mark_as_visited(model_name)
        db.save_database()
        print(f"✅ Modelo '{model_name}' marcado como visitado")
        
        return (model_3mf_info, download_url)
        
    except Exception as e:
        print(f"❌ Error procesando modelo '{model_name}': {e}")
        return None


def procesar3MF(model_name: str, archivo_3mf_path: str) -> Optional[str]:
    """
    Procesa un archivo 3MF y genera perfiles por impresora en un workspace aislado.
    """

    tmp_root = os.getenv("TMP_ROOT", r"E:\creality_bot\tmp")
    plantillas_folder = os.getenv("PLANTILLAS_FOLDER", r"E:\creality_bot\plantillas")

    os.makedirs(tmp_root, exist_ok=True)

    clean_name = _sanear_nombre_modelo(model_name)
    work_folder = os.path.join(tmp_root, f"{clean_name}_work")
    model_folder = os.path.join(tmp_root, clean_name)

    # Limpiar workspace previo para evitar zips enormes
    if os.path.exists(work_folder):
        shutil.rmtree(work_folder, ignore_errors=True)
    if os.path.exists(model_folder):
        shutil.rmtree(model_folder, ignore_errors=True)

    os.makedirs(work_folder, exist_ok=True)
    os.makedirs(model_folder, exist_ok=True)

    try:
        print(f"🔧 Procesando archivo 3MF: {model_name}")

        # 1. Copiar el archivo 3MF al workspace
        dest_path = os.path.join(work_folder, os.path.basename(archivo_3mf_path))
        shutil.copy2(archivo_3mf_path, dest_path)
        print(f"✅ Archivo copiado a {dest_path}")

        # 2. Cambiar extensión a .zip
        zip_path = os.path.splitext(dest_path)[0] + ".zip"
        os.rename(dest_path, zip_path)

        # 3. Descomprimir el zip en work_folder
        with zipfile.ZipFile(zip_path, "r", allowZip64=True) as zip_ref:
            zip_ref.extractall(work_folder)
        os.remove(zip_path)
        print(f"✅ Archivo descomprimido en {work_folder}")

        metadata_folder = os.path.join(work_folder, "Metadata")

        # 4. Modificar Metadata/creality.config
        config_path = os.path.join(metadata_folder, "creality.config")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                today = datetime.now().strftime("%Y-%m-%d")
                content = re.sub(r'(CreationDate" value=")[:\d\- ]*(")', fr"\1{today}\2", content)
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print("✅ Metadata/creality.config actualizado con la fecha actual")
            except Exception as e:
                print(f"⚠️ Error actualizando creality.config: {e}")
        else:
            print("⚠️ creality.config no encontrado en Metadata")

        # 5. Eliminar archivos innecesarios de Metadata
        if os.path.exists(metadata_folder):
            try:
                for f in ["custom_gcode_per_layer.xml", "project_settings.config"]:
                    f_path = os.path.join(metadata_folder, f)
                    if os.path.exists(f_path):
                        os.remove(f_path)
                for f in glob.glob(os.path.join(metadata_folder, "*.gcode")) + glob.glob(os.path.join(metadata_folder, "*.md5")):
                    os.remove(f)
                print("✅ Archivos innecesarios eliminados de Metadata")
            except Exception as e:
                print(f"⚠️ Error eliminando archivos de Metadata: {e}")
        else:
            print("⚠️ Carpeta Metadata no encontrada")

        # 6. Procesar plate_1.png
        plate_file = os.path.join(metadata_folder, "plate_1.png")
        final_image_path = os.path.join(model_folder, "plate_1.png")

        if os.path.exists(plate_file):
            try:
                processed_image_path = procesar_imagen(plate_file)
                shutil.copy(processed_image_path, final_image_path)
                if os.path.exists(processed_image_path):
                    os.remove(processed_image_path)
                print(f"✅ plate_1.png procesado y copiado a {model_folder}")
            except Exception as e:
                print(f"⚠️ Error procesando plate_1.png: {e}")
                try:
                    shutil.copy(plate_file, final_image_path)
                    print(f"✅ plate_1.png copiado sin procesar a {model_folder}")
                except Exception as e2:
                    print(f"⚠️ Error copiando plate_1.png original: {e2}")
        else:
            print("⚠️ plate_1.png no encontrado, creando placeholder")
            _crear_placeholder_plate(final_image_path)

        # 6.5. Calcular dimensiones del modelo (para filtrar por cama)
        dims_modelo = obtener_dimensiones_modelo(work_folder)
        if dims_modelo:
            print(f"📐 Dimensiones del modelo: "
                  f"{dims_modelo[0]:.1f} x {dims_modelo[1]:.1f} x {dims_modelo[2]:.1f} mm")
        else:
            print("⚠️ No se pudieron determinar las dimensiones del modelo; "
                  "no se filtrará por tamaño de cama")

        # 7. Procesar cada impresora en plantillas
        impresoras_disponibles = []
        if os.path.exists(plantillas_folder):
            impresoras_disponibles = [
                f for f in os.listdir(plantillas_folder)
                if os.path.isdir(os.path.join(plantillas_folder, f))
            ]

        if not impresoras_disponibles:
            print(f"⚠️ No se encontraron plantillas en: {plantillas_folder}. Se generará un único 3MF.")
            output_path = os.path.join(model_folder, f"{clean_name}_original.3mf")
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
                for root, _, files in os.walk(work_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, work_folder)
                        zipf.write(file_path, arcname)
            print(f"✅ Archivo {output_path} generado")
        else:
            print(f"✅ Procesando con {len(impresoras_disponibles)} plantillas de impresoras")
            generados = 0
            for impresora in impresoras_disponibles:
                plantilla_path = os.path.join(plantillas_folder, impresora)

                # Verificar que el modelo cabe en la cama de esta impresora
                if dims_modelo:
                    dims_cama = obtener_dimensiones_cama(plantilla_path, impresora)
                    if dims_cama and not modelo_cabe_en_cama(dims_modelo, dims_cama):
                        print(f"⏭️ Modelo "
                              f"({dims_modelo[0]:.1f}x{dims_modelo[1]:.1f}x{dims_modelo[2]:.1f} mm) "
                              f"NO cabe en cama de {impresora} "
                              f"({dims_cama[0]:.0f}x{dims_cama[1]:.0f}x{dims_cama[2]:.0f} mm "
                              f"- margen {MARGEN_SEGURIDAD_MM:.0f}mm). "
                              f"Se omite esta impresora.")
                        continue
                    if not dims_cama:
                        print(f"⚠️ No se pudo determinar la cama de {impresora}; "
                              f"se genera sin filtrar")

                # Copiar archivos de la plantilla a Metadata
                for file_name in ["custom_gcode_per_layer.xml", "project_settings.config"]:
                    src_file = os.path.join(plantilla_path, file_name)
                    dst_file = os.path.join(metadata_folder, file_name)
                    if os.path.exists(src_file):
                        shutil.copy(src_file, dst_file)

                output_path = os.path.join(model_folder, f"{clean_name}_{impresora}.3mf")
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
                    for root, _, files in os.walk(work_folder):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, work_folder)
                            zipf.write(file_path, arcname)
                print(f"✅ Archivo {output_path} generado para la impresora {impresora}")
                generados += 1

            if generados == 0:
                print("⚠️ Ningún perfil generado: el modelo no cabe en ninguna cama disponible")

        # Limpiar workspace temporal para evitar acumulación
        shutil.rmtree(work_folder, ignore_errors=True)

        return model_folder

    except Exception as e:
        print(f"❌ Error procesando 3MF '{model_name}': {e}")
        shutil.rmtree(work_folder, ignore_errors=True)
        return None


def procesar_imagen(imagen_path: str) -> str:
    """
    Procesa una imagen para usarla como portada del modelo.
    Recorta a cuadrado centrado y escala si es necesario.
    
    Args:
        imagen_path: Ruta a la imagen original
    
    Returns:
        Ruta a la imagen procesada
    """
    img = Image.open(imagen_path)
    w, h = img.size

    # 1. Recortar a cuadrado centrado
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img_cropped = img.crop((left, top, left + side, top + side))

    # 2. Escalar si es más pequeño que 400x400
    if side < 400:
        img_cropped = img_cropped.resize((400, 400), Image.LANCZOS)

    # 3. Guardar en archivo temporal (para no sobreescribir plate_1.png)
    temp_dir = tempfile.gettempdir()
    output_path = os.path.join(temp_dir, "plate_1_processed.png")
    img_cropped.save(output_path, format="PNG")

    return output_path


def descargar_y_procesar_3mf(login_result: LoginResult, model_name: str, download_url: str, 
                            download_folder: str = None) -> Optional[str]:
    """
    Descarga un archivo 3MF desde una URL y lo procesa.
    
    Args:
        login_result: Resultado del login con las credenciales
        model_name: Nombre del modelo
        download_url: URL de descarga del archivo 3MF
        download_folder: Carpeta donde descargar (por defecto: Downloads del usuario)
    
    Returns:
        Ruta a la carpeta del modelo procesado, o None si hay error
    """
    if download_folder is None:
        download_folder = os.getenv("DOWNLOAD_FOLDER", r"E:\descargas")
    
    try:
        print(f"⬇️ Descargando archivo 3MF: {model_name}")
        
        # Crear carpeta de descargas si no existe
        os.makedirs(download_folder, exist_ok=True)
        
        # Preparar headers con la autenticación
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Authorization': f'Bearer {login_result.token}' if login_result.token else '',
            'Cookie': f'accessToken={login_result.token}' if login_result.token else ''
        }
        
        # Realizar la descarga
        response = requests.get(download_url, headers=headers, stream=True)
        response.raise_for_status()

        # Generar nombre del archivo con nombre saneado
        clean_name = _sanear_nombre_modelo(model_name)
        filename = f"{clean_name.replace(' ', '_')}.3mf"
        file_path = os.path.join(download_folder, filename)

        # Obtener tamaño total
        total_size = int(response.headers.get('content-length', 0))

        # Guardar el archivo con barra de progreso
        with open(file_path, 'wb') as f:
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"Descargando {filename}", bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}') as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

        print(f"✅ Archivo descargado: {file_path}")
        
        # Procesar el archivo 3MF
        model_folder = procesar3MF(model_name, file_path)
        
        # Eliminar el archivo 3MF original descargado
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"🗑️ Archivo 3MF original eliminado: {file_path}")
        
        return model_folder
        
    except Exception as e:
        print(f"❌ Error descargando y procesando 3MF '{model_name}': {e}")
        return None


def get_aliyun_credentials(
    login_result: LoginResult,
    timeout: int = 15
) -> Optional[AliyunCredentials]:
    """
    Obtiene las credenciales STS de Alibaba Cloud para uploads OSS.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        timeout: Timeout en segundos
    
    Returns:
        AliyunCredentials con las credenciales STS o None si falla
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id para obtener credenciales OSS.")
    
    # Configurar headers específicos para la API de credenciales
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "__cxy_token_": login_result.model_token,
        "__cxy_uid_": str(login_result.model_user_id),
        "__cxy_brand_": "creality",
        "__cxy_os_lang_": "0",
        "__cxy_app_ver_": "6.0.0",
        "__cxy_app_ch_": "Chrome 143.0.0.0",
        "__cxy_os_ver_": "Windows 10",
        "__cxy_timezone_": "3600",
        "__cxy_app_id_": "creality_model",
        "__cxy_platform_": "2",
        "Origin": CLOUD_BASE_URL,
        "Referer": f"{CLOUD_BASE_URL}/es/",
    }
    
    try:
        # Realizar la petición para obtener credenciales
        response = login_result.session.post(
            f"{CLOUD_BASE_URL}/api/cxy/account/v2/getAliyunInfo",
            json={},  # Body vacío según el tráfico HTTP
            headers=headers,
            timeout=timeout
        )
        response.raise_for_status()
        
        # Procesar la respuesta
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Error obteniendo credenciales OSS: {data.get('msg', 'Error desconocido')}")
        
        aliyun_info = data.get("result", {}).get("aliyunInfo", {})
        if not aliyun_info:
            raise RuntimeError("No se encontraron credenciales de Alibaba Cloud en la respuesta")
        
        credentials = AliyunCredentials.from_dict(aliyun_info)
        
        print(f"✅ Credenciales OSS obtenidas")
        print(f"   🔑 AccessKeyId: {credentials.access_key_id}")
        print(f"   ⏰ Expira en: {credentials.life_time} segundos")
        
        return credentials
        
    except Exception as e:
        print(f"❌ Error obteniendo credenciales de Alibaba Cloud: {e}")
        return None


def generar_nombre_archivo_unico() -> str:
    """
    Genera un nombre único de 32 caracteres hexadecimales como usa Creality.
    
    Returns:
        Nombre único en formato hexadecimal
    """
    return uuid.uuid4().hex


def calcular_md5_archivo(file_path: str) -> tuple[str, str]:
    """
    Calcula el hash MD5 de un archivo.
    
    Args:
        file_path: Ruta al archivo
    
    Returns:
        Tupla (md5_hex, md5_base64) con el hash en formato hexadecimal y base64
    """
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    
    md5_hex = hasher.hexdigest().upper()
    md5_base64 = base64.b64encode(hasher.digest()).decode('utf-8')
    
    return md5_hex, md5_base64


def subir_imagen_oss(
    login_result: LoginResult,
    imagen_path: str,
    credentials: AliyunCredentials,
    timeout: int = 30
) -> Optional[str]:
    """
    Sube una imagen a Alibaba Cloud OSS usando PUT directo.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        imagen_path: Ruta a la imagen a subir
        sts_token: Token STS para autenticación OSS
        timeout: Timeout en segundos
    
    Returns:
        URL CDN de la imagen subida o None si falla
    """
    
    if not os.path.exists(imagen_path):
        print(f"❌ Archivo de imagen no encontrado: {imagen_path}")
        return None
    
    try:
        # Generar nombre único para la imagen
        filename_uuid = generar_nombre_archivo_unico()
        
        # Determinar extensión
        file_extension = os.path.splitext(imagen_path)[1].lower()
        if file_extension in ['.png', '.jpg', '.jpeg']:
            # Normalizar a .jpeg para el CDN
            cdn_extension = '.jpeg'
        else:
            cdn_extension = file_extension
        
        # URLs de destino
        oss_key = f"crealityCloud/upload/{filename_uuid}{cdn_extension}"
        oss_url = f"{OSS_IMAGE_BASE_URL}/{oss_key}"
        cdn_url = f"{CDN_IMAGE_BASE_URL}/{filename_uuid}{cdn_extension}"
        
        print(f"🖼️ Subiendo imagen: {os.path.basename(imagen_path)}")
        print(f"   📍 Destino: {oss_key}")
        
        # Leer archivo
        with open(imagen_path, 'rb') as f:
            file_data = f.read()
        
        # Configurar headers OSS
        from datetime import datetime as dt
        gmt_time = dt.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        
        headers = {
            'Content-Type': 'image/jpeg',
            'Content-Length': str(len(file_data)),
            'X-Oss-Date': gmt_time,
            'X-Oss-Security-Token': credentials.session_token,
            'X-Oss-User-Agent': 'aliyun-sdk-js/6.17.1 Chrome 143.0.0.0 on Windows 10 64-bit',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Origin': CLOUD_BASE_URL,
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Accept': '*/*'
        }
        
        # Calcular signature OSS
        signature = calcular_signature_oss('PUT', f'/pic2-creality/{oss_key}', headers, credentials.secret_access_key)
        headers['Authorization'] = f'OSS {credentials.access_key_id}:{signature}'
        
        # Realizar upload PUT
        response = requests.put(
            oss_url,
            data=file_data,
            headers=headers,
            timeout=timeout
        )
        
        if response.status_code == 200:
            print(f"✅ Imagen subida exitosamente")
            print(f"   🔗 URL CDN: {cdn_url}")
            return cdn_url
        else:
            print(f"❌ Error subiendo imagen: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error subiendo imagen '{os.path.basename(imagen_path)}': {e}")
        return None


def calcular_signature_oss(
    method: str, 
    resource: str, 
    headers: dict, 
    access_key_secret: str
) -> str:
    """
    Calcula la signature OSS para autenticación usando HMAC-SHA1.
    
    Args:
        method: Método HTTP (GET, PUT, POST)
        resource: Recurso OSS (ej: /crealityCloud/upload/xxx.jpeg)
        headers: Headers de la petición HTTP
        access_key_secret: Secret access key de las credenciales STS
    
    Returns:
        Signature calculada en base64
    """
    
    # 1. Extraer headers OSS específicos y ordenarlos
    oss_headers = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower.startswith('x-oss-'):
            oss_headers[key_lower] = value
    
    # 2. Construir string de headers OSS
    oss_headers_str = ""
    if oss_headers:
        sorted_headers = sorted(oss_headers.items())
        oss_headers_str = '\n'.join([f"{k}:{v}" for k, v in sorted_headers])
        if oss_headers_str:
            oss_headers_str += '\n'
    
    # 3. Obtener valores específicos
    content_md5 = headers.get('Content-MD5', '')
    content_type = headers.get('Content-Type', '')
    
    # Si x-oss-date está presente, usar su valor para Date en StringToSign
    if 'x-oss-date' in oss_headers:
        date = oss_headers['x-oss-date']
    else:
        date = headers.get('Date', '')
    
    # 4. Construir string to sign
    string_to_sign = f"{method}\n{content_md5}\n{content_type}\n{date}\n{oss_headers_str}{resource}"
    
    # 5. Calcular HMAC-SHA1 signature
    signature = hmac.new(
        access_key_secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha1
    ).digest()
    
    # 6. Codificar en base64
    return base64.b64encode(signature).decode('utf-8')


def subir_archivo_3mf_oss(
    login_result: LoginResult,
    archivo_3mf_path: str,
    credentials: AliyunCredentials,
    timeout: int = 120
) -> Optional[str]:
    """
    Sube un archivo 3MF a Alibaba Cloud OSS usando PUT directo.

    Args:
        login_result: Resultado del login con tokens y sesión
        archivo_3mf_path: Ruta al archivo 3MF a subir
        credentials: Credenciales de Alibaba Cloud
        timeout: Timeout en segundos

    Returns:
        Key del archivo subido (ej: file3mf/xxx.3mf) o None si falla
    """

    if not os.path.exists(archivo_3mf_path):
        print(f"❌ Archivo 3MF no encontrado: {archivo_3mf_path}")
        return None

    try:
        # Generar nombre único para el archivo
        filename_uuid = generar_nombre_archivo_unico()
        oss_key = f"file3mf/{filename_uuid}.3mf"
        oss_url = f"{OSS_3MF_BASE_URL}/{oss_key}"

        print(f"📤 Subiendo archivo 3MF: {os.path.basename(archivo_3mf_path)}")
        print(f"   📍 Destino: {oss_key}")

        # Leer archivo
        with open(archivo_3mf_path, 'rb') as f:
            file_data = f.read()

        # Configurar headers OSS (igual a imagen pero con Content-Type de 3MF)
        from datetime import datetime as dt
        gmt_time = dt.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')

        headers = {
            'Content-Type': 'model/3mf',
            'Content-Length': str(len(file_data)),
            'X-Oss-Date': gmt_time,
            'X-Oss-Security-Token': credentials.session_token,
            'X-Oss-User-Agent': 'aliyun-sdk-js/6.17.1 Chrome 143.0.0.0 on Windows 10 64-bit',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Origin': CLOUD_BASE_URL,
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Accept': '*/*'
        }

        # Calcular signature OSS
        signature = calcular_signature_oss('PUT', f'/internal-creality-usa/{oss_key}', headers, credentials.secret_access_key)
        headers['Authorization'] = f'OSS {credentials.access_key_id}:{signature}'

        # Realizar upload PUT
        response = requests.put(
            oss_url,
            data=file_data,
            headers=headers,
            timeout=timeout
        )

        if response.status_code == 200:
            print(f"✅ Archivo 3MF subido exitosamente")
            print(f"   📁 Key: {oss_key}")
            return oss_key
        else:
            print(f"❌ Error subiendo archivo 3MF: {response.status_code} - {response.text[:200]}")
            return None

    except Exception as e:
        print(f"❌ Error subiendo archivo 3MF: {e}")
        return None


def subir_archivo_fisico(
    login_result: LoginResult,
    file_path: str,
    file_type: str = "3mf",
    credentials: AliyunCredentials = None,
    timeout: int = 120
) -> Optional[str]:
    """
    Sube un archivo físico al servidor OSS y retorna el filekey/URL.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        file_path: Ruta al archivo a subir
        file_type: Tipo de archivo ('3mf', 'image')
        credentials: Credenciales de Alibaba Cloud (se obtienen automáticamente si no se proporcionan)
        timeout: Timeout en segundos
    
    Returns:
        El filekey/URL del archivo subido o None si falla
    """
    
    if not os.path.exists(file_path):
        print(f"❌ Archivo no encontrado: {file_path}")
        return None
    
    # Obtener credenciales si no se proporcionan
    if not credentials:
        print("🔑 Obteniendo credenciales OSS de Alibaba Cloud...")
        credentials = get_aliyun_credentials(login_result, timeout)
        if not credentials:
            print("❌ No se pudieron obtener las credenciales OSS")
            return None
    
    # Verificar si las credenciales han expirado
    if credentials.is_expired():
        print("⚠️ Las credenciales OSS han expirado, obteniendo nuevas...")
        credentials = get_aliyun_credentials(login_result, timeout)
        if not credentials:
            print("❌ No se pudieron renovar las credenciales OSS")
            return None
    
    if file_type == "3mf":
        return subir_archivo_3mf_oss(login_result, file_path, credentials, timeout)
    elif file_type == "image":
        return subir_imagen_oss(login_result, file_path, credentials, timeout)
    
    print(f"❌ Tipo de archivo no soportado: {file_type}")
    return None


def crear_plate_list(
    imagen_portada_path: str = None,
    cover_url: str = ""
) -> List[Dict[str, Any]]:
    """
    Crea la lista de plates para el payload de subida.
    
    Args:
        imagen_portada_path: Ruta a la imagen de portada
        cover_url: URL de la imagen subida
    
    Returns:
        Lista de plates para el payload
    """
    
    plates = []
    
    # Plate principal
    plate = {
        "name": "plate1",
        "index": 1,
        "thumbnail": cover_url if cover_url else "",
        "hasGcode": False
    }
    plates.append(plate)
    
    return plates


def subir_archivo_3mf(
    login_result: LoginResult,
    archivo_3mf_path: str,
    model_name: str,
    model_group_id: str,
    imagen_portada_path: str = None,
    timeout: int = 60
) -> bool:
    """
    Sube un archivo 3MF procesado a Creality Cloud.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        archivo_3mf_path: Ruta al archivo 3MF a subir
        model_name: Nombre del modelo
        model_group_id: ID del grupo de modelos original
        imagen_portada_path: Ruta a la imagen de portada (opcional)
        timeout: Timeout en segundos
    
    Returns:
        True si la subida fue exitosa, False en caso contrario
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id para subir archivos.")
    
    if not os.path.exists(archivo_3mf_path):
        print(f"❌ Archivo 3MF no encontrado: {archivo_3mf_path}")
        return False
    
    try:
        # Obtener información del archivo
        file_size = os.path.getsize(archivo_3mf_path)
        file_name = os.path.basename(archivo_3mf_path)
        
        # Extraer nombre de impresora del nombre del archivo
        if "_" in file_name:
            printer_code = file_name.split("_")[-1].replace(".3mf", "")
            # Mapear códigos de impresora a nombres oficiales
            printer_map = {
                "K1": "K1",
                "K1C": "K1C",
                "K1Max": "K1 Max",
                "K1SE": "K1 SE",
                "K2": "K2",
                "K2Pro": "K2 Pro",
                "E3V3": "Ender-3 V3",
                "E3V3KE": "Ender-3 V3 KE",
                "E3V3Plus": "Ender-3 V3 Plus",
                "E3V3SE": "Ender-3 V3 SE",
                "E5Max": "CR-M4",
                "Hi": "CR-200B",
            }
            printer_name = printer_map.get(printer_code, printer_code)
        else:
            printer_name = "Unknown"
        
        print(f"📤 Subiendo archivo 3MF: {file_name}")
        print(f"   📏 Tamaño: {file_size:,} bytes")
        print(f"   🖨️ Impresora: {printer_name}")
        
        # Configurar headers para la subida
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "__cxy_token_": login_result.model_token,
            "__cxy_uid_": str(login_result.model_user_id),
            "__cxy_brand_": "creality",
            "__cxy_os_lang_": "0",  # Español
            "__cxy_app_ver_": "6.0.0",
            "__cxy_app_ch_": "Chrome 143.0.0.0",
            "__cxy_os_ver_": "Windows 10",
            "__cxy_timezone_": "3600",
            "__cxy_app_id_": "creality_model",
            "__cxy_platform_": "2",
            "Origin": CLOUD_BASE_URL,
            "Referer": f"{CLOUD_BASE_URL}/es/",
        }
        
        # FLUJO SEGÚN TRÁFICO HTTP:
        # 1. Primero se sube el archivo 3MF a OSS (multipart upload)
        # 2. Después se sube la imagen a OSS (PUT directo)  
        # 3. Finalmente se registra el modelo con upload3mf
        # 4. Se obtienen los detalles del modelo actualizado
        
        print("   📤 Subiendo archivo 3MF al servidor...")
        filekey = subir_archivo_fisico(login_result, archivo_3mf_path, "3mf", None, timeout)
        
        if not filekey:
            print("❌ No se pudo subir el archivo 3MF")
            return False
        
        print(f"   ✅ Archivo 3MF subido. FileKey: {filekey}")
        
        # 2. Subir imagen de portada si se proporciona
        cover_url = ""
        thumbnail_url = ""
        
        print(f"   📋 Preparando subida del perfil:")
        print(f"      🖨️ Impresora: {printer_name}")
        print(f"      📁 FileKey: {filekey}")
        print(f"      📏 Tamaño: {file_size:,} bytes")
        print(f"      🎯 Grupo modelo: {model_group_id}")
        
        print(f"   📋 Preparando subida del perfil:")
        print(f"      🖨️ Impresora: {printer_name}")
        print(f"      📁 FileKey: {filekey}")
        print(f"      📏 Tamaño: {file_size:,} bytes")
        print(f"      🎯 Grupo modelo: {model_group_id}")
        
        if imagen_portada_path and os.path.exists(imagen_portada_path):
            print("   🖼️ Subiendo imagen de portada a OSS...")
            cover_url = subir_archivo_fisico(login_result, imagen_portada_path, "image", None, timeout)
            
            if cover_url:
                thumbnail_url = cover_url  # Usar la misma URL para thumbnail
                print(f"   ✅ Imagen de portada subida: {os.path.basename(imagen_portada_path)}")
            else:
                print("   ⚠️ No se pudo subir la imagen de portada")
        
        # Preparar el payload para la subida (formato exacto del tráfico HTTP)
        payload = {
            "filekey": filekey,
            "size": file_size,
            "name": file_name,
            "thumbnail": thumbnail_url,
            "printerName": printer_name,
            "layerHeight": "0.2",
            "sparseInfillDensity": "15%",
            "nozzleDiameter": ["0.4"],
            "currBedType": "High Temp Plate",
            "plateList": crear_plate_list(imagen_portada_path, cover_url),
            "secondName": "0.2mm layer, 2 walls, 15% infill",
            "wallLoops": "2",
            "modelGroupId": model_group_id,
            "covers": [
                {
                    "type": 2,
                    "width": 400,
                    "height": 400,
                    "url": cover_url
                }
            ] if cover_url else [],
            "desc": ""
        }
        
        # 3. Registrar el modelo en Creality Cloud (upload3mf)
        print("   📝 Registrando modelo en Creality Cloud...")
        
        response = login_result.session.post(
            f"{CLOUD_BASE_URL}/api/cxy/v3/model/upload3mf",
            json=payload,
            headers=headers,
            timeout=timeout
        )
        response.raise_for_status()
        
        # Procesar la respuesta
        data = response.json()
        if data.get("code") != 0:
            msg = data.get('msg', 'Error desconocido')
            print(f"❌ Error en la subida: {msg}")
            if _es_limite_diario(msg):
                raise DailyLimitReached(msg)
            return False

        # Procesar información de la respuesta
        upload_info = procesar_respuesta_upload3mf(data)
        
        print(f"✅ Archivo 3MF subido exitosamente: {file_name}")
        print(f"   🆔 ID del archivo: {upload_info['id']}")
        print(f"   📄 Nombre del grupo: {upload_info['model_group_name']}")
        print(f"   🖨️ Impresora: {upload_info['printer_name']}")
        print(f"   🔐 Puede imprimir: {'Sí' if upload_info['is_can_print'] else 'No'}")
        
        # Obtener detalles del modelo después de la subida (como en el tráfico HTTP)
        print("   📋 Obteniendo detalles del modelo...")
        model_details = get_model_group_detail(login_result, model_group_id)
        if model_details:
            print(f"   ✅ Detalles del modelo actualizados")
        else:
            print(f"   ⚠️ No se pudieron obtener los detalles del modelo")
        
        return True

    except DailyLimitReached:
        raise
    except Exception as e:
        print(f"❌ Error subiendo archivo 3MF '{file_name}': {e}")
        return False


def subir_todos_los_perfiles(
    login_result: LoginResult,
    model_folder: str,
    model_group_id: str,
    timeout: int = 60
) -> tuple[int, int]:
    """
    Sube todos los archivos 3MF de una carpeta de modelo procesado.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        model_folder: Carpeta con los archivos 3MF procesados
        model_group_id: ID del grupo de modelos original
        timeout: Timeout en segundos por archivo
    
    Returns:
        Tupla (exitosos, fallidos) con el conteo de archivos
    """
    
    if not os.path.exists(model_folder):
        print(f"❌ Carpeta de modelo no encontrada: {model_folder}")
        return 0, 0
    
    # Buscar archivos 3MF en la carpeta
    archivos_3mf = [f for f in os.listdir(model_folder) if f.endswith('.3mf')]
    
    if not archivos_3mf:
        print(f"⚠️ No se encontraron archivos 3MF en: {model_folder}")
        return 0, 0
    
    # Buscar imagen de portada
    imagen_portada = None
    plate_file = os.path.join(model_folder, "plate_1.png")
    if os.path.exists(plate_file):
        imagen_portada = plate_file
    
    print(f"📤 Iniciando subida de {len(archivos_3mf)} archivos 3MF...")
    
    exitosos = 0
    fallidos = 0
    
    for archivo_3mf in archivos_3mf:
        archivo_path = os.path.join(model_folder, archivo_3mf)
        
        # Extraer nombre del modelo del nombre del archivo
        model_name = archivo_3mf.replace('.3mf', '')
        
        try:
            exito = subir_archivo_3mf(
                login_result=login_result,
                archivo_3mf_path=archivo_path,
                model_name=model_name,
                model_group_id=model_group_id,
                imagen_portada_path=imagen_portada,
                timeout=timeout
            )
            
            if exito:
                exitosos += 1
            else:
                fallidos += 1
                
            # Pequeña pausa entre subidas para no saturar el servidor
            time.sleep(2)

        except DailyLimitReached:
            raise
        except Exception as e:
            print(f"❌ Error subiendo {archivo_3mf}: {e}")
            fallidos += 1
    
    print(f"📊 Resumen de subida:")
    print(f"   ✅ Exitosos: {exitosos}")
    print(f"   ❌ Fallidos: {fallidos}")
    
    # Limpiar carpeta de modelo si se subieron todos exitosamente
    if exitosos > 0 and fallidos == 0:
        try:
            shutil.rmtree(model_folder)
            print(f"🗑️ Carpeta '{model_folder}' eliminada después de subir los archivos")
        except Exception as e:
            print(f"⚠️ No se pudo eliminar la carpeta '{model_folder}': {e}")
    
    return exitosos, fallidos


def procesar_respuesta_upload3mf(response_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Procesa la respuesta del endpoint upload3mf y extrae información útil.
    
    Args:
        response_data: Datos de la respuesta JSON del upload3mf
    
    Returns:
        Diccionario con información procesada
    """
    
    result = response_data.get("result", {})
    
    info = {
        "id": result.get("id", ""),
        "model_group_id": result.get("modelGroupId", ""),
        "model_group_name": result.get("modelGroupName", ""),
        "size": result.get("size", 0),
        "filekey": result.get("filekey", ""),
        "name": result.get("name", ""),
        "printer_name": result.get("printerName", ""),
        "thumbnail": result.get("thumbnail", ""),
        "is_can_print": result.get("isCanPrint", False),
        "is_auth": result.get("isAuth", False),
        "user_id": result.get("userId", 0)
    }
    
    return info


def get_model_group_detail(
    login_result: LoginResult,
    model_group_id: str,
    timeout: int = 15
) -> Optional[Dict[str, Any]]:
    """
    Obtiene los detalles de un grupo de modelos después de la subida.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        model_group_id: ID del grupo de modelos
        timeout: Timeout en segundos
    
    Returns:
        Diccionario con los detalles del modelo o None si falla
    """
    
    if not login_result.model_token or not login_result.model_user_id:
        raise RuntimeError("Se requiere model_token y model_user_id para obtener detalles del modelo.")
    
    # Configurar headers específicos para la API de detalles
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "__cxy_token_": login_result.model_token,
        "__cxy_uid_": str(login_result.model_user_id),
        "__cxy_brand_": "creality",
        "__cxy_os_lang_": "0",
        "__cxy_app_ver_": "6.0.0",
        "__cxy_app_ch_": "Chrome 143.0.0.0",
        "__cxy_os_ver_": "Windows 10",
        "__cxy_timezone_": "3600",
        "__cxy_app_id_": "creality_model",
        "__cxy_platform_": "2",
        "Origin": CLOUD_BASE_URL,
        "Referer": f"{CLOUD_BASE_URL}/es/",
    }
    
    # Payload con el ID del modelo
    payload = {
        "id": model_group_id
    }
    
    try:
        # Realizar la petición
        response = login_result.session.post(
            f"{CLOUD_BASE_URL}/api/cxy/v3/model/modelGroupDetail",
            json=payload,
            headers=headers,
            timeout=timeout
        )
        response.raise_for_status()
        
        # Procesar la respuesta
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Error obteniendo detalles del modelo: {data.get('msg', 'Error desconocido')}")
        
        return data.get("result")
        
    except Exception as e:
        print(f"❌ Error obteniendo detalles del modelo '{model_group_id}': {e}")
        return None


def proceso_completo_con_subida(
    login_result: LoginResult,
    model_name: str,
    db: ModelDatabase,
    subir_archivos: bool = False,
    timeout: int = 30
) -> Optional[tuple[str, int, int]]:
    """
    Proceso completo: descarga, procesa y opcionalmente sube archivos 3MF.
    
    Args:
        login_result: Resultado del login con tokens y sesión
        model_name: Nombre del modelo en la base de datos
        db: Base de datos de modelos
        subir_archivos: Si True, sube los archivos procesados
        timeout: Timeout en segundos
    
    Returns:
        Tupla (carpeta_modelo, exitosos, fallidos) o None si falla
    """
    
    # 1. Procesar modelo completo (descarga y procesamiento)
    result = process_model_complete(login_result, model_name, db, timeout)
    
    if not result:
        return None
    
    model_3mf_info, download_url = result
    
    # 2. Descargar y procesar archivo 3MF
    model_folder = descargar_y_procesar_3mf(login_result, model_name, download_url)
    
    if not model_folder:
        return None
    
    # 3. Subir archivos si está habilitado
    if subir_archivos:
        print(f"\n🚀 Iniciando subida de archivos procesados...")
        
        # Obtener el ID del modelo original
        model_entry = db.get_model(model_name)
        model_group_id = model_entry.model_id if model_entry else ""
        
        exitosos, fallidos = subir_todos_los_perfiles(
            login_result=login_result,
            model_folder=model_folder,
            model_group_id=model_group_id,
            timeout=timeout
        )
        
        return model_folder, exitosos, fallidos
    
    return model_folder, 0, 0