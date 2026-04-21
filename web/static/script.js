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

        // Actualizar modelo actual
        const modeloEl = document.getElementById('modelo-actual');
        if (data.modelo_actual) {
            modeloEl.textContent = `📦 ${data.modelo_actual}`;
        } else {
            modeloEl.textContent = 'Esperando información...';
        }

        // Actualizar logs de errores
        const logsEl = document.getElementById('logs-container');
        if (data.ultimos_errores && data.ultimos_errores.length > 0) {
            logsEl.innerHTML = data.ultimos_errores
                .map(error => `<div class="log-item">❌ ${error}</div>`)
                .join('');
        } else {
            logsEl.innerHTML = '<p class="no-errors">Sin errores</p>';
        }

        // Actualizar timestamp
        const ahora = new Date();
        const timestamp = ahora.toLocaleTimeString('es-ES');
        document.getElementById('timestamp').textContent = `Última actualización: ${timestamp}`;

    } catch (error) {
        console.error('Error actualizando estado:', error);
    }
}
