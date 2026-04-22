"""Módulo para actualizar estado del bot"""

import json
from datetime import datetime
from pathlib import Path

STATUS_FILE = 'bot_status.json'

class BotStatus:
    def __init__(self):
        self.estado = "Iniciando"
        self.modelo_actual = ""
        self.modelos_procesados = 0
        self.archivos_subidos = 0
        self.errores = 0
        self.ultimos_errores = []
        self.pagina = 0

    def actualizar(self, **kwargs):
        """Actualiza el estado y guarda a archivo"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._guardar()

    def agregar_error(self, error):
        """Agrega un error a la lista (máximo 20 últimos)"""
        self.errores += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        error_msg = f"[{timestamp}] {str(error)[:120]}"
        self.ultimos_errores.insert(0, error_msg)
        self.ultimos_errores = self.ultimos_errores[:20]
        self._guardar()
        print(f"   📋 Error registrado: {error_msg}")

    def _guardar(self):
        """Guarda estado a JSON"""
        data = {
            "estado": self.estado,
            "modelo_actual": self.modelo_actual,
            "modelos_procesados": self.modelos_procesados,
            "archivos_subidos": self.archivos_subidos,
            "errores": self.errores,
            "ultimos_errores": self.ultimos_errores,
            "pagina": self.pagina,
            "timestamp": datetime.now().isoformat()
        }
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# Instancia global
bot_status = BotStatus()
