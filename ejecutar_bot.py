#!/usr/bin/env python3
"""
Script principal para ejecutar el bot de Creality Cloud.
Procesa y sube automáticamente perfiles de impresión de modelos populares.
"""

import os
import sys
import time
from pathlib import Path
from login import LoginResult, login
from models import (
    ModelDatabase,
    list_trending_models,
    process_model_complete,
    descargar_y_procesar_3mf,
    subir_todos_los_perfiles
)
from status import bot_status, get_delay_config


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carga variables de entorno desde archivo .env"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def main():
    """Función principal del bot"""
    # Guardar PID para que web verifique
    import signal

    class BotInterrupt(Exception):
        pass

    def handle_sigterm(signum, frame):
        raise BotInterrupt("Señal SIGTERM recibida")

    signal.signal(signal.SIGTERM, handle_sigterm)

    pid = os.getpid()
    with open('bot.pid', 'w') as f:
        f.write(str(pid))

    print("🤖 Iniciando bot de Creality Cloud...")
    print("=" * 60)

    # Limpiar logs de ejecuciones anteriores
    if os.path.exists('errors.log'):
        os.remove('errors.log')

    # Cargar credenciales
    load_dotenv()
    account = os.getenv("CREALITY_EMAIL")
    password = os.getenv("CREALITY_PASSWORD")

    if not account or not password:
        print("❌ Error: Configura CREALITY_EMAIL y CREALITY_PASSWORD en .env")
        sys.exit(1)

    try:
        # Login en Creality Cloud
        print(f"\n🔐 Iniciando sesión con cuenta: {account}")
        login_result: LoginResult = login(account, password)
        print("✅ Login exitoso en Creality Cloud")
        print(f"   🆔 User ID: {login_result.user_id}")

        # Cargar base de datos de modelos
        db = ModelDatabase()
        print(f"\n📚 Base de datos cargada: {len(db.models)} modelos registrados")

        # Bucle infinito: página por página
        pagina = 1
        procesados_total = 0
        subidos_total = 0
        errores_total = 0

        bot_status.actualizar(estado="Iniciado correctamente", pagina=pagina)

        while True:
            print(f"\n🔍 Obteniendo modelos de página {pagina}...")
            bot_status.actualizar(estado="Buscando modelos", pagina=pagina)

            # Obtener modelos de esta página
            modelos = list_trending_models(
                login_result=login_result,
                page=pagina,
                page_size=20,
                is_pay=2,
                save_to_db=False
            )

            if not modelos:
                print("✅ No hay más modelos disponibles")
                bot_status.actualizar(estado="Completado - sin más modelos")
                break

            print(f"   📊 Obtuvieron {len(modelos)} modelos")

            # Procesar modelos sin visitar de esta página
            modelos_sin_visitar = []
            for modelo in modelos:
                entrada = db.get_model(modelo.name)
                if not entrada or not entrada.visited:
                    modelos_sin_visitar.append(modelo.name)
                    db.add_model(modelo.name, modelo.id, visited=False)

            db.save_database()

            if not modelos_sin_visitar:
                print("   ⏭️ Todos los modelos de esta página ya fueron procesados")
                pagina += 1
                continue

            print(f"   🚀 {len(modelos_sin_visitar)} modelos sin procesar")
            print("=" * 60)

            # Procesar cada modelo sin visitar
            for i, model_name in enumerate(modelos_sin_visitar, 1):
                print(f"\n📦 [{pagina}-{i}/{len(modelos_sin_visitar)}] Procesando: {model_name}")
                print("-" * 60)

                bot_status.actualizar(
                    estado="Procesando",
                    modelo_actual=model_name,
                    pagina=pagina,
                    modelos_procesados=procesados_total,
                    archivos_subidos=subidos_total,
                    errores=errores_total
                )

                try:
                    # 1. Obtener información del modelo
                    result = process_model_complete(login_result, model_name, db, timeout=30)
                    if not result:
                        print(f"   ⚠️ No se pudo obtener información del modelo")
                        errores_total += 1
                        bot_status.agregar_error(f"{model_name}: No se pudo obtener información")
                        continue

                    _, download_url = result

                    # 2. Descargar y procesar archivo 3MF
                    print(f"\n   ⬇️ Descargando y procesando archivo 3MF...")
                    model_folder = descargar_y_procesar_3mf(login_result, model_name, download_url)

                    if not model_folder:
                        print(f"   ❌ Error procesando el modelo")
                        errores_total += 1
                        bot_status.agregar_error(f"{model_name}: Error descargando/procesando 3MF")
                        continue

                    print(f"   ✅ Modelo procesado correctamente")

                    # 3. Subir archivos 3MF procesados
                    print(f"\n   📤 Subiendo perfiles de impresión...")
                    model_entry = db.get_model(model_name)
                    model_group_id = model_entry.model_id if model_entry else ""

                    exitosos, fallidos = subir_todos_los_perfiles(
                        login_result=login_result,
                        model_folder=model_folder,
                        model_group_id=model_group_id,
                        timeout=60
                    )

                    if exitosos > 0:
                        print(f"   ✅ Subidos {exitosos} archivos exitosamente")
                        procesados_total += 1
                        subidos_total += exitosos
                        bot_status.actualizar(
                            modelos_procesados=procesados_total,
                            archivos_subidos=subidos_total
                        )

                    if fallidos > 0:
                        print(f"   ⚠️ {fallidos} archivos fallaron al subir")
                        errores_total += fallidos
                        bot_status.agregar_error(f"{model_name}: {fallidos} archivos fallaron al subir")

                    # Esperar antes de siguiente modelo (configurado)
                    delay = get_delay_config()
                    print(f"\n⏳ Esperando {delay}s antes de siguiente modelo...")
                    bot_status.iniciar_pausa(delay)
                    time.sleep(delay)
                except (KeyboardInterrupt, BotInterrupt):
                    print("\n\n⚠️ Proceso interrumpido")
                    raise
                except Exception as e:
                    print(f"   ❌ Error procesando modelo: {e}")
                    errores_total += 1
                    bot_status.agregar_error(f"{model_name}: {str(e)[:80]}")

            # Pasar a siguiente página
            if len(modelos) < 20:
                print("\n✅ Se han procesado todos los modelos disponibles")
                break

            pagina += 1
            print(f"\n{'='*60}")

        # Resumen final
        print("\n" + "=" * 60)
        print("📊 RESUMEN FINAL")
        print("=" * 60)
        print(f"✅ Modelos procesados exitosamente: {procesados_total}")
        print(f"📤 Total de archivos subidos: {subidos_total}")
        print(f"❌ Errores encontrados: {errores_total}")
        print("\n🎉 ¡Bot completado!")

    except (KeyboardInterrupt, BotInterrupt):
        print("\n\n⚠️ Bot detenido")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
