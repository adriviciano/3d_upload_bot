// Actualizar estado cada 5 segundos
setInterval(actualizarEstado, 5000);

// Actualizar al cargar
actualizarEstado();

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

        // Mostrar pausa si está activa
        const pauseInfo = document.getElementById('pause-info');
        const pauseText = document.getElementById('pause-text');
        if (data.pausa_restante && data.pausa_restante > 0) {
            pauseInfo.style.display = 'block';
            const minutos = Math.floor(data.pausa_restante / 60);
            const segundos = data.pausa_restante % 60;
            pauseText.textContent = `Pausa en progreso: ${minutos}m ${segundos}s restantes`;
        } else {
            pauseInfo.style.display = 'none';
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

        // Actualizar timestamp
        const ahora = new Date();
        const timestamp = ahora.toLocaleTimeString('es-ES');
        document.getElementById('timestamp').textContent = `Última actualización: ${timestamp}`;

    } catch (error) {
        console.error('Error actualizando estado:', error);
    }
}
