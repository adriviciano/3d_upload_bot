#!/usr/bin/env python3
"""Servidor web para monitorear el bot de Creality Cloud"""

from flask import Flask, render_template, jsonify, request
import json
import os
import signal
from pathlib import Path
from datetime import datetime, timedelta
from status import get_delay_config, set_delay_config

app = Flask(__name__, static_folder='web/static', template_folder='web')

STATUS_FILE = 'bot_status.json'
PID_FILE = 'bot.pid'

def get_default_status():
    return {
        "estado": "Inactivo",
        "modelo_actual": "",
        "modelos_procesados": 0,
        "archivos_subidos": 0,
        "errores": 0,
        "pagina": 0,
        "pausa_inicio": None,
        "pausa_duracion": 0,
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
        if not os.path.exists(PID_FILE):
            return False
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
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
            status = json.load(f)
        # Calcular tiempo restante de pausa
        if status.get('pausa_inicio') and status.get('pausa_duracion'):
            try:
                inicio = datetime.fromisoformat(status['pausa_inicio'])
                duracion = status['pausa_duracion']
                ahora = datetime.now()
                elapsed = (ahora - inicio).total_seconds()
                restante = max(0, duracion - elapsed)
                status['pausa_restante'] = int(restante)
            except:
                status['pausa_restante'] = 0
        else:
            status['pausa_restante'] = 0
        return status
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
    status['delay_configurado'] = get_delay_config()
    return jsonify(status)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """GET: obtener config | POST: cambiar delay"""
    if request.method == 'POST':
        data = request.get_json()
        delay = data.get('delay_entre_descargas')
        if delay and isinstance(delay, int) and delay > 0:
            set_delay_config(delay)
            return jsonify({'success': True, 'delay': delay})
        return jsonify({'success': False, 'error': 'delay inválido'}), 400

    delay = get_delay_config()
    return jsonify({'delay_entre_descargas': delay})

@app.route('/api/control/stop', methods=['POST'])
def control_stop():
    """Detiene el bot"""
    try:
        if not os.path.exists(PID_FILE):
            return jsonify({'success': False, 'error': 'Bot no está ejecutándose'}), 400

        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        os.kill(pid, signal.SIGTERM)
        return jsonify({'success': True, 'message': 'Bot detenido'})
    except ProcessLookupError:
        return jsonify({'success': False, 'error': 'Proceso no encontrado'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/control/start', methods=['POST'])
def control_start():
    """Inicia el bot"""
    if is_bot_running():
        return jsonify({'success': False, 'error': 'Bot ya está ejecutándose'}), 400

    import subprocess
    try:
        subprocess.Popen(
            ['python', 'ejecutar_bot.py'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return jsonify({'success': True, 'message': 'Bot iniciado'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
