"""Módulo para actualizar estado del bot"""

import json
from datetime import datetime
from pathlib import Path

STATUS_FILE = 'bot_status.json'
ERROR_LOG = 'errors.log'
CONFIG_FILE = 'bot_config.json'

class BotStatus:
    def __init__(self):
        self.estado = "Iniciando"
        self.modelo_actual = ""
        self.modelos_procesados = 0
        self.archivos_subidos = 0
        self.errores = 0
        self.pagina = 0
        self.pausa_inicio = None
        self.pausa_duracion = 0

    def actualizar(self, **kwargs):
        """Actualiza el estado y guarda a archivo"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._guardar()

    def iniciar_pausa(self, duracion_segundos):
        """Marca inicio de pausa"""
        self.pausa_inicio = datetime.now().isoformat()
        self.pausa_duracion = duracion_segundos
        self._guardar()

    def agregar_error(self, error):
        """Agrega error a archivo log"""
        self.errores += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_msg = f"[{timestamp}] {str(error)[:200]}"

        with open(ERROR_LOG, 'a', encoding='utf-8') as f:
            f.write(error_msg + '\n')

        self._guardar()

    def _guardar(self):
        """Guarda estado a JSON"""
        data = {
            "estado": self.estado,
            "modelo_actual": self.modelo_actual,
            "modelos_procesados": self.modelos_procesados,
            "archivos_subidos": self.archivos_subidos,
            "errores": self.errores,
            "pagina": self.pagina,
            "pausa_inicio": self.pausa_inicio,
            "pausa_duracion": self.pausa_duracion,
            "timestamp": datetime.now().isoformat()
        }
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def get_delay_config():
    """Lee delay configurado desde archivo"""
    if not Path(CONFIG_FILE).exists():
        return 240
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('delay_entre_descargas', 240)
    except:
        return 240

def set_delay_config(delay_segundos):
    """Guarda delay configurado"""
    config = {'delay_entre_descargas': int(delay_segundos)}
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

# Instancia global
bot_status = BotStatus()
