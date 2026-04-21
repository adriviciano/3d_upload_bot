#!/usr/bin/env python3
"""Test para verificar modelos nuevos disponibles en Creality Cloud"""

import os
from dotenv import load_dotenv
from login import login
from models import list_trending_models, ModelDatabase

load_dotenv()

email = os.getenv("CREALITY_EMAIL")
password = os.getenv("CREALITY_PASSWORD")

print("🔐 Login...")
login_result = login(email, password)
print(f"✅ Login exitoso\n")

print("📚 Cargando BD...")
db = ModelDatabase()
print(f"   BD actual: {len(db.models)} modelos\n")

print("🔍 Obteniendo modelos trending (primeras 3 páginas)...")
nuevos = []
for page in range(1, 4):
    modelos = list_trending_models(
        login_result=login_result,
        page=page,
        page_size=20,
        is_pay=2,
        save_to_db=False
    )
    print(f"\n   Página {page}: {len(modelos)} modelos")
    for modelo in modelos:
        if not db.get_model(modelo.name):
            nuevos.append(modelo.name)
            print(f"      ✨ NUEVO: {modelo.name}")
        else:
            print(f"      ✓ Ya en BD: {modelo.name}")

print(f"\n{'='*60}")
print(f"📊 RESUMEN")
print(f"{'='*60}")
print(f"Total modelos trending: {len(modelos) * 3}")
print(f"Modelos nuevos: {len(nuevos)}")
print(f"Modelos ya en BD: {(len(modelos) * 3) - len(nuevos)}")
print(f"\n📝 Nuevos modelos encontrados:")
for modelo in nuevos:
    print(f"   - {modelo}")
