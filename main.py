import os
import sys
from pathlib import Path
from typing import List

from login import LoginResult, login
from models import (
    ModelDatabase,
    list_trending_models,
    process_model_complete,
    descargar_y_procesar_3mf,
    subir_todos_los_perfiles,
)


def load_dotenv(path: Path = Path(".env")) -> None:
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


def obtener_modelos_populares(
    login_result: LoginResult,
    db: ModelDatabase,
    max_paginas: int = 3,
    page_size: int = 10,
) -> List[str]:
    """Descarga modelos trending y los registra en la base local."""
    nombres: List[str] = []

    for page in range(1, max_paginas + 1):
        try:
            models = list_trending_models(
                login_result=login_result,
                page=page,
                page_size=page_size,
                save_to_db=False,
            )
            for model in models:
                if model.name and model.id:
                    db.add_model(model.name, model.id)
                    nombres.append(model.name)
        except Exception as e:
            print(f"⚠️ Error obteniendo página {page} de modelos: {e}")
            continue

    db.save_database()
    # Eliminar duplicados preservando orden
    unique_names = list(dict.fromkeys(nombres))
    return unique_names


def main() -> None:
    print("🤖 Iniciando bot de Creality Cloud...")
    print("=" * 60)

    load_dotenv()

    # Compatibilidad: CREALITY_ACCOUNT o CREALITY_EMAIL
    account = os.getenv("CREALITY_ACCOUNT") or os.getenv("CREALITY_EMAIL")
    password = os.getenv("CREALITY_PASSWORD")

    if not account or not password:
        raise SystemExit(
            "Configura CREALITY_ACCOUNT/CREALITY_EMAIL y CREALITY_PASSWORD (en .env o entorno) antes de ejecutar."
        )

    try:
        # Login
        print(f"\n🔐 Iniciando sesión con cuenta: {account}")
        login_result: LoginResult = login(account, password)
        print("✅ Login exitoso en Creality Cloud")
        print(f"   🆔 User ID: {login_result.user_id}")

        # Base de datos local
        db = ModelDatabase()
        print(f"\n📚 Base de datos cargada: {len(db.models)} modelos registrados")

        # Obtener modelos populares (paginas configurable)
        print("\n🔍 Obteniendo lista de modelos populares...")
        modelos_nuevos = obtener_modelos_populares(login_result, db, max_paginas=2)
        print(f"   📊 Encontrados {len(modelos_nuevos)} modelos nuevos")

        if not modelos_nuevos:
            print("\n✅ No hay modelos nuevos para procesar")
            return

        # Procesar y subir cada modelo
        print(f"\n🚀 Procesando {len(modelos_nuevos)} modelos...")
        print("=" * 60)

        procesados = 0
        errores = 0
        total_subidos = 0

        for i, model_name in enumerate(modelos_nuevos, 1):
            print(f"\n📦 [{i}/{len(modelos_nuevos)}] Procesando: {model_name}")
            print("-" * 60)

            try:
                # 1) Obtener info del modelo
                result = process_model_complete(login_result, model_name, db, timeout=30)
                if not result:
                    print("   ⚠️ No se pudo obtener información del modelo")
                    errores += 1
                    continue

                model_3mf_info, download_url = result

                # 2) Descargar y procesar el 3MF
                print("\n   ⬇️ Descargando y procesando archivo 3MF...")
                model_folder = descargar_y_procesar_3mf(login_result, model_name, download_url)

                if not model_folder:
                    print("   ❌ Error procesando el modelo")
                    errores += 1
                    continue

                print("   ✅ Modelo procesado correctamente")

                # 3) Subir perfiles
                print("\n   📤 Subiendo perfiles de impresión...")
                model_entry = db.get_model(model_name)
                model_group_id = model_entry.model_id if model_entry else ""

                exitosos, fallidos = subir_todos_los_perfiles(
                    login_result=login_result,
                    model_folder=model_folder,
                    model_group_id=model_group_id,
                    timeout=60,
                )

                if exitosos > 0:
                    print(f"   ✅ Subidos {exitosos} archivos exitosamente")
                    procesados += 1
                    total_subidos += exitosos

                if fallidos > 0:
                    print(f"   ⚠️ {fallidos} archivos fallaron al subir")
                    errores += fallidos

            except KeyboardInterrupt:
                print("\n\n⚠️ Proceso interrumpido por el usuario")
                break
            except Exception as e:
                print(f"   ❌ Error procesando modelo: {e}")
                errores += 1

        # Resumen
        print("\n" + "=" * 60)
        print("📊 RESUMEN FINAL")
        print("=" * 60)
        print(f"✅ Modelos procesados exitosamente: {procesados}")
        print(f"📤 Total de archivos subidos: {total_subidos}")
        print(f"❌ Errores encontrados: {errores}")
        print("\n🎉 ¡Proceso completado!")

    except KeyboardInterrupt:
        print("\n\n⚠️ Bot detenido por el usuario")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
