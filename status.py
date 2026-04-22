"""Módulo para actualizar estado del bot"""

import json
from datetime import datetime
from pathlib import Path

STATUS_FILE = 'bot_status.json'
ERROR_LOG = 'errors.log'

class BotStatus:
    def __init__(self):
        self.estado = "Iniciando"
        self.modelo_actual = ""
        self.modelos_procesados = 0
        self.archivos_subidos = 0
        self.errores = 0
        self.pagina = 0

    def actualizar(self, **kwargs):
        """Actualiza el estado y guarda a archivo"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._guardar()

    def agregar_error(self, error):
        """Agrega error a archivo log"""
        self.errores += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_msg = f"[{timestamp}] {str(error)[:200]}"

        # Escribir a archivo log
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
            "timestamp": datetime.now().isoformat()
        }
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# Instancia global
bot_status = BotStatus()
