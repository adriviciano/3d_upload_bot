// Actualizar estado cada 5 segundos (3 para pausa si está en pausa)
let updateInterval = setInterval(actualizarEstado, 5000);

// Actualizar al cargar
actualizarEstado();
inicializarControles();

async function actualizarEstado() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Actualizar stats
        document.getElementById('procesados').textContent = data.modelos_procesados;
        document.getElementById('subidos').textContent = data.archivos_subidos;
        document.getElementById('errores').textContent = data.errores;
        document.getElementById('pagina').textContent = data.pagina;

        // Actualizar estado
        const estadoEl = document.getElementById('estado');
        const indicador = document.getElementById('status-indicator');

        estadoEl.textContent = data.estado;

        if (data.estado.includes('Procesando')) {
            indicador.className = 'status-indicator processing';
        } else if (data.estado.includes('Activo')) {
            indicador.className = 'status-indicator active';
        } else {
            indicador.className = 'status-indicator';
        }

        // Actualizar running status
        const runningIndicator = document.getElementById('running-indicator');
        const runningText = document.getElementById('running-text');
        if (data.is_running) {
            runningIndicator.className = 'running-indicator running';
            runningText.textContent = 'Estado: Bot en ejecución ✓';
        } else {
            runningIndicator.className = 'running-indicator';
            runningText.textContent = 'Estado: Bot detenido';
        }

        // Actualizar modelo actual
        const modeloEl = document.getElementById('modelo-actual');
        if (data.modelo_actual) {
            modeloEl.textContent = `📦 ${data.modelo_actual}`;
        } else {
            modeloEl.textContent = 'Esperando información...';
        }

        // Actualizar información de pausa
        const pauseInfo = document.getElementById('pause-info');
        if (data.pausa_inicio && data.pausa_restante > 0) {
            pauseInfo.style.display = 'block';
            document.getElementById('pausa-restante').textContent = data.pausa_restante;
            // Actualizar más frecuente durante pausa
            clearInterval(updateInterval);
            updateInterval = setInterval(actualizarEstado, 1000);
        } else {
            pauseInfo.style.display = 'none';
            // Restaurar intervalo normal
            clearInterval(updateInterval);
            updateInterval = setInterval(actualizarEstado, 5000);
        }

        // Actualizar logs de errores
        const logsEl = document.getElementById('logs-container');
        if (data.ultimos_errores && data.ultimos_errores.length > 0) {
            logsEl.innerHTML = data.ultimos_errores
                .map(error => `<div class="log-item">${error}</div>`)
                .join('');
        } else {
            logsEl.innerHTML = '<p class="no-errors">Sin errores registrados</p>';
        }

        // Actualizar delay mostrado
        if (data.delay_configurado) {
            document.getElementById('delay-actual').textContent = data.delay_configurado;
            document.getElementById('delay-input').value = data.delay_configurado;
        }

        // Habilitar/deshabilitar botones según estado
        const startBtn = document.getElementById('start-btn');
        const stopBtn = document.getElementById('stop-btn');
        if (data.is_running) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
        }

        // Actualizar timestamp
        const ahora = new Date();
        const timestamp = ahora.toLocaleTimeString('es-ES');
        document.getElementById('timestamp').textContent = `Última actualización: ${timestamp}`;

    } catch (error) {
        console.error('Error actualizando estado:', error);
    }
}

function inicializarControles() {
    // Botón de actualizar delay
    document.getElementById('delay-btn').addEventListener('click', async () => {
        const delay = parseInt(document.getElementById('delay-input').value);
        if (!delay || delay < 1) {
            alert('Ingresa un valor válido (mayor a 0)');
            return;
        }

        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delay_entre_descargas: delay })
            });

            if (response.ok) {
                alert(`Delay actualizado a ${delay} segundos`);
                actualizarEstado();
            } else {
                alert('Error al actualizar delay');
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al actualizar delay');
        }
    });

    // Botón de iniciar bot
    document.getElementById('start-btn').addEventListener('click', async () => {
        if (!confirm('¿Iniciar el bot?')) return;

        try {
            const response = await fetch('/api/control/start', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                alert('Bot iniciado');
                setTimeout(actualizarEstado, 1000);
            } else {
                alert('Error: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al iniciar bot');
        }
    });

    // Botón de parar bot
    document.getElementById('stop-btn').addEventListener('click', async () => {
        if (!confirm('¿Parar el bot?')) return;

        try {
            const response = await fetch('/api/control/stop', { method: 'POST' });
            const data = await response.json();

            if (data.success) {
                alert('Bot detenido');
                setTimeout(actualizarEstado, 1000);
            } else {
                alert('Error: ' + data.error);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al parar bot');
        }
    });
}
