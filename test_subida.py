#!/usr/bin/env python3
"""
Script de Test para Subida de Archivos - Creality Cloud Bot

Tests incluidos:
1. Test de autenticación
2. Test de credenciales OSS
3. Test de subida de imagen
4. Test de flujo completo (opcional)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image
import tempfile

# Cargar variables de entorno
load_dotenv()

# Importar módulos del proyecto
from login import login, LoginResult
from models import (
    get_aliyun_credentials,
    subir_imagen_oss,
    list_trending_models,
    ModelDatabase
)


def crear_imagen_prueba() -> str:
    """
    Crea una imagen de prueba temporal de 400x400px.
    
    Returns:
        Ruta al archivo de imagen creado
    """
    # Crear imagen de prueba con degradado
    img = Image.new('RGB', (400, 400), color='#FF6B6B')
    
    # Añadir un patrón simple
    pixels = img.load()
    for i in range(400):
        for j in range(400):
            # Crear un patrón de cuadrícula
            if (i // 50 + j // 50) % 2 == 0:
                pixels[i, j] = (255, 107, 107)  # Rojo claro
            else:
                pixels[i, j] = (107, 107, 255)  # Azul
    
    # Guardar en archivo temporal
    temp_file = tempfile.NamedTemporaryFile(
        suffix='.jpg',
        delete=False,
        mode='wb'
    )
    img.save(temp_file.name, 'JPEG', quality=95)
    temp_file.close()
    
    return temp_file.name


def test_autenticacion() -> LoginResult:
    """
    Test 1: Verifica que la autenticación funcione correctamente.
    
    Returns:
        LoginResult si el test es exitoso
    
    Raises:
        Exception si el test falla
    """
    print("\n" + "="*60)
    print("TEST 1: AUTENTICACIÓN")
    print("="*60)
    
    email = os.getenv('CREALITY_EMAIL')
    password = os.getenv('CREALITY_PASSWORD')
    
    if not email or not password:
        raise Exception(
            "❌ ERROR: Variables de entorno no configuradas.\n"
            "   Asegúrate de tener CREALITY_EMAIL y CREALITY_PASSWORD en .env"
        )
    
    print(f"📧 Email: {email}")
    print("🔐 Password: ******")
    print("\n🔄 Intentando autenticación...")
    
    try:
        login_result = login(email, password)
        
        print("\n✅ AUTENTICACIÓN EXITOSA")
        print(f"   Token: {login_result.token[:20]}...")
        print(f"   User ID: {login_result.user_id}")
        print(f"   Model Token: {login_result.model_token[:20] if login_result.model_token else 'None'}...")
        print(f"   Model User ID: {login_result.model_user_id}")
        
        return login_result
        
    except Exception as e:
        print(f"\n❌ ERROR EN AUTENTICACIÓN: {e}")
        raise


def test_credenciales_oss(login_result: LoginResult):
    """
    Test 2: Verifica que se puedan obtener credenciales OSS.
    
    Args:
        login_result: Resultado del login
    
    Raises:
        Exception si el test falla
    """
    print("\n" + "="*60)
    print("TEST 2: OBTENCIÓN DE CREDENCIALES OSS")
    print("="*60)
    
    print("🔄 Obteniendo credenciales STS de Alibaba Cloud...")
    
    try:
        credentials = get_aliyun_credentials(login_result)
        
        if not credentials:
            raise Exception("No se obtuvieron credenciales")
        
        print("\n✅ CREDENCIALES OSS OBTENIDAS")
        print(f"   Access Key ID: {credentials.access_key_id[:20]}...")
        print(f"   Secret Access Key: {credentials.secret_access_key[:20]}...")
        print(f"   Session Token: {credentials.session_token[:30]}...")
        print(f"   Expira en: {credentials.life_time} segundos")
        print(f"   ¿Expirado?: {'Sí ❌' if credentials.is_expired() else 'No ✅'}")
        
        return credentials
        
    except Exception as e:
        print(f"\n❌ ERROR OBTENIENDO CREDENCIALES OSS: {e}")
        raise


def test_subida_imagen(login_result: LoginResult, credentials):
    """
    Test 3: Prueba la subida de una imagen a OSS.
    
    Args:
        login_result: Resultado del login
        credentials: Credenciales OSS
    
    Raises:
        Exception si el test falla
    """
    print("\n" + "="*60)
    print("TEST 3: SUBIDA DE IMAGEN")
    print("="*60)
    
    imagen_path = None
    
    try:
        # Crear imagen de prueba
        print("🎨 Creando imagen de prueba...")
        imagen_path = crear_imagen_prueba()
        print(f"   ✅ Imagen creada: {imagen_path}")
        print(f"   📊 Tamaño: {os.path.getsize(imagen_path)} bytes")
        
        # Subir imagen
        print("\n🔄 Subiendo imagen a OSS...")
        cdn_url = subir_imagen_oss(
            login_result=login_result,
            imagen_path=imagen_path,
            credentials=credentials
        )
        
        if not cdn_url:
            raise Exception("La función subir_imagen_oss retornó None")
        
        print(f"\n✅ IMAGEN SUBIDA EXITOSAMENTE")
        print(f"   🔗 URL CDN: {cdn_url}")
        
        return cdn_url
        
    except Exception as e:
        print(f"\n❌ ERROR EN SUBIDA DE IMAGEN: {e}")
        raise
        
    finally:
        # Limpiar archivo temporal
        if imagen_path and os.path.exists(imagen_path):
            try:
                os.unlink(imagen_path)
                print(f"\n🧹 Limpieza: Imagen temporal eliminada")
            except:
                pass


def test_listar_modelos(login_result: LoginResult):
    """
    Test 4 (Opcional): Lista modelos trending para verificar conectividad.
    
    Args:
        login_result: Resultado del login
    """
    print("\n" + "="*60)
    print("TEST 4: LISTAR MODELOS TRENDING (Opcional)")
    print("="*60)
    
    try:
        print("🔄 Obteniendo modelos trending...")
        
        models = list_trending_models(
            login_result=login_result,
            page=1,
            page_size=5,
            save_to_db=False  # No guardar en DB durante el test
        )
        
        print(f"\n✅ MODELOS OBTENIDOS: {len(models)}")
        
        for i, model in enumerate(models[:3], 1):  # Mostrar solo los primeros 3
            print(f"\n   📦 Modelo {i}:")
            print(f"      Nombre: {model.name}")
            print(f"      Autor: {model.author}")
            print(f"      Descargas: {model.download_count}")
            print(f"      Likes: {model.like_count}")
            print(f"      Gratis: {'Sí' if model.is_free else 'No'}")
        
        if len(models) > 3:
            print(f"\n   ... y {len(models) - 3} modelos más")
        
    except Exception as e:
        print(f"\n⚠️ ERROR LISTANDO MODELOS: {e}")
        print("   (Este test es opcional y no afecta las pruebas de subida)")


def main():
    """
    Función principal que ejecuta todos los tests en secuencia.
    """
    print("\n" + "🚀"*30)
    print("   SCRIPT DE PRUEBA - SUBIDA DE ARCHIVOS")
    print("   Creality Cloud Bot")
    print("🚀"*30)
    
    login_result = None
    credentials = None
    tests_pasados = 0
    tests_totales = 4
    
    try:
        # Test 1: Autenticación
        login_result = test_autenticacion()
        tests_pasados += 1
        
        # Test 2: Credenciales OSS
        credentials = test_credenciales_oss(login_result)
        tests_pasados += 1
        
        # Test 3: Subida de imagen
        test_subida_imagen(login_result, credentials)
        tests_pasados += 1
        
        # Test 4: Listar modelos (opcional)
        test_listar_modelos(login_result)
        tests_pasados += 1
        
        # Resumen final
        print("\n" + "="*60)
        print("RESUMEN DE TESTS")
        print("="*60)
        print(f"✅ Tests pasados: {tests_pasados}/{tests_totales}")
        print(f"🎉 ¡TODOS LOS TESTS COMPLETADOS CON ÉXITO!")
        print("\n💡 El sistema de subida está funcionando correctamente.")
        print("   Puedes proceder con el bot completo usando ejecutar_bot.py")
        print("="*60)
        
        return 0
        
    except Exception as e:
        print("\n" + "="*60)
        print("RESUMEN DE TESTS")
        print("="*60)
        print(f"❌ Tests pasados: {tests_pasados}/{tests_totales}")
        print(f"💥 ERROR: {e}")
        print("\n🔍 Revisa los logs arriba para más detalles.")
        print("="*60)
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
