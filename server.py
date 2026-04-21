#!/usr/bin/env python3
"""Servidor web para monitorear el bot de Creality Cloud"""

from flask import Flask, render_template, jsonify
import json
import os
from pathlib import Path

app = Flask(__name__, static_folder='web/static', template_folder='web')

STATUS_FILE = 'bot_status.json'

def get_default_status():
    return {
        "estado": "Inactivo",
        "modelo_actual": "",
        "modelos_procesados": 0,
        "archivos_subidos": 0,
        "errores": 0,
        "ultimos_errores": [],
        "pagina": 0,
        "timestamp": ""
    }

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
    return jsonify(load_status())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
