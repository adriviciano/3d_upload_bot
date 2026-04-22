#!/usr/bin/env python3
"""Servidor web para monitorear el bot de Creality Cloud"""

from flask import Flask, render_template, jsonify
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

app = Flask(__name__, static_folder='web/static', template_folder='web')

STATUS_FILE = 'bot_status.json'

def get_default_status():
    return {
        "estado": "Inactivo",
        "modelo_actual": "",
        "modelos_procesados": 0,
        "archivos_subidos": 0,
        "errores": 0,
        "pagina": 0,
        "timestamp": ""
    }

def get_ultimos_errores(limit=20):
    """Lee últimos N errores del archivo log"""
    try:
        if not os.path.exists('errors.log'):
            return []
        with open('errors.log', 'r', encoding='utf-8') as f:
            lineas = f.readlines()
        return [linea.strip() for linea in lineas[-limit:] if linea.strip()]
    except:
        return []

def is_bot_running():
    """Verifica si el bot está corriendo verificando su PID"""
    try:
        if not os.path.exists('bot.pid'):
            return False
        with open('bot.pid', 'r') as f:
            pid = int(f.read().strip())
        # Verificar si proceso existe (sin matar)
        import signal
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return False
    except:
        return False

def load_status():
    """Carga el estado del bot desde archivo"""
    if not os.path.exists(STATUS_FILE):
        return get_default_status()
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return get_default_status()

@app.route('/')
def index():
    """Sirve página principal"""
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    """API que retorna estado actual del bot"""
    status = load_status()
    status['ultimos_errores'] = get_ultimos_errores(20)
    status['is_running'] = is_bot_running()
    return jsonify(status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
