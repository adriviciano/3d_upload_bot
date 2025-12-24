from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import shutil
import zipfile
import glob
import datetime
import re
from PIL import Image
import os, time, tempfile

def procesar3MF(model_name):
    downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
    tmp_folder = r"C:\creality_bot\tmp"
    perfiles_folder = r"C:\creality_bot\perfiles_terminados"
    plantillas_folder = r"C:\creality_bot\plantillas"

    os.makedirs(tmp_folder, exist_ok=True)
    os.makedirs(perfiles_folder, exist_ok=True)

    # Esperar un momento por si el archivo aún se está descargando
    time.sleep(5)

    # 1. Buscar el archivo .3mf más reciente en Descargas
    files = [f for f in os.listdir(downloads_folder) if f.endswith(".3mf")]
    if not files:
        print("⚠️ No se encontró ningún archivo .3mf en Descargas.")
        return
    latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(downloads_folder, f)))
    source_path = os.path.join(downloads_folder, latest_file)

    # 2. Moverlo a tmp
    dest_path = os.path.join(tmp_folder, latest_file)
    shutil.move(source_path, dest_path)
    print(f"✅ Archivo movido a {dest_path}")

    # 3. Cambiar extensión a .zip
    zip_path = os.path.splitext(dest_path)[0] + ".zip"
    os.rename(dest_path, zip_path)

    # 4. Descomprimir el zip en tmp
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(tmp_folder)
    os.remove(zip_path)
    print(f"✅ Archivo descomprimido en {tmp_folder}")

    # 5. Modificar Metadata/creality.config
    config_path = os.path.join(tmp_folder, "Metadata", "creality.config")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        content = re.sub(r'(CreationDate" value=")[^"]*(")', fr'\1{today}\2', content)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ Metadata/creality.config actualizado con la fecha actual")

    # 6. Eliminar archivos de Metadata
    metadata_folder = os.path.join(tmp_folder, "Metadata")
    for f in ["custom_gcode_per_layer.xml", "project_settings.config"]:
        f_path = os.path.join(metadata_folder, f)
        if os.path.exists(f_path):
            os.remove(f_path)
    # Eliminar .gcode y .md5
    for f in glob.glob(os.path.join(metadata_folder, "*.gcode")) + glob.glob(os.path.join(metadata_folder, "*.md5")):
        os.remove(f)

    # 7. Crear carpeta del modelo en perfiles_terminados
    model_folder = os.path.join(perfiles_folder, model_name)
    os.makedirs(model_folder, exist_ok=True)

    # Copiar plate_1.png a la carpeta del modelo
    plate_file = os.path.join(metadata_folder, "plate_1.png")

    if os.path.exists(plate_file):
        shutil.copy(plate_file, model_folder)
        print(f"✅ plate_1.png copiado a {model_folder}")
    else:
        print("⚠️ plate_1.png no encontrado en Metadata")

    # 8. Procesar cada impresora en plantillas
    for impresora in os.listdir(plantillas_folder):
        plantilla_path = os.path.join(plantillas_folder, impresora)
        if not os.path.isdir(plantilla_path):
            continue

        # Copiar archivos de la plantilla a Metadata
        for file_name in ["custom_gcode_per_layer.xml", "project_settings.config"]:
            src_file = os.path.join(plantilla_path, file_name)
            dst_file = os.path.join(metadata_folder, file_name)
            if os.path.exists(src_file):
                shutil.copy(src_file, dst_file)

        # Crear zip de todo tmp
        zip_name = f"{model_name}_{impresora}.zip"
        zip_full_path = os.path.join(model_folder, zip_name)
        with zipfile.ZipFile(zip_full_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(tmp_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmp_folder)
                    zipf.write(file_path, arcname)

        # Renombrar a .3mf
        mf_name = os.path.join(model_folder, f"{model_name}_{impresora}.3mf")
        os.rename(zip_full_path, mf_name)
        print(f"✅ Archivo {mf_name} generado para la impresora {impresora}")

    # 9. Limpiar tmp
    for f in os.listdir(tmp_folder):
        f_path = os.path.join(tmp_folder, f)
        if os.path.isfile(f_path) or os.path.islink(f_path):
            os.unlink(f_path)
        elif os.path.isdir(f_path):
            shutil.rmtree(f_path)
    print("✅ Carpeta tmp limpiada")

def login(driver, wait, username, password, url_principal):
    try:
        # 1. Clicar el botón de login
        login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "span.login-btn")))
        login_btn.click()

        # 2. Rellenar el campo de usuario
        username_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][placeholder='user@example.com']")))
        username_input.clear()
        username_input.send_keys(username)

        # 3. Rellenar el campo de contraseña
        password_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'][placeholder='Must contain at least 6 characters.']")))
        password_input.clear()
        password_input.send_keys(password)

        # 4. Clicar el botón Login
        submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.cus-button.primary.success[type='submit']")))
        submit_btn.click()

        # 5. Esperar 3 segundos a que se haga el login
        time.sleep(3)

        # 6. Volver a la página inicial
        driver.get(url_principal)
        print("✅ Login realizado correctamente.")

    except Exception as e:
        print(f"⚠️ Error durante login: {e}")

def activarOperateWrap(driver, wait):
    try:
        # 1. Tomar el primer item-3mf-box
        item_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.item-3mf-box"))
        )

        # 2. Dentro de este, localizar el div comp-3mf-file-right.flex-center
        file_right_div = item_box.find_element(By.CSS_SELECTOR, "div.comp-3mf-file-right.flex-center")

        # 3. Añadir la clase comp-3mf-file-operate
        driver.execute_script("arguments[0].classList.add('comp-3mf-file-operate');", file_right_div)

        print("✅ Clase 'comp-3mf-file-operate' añadida al primer item-3mf-box correctamente.")

    except Exception as e:
        print(f"⚠️ Error al añadir clase al operate-wrap: {e}")

def esperar_descarga(downloads_folder, timeout=120):
    start_time = time.time()
    archivos_antes = set(os.listdir(downloads_folder))

    while True:
        archivos_despues = set(os.listdir(downloads_folder))
        nuevos_archivos = archivos_despues - archivos_antes

        # Buscar un .3mf que no tenga extensión temporal
        for f in nuevos_archivos:
            if f.endswith(".3mf"):
                full_path = os.path.join(downloads_folder, f)
                # Esperar a que el archivo deje de crecer (opcional)
                prev_size = -1
                while True:
                    curr_size = os.path.getsize(full_path)
                    if curr_size == prev_size:
                        return full_path
                    prev_size = curr_size
                    time.sleep(0.5)

        if time.time() - start_time > timeout:
            raise TimeoutError("⏱ Timeout esperando la descarga del archivo .3mf")
        time.sleep(0.5)

def descargarPerfil(driver, wait):
    try:
        activarOperateWrap(driver, wait)

        # 4. Esperar a que el div 'Download Print Settings' sea clickable
        download_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class,'operate-wrap')]//div[contains(text(),'Download Print Settings')]")
            )
        )

        # 5. Hacer click
        download_button.click()
        print("✅ Click en 'Download Print Settings' realizado.")

        #Esperar a que acabe la descarga
        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        archivo_descargado = esperar_descarga(downloads_folder)
        print(f"✅ Descarga completada: {archivo_descargado}")

    except Exception as e:
        print(f"⚠️ Error al descargar Print Settings: {e}")

def procesar_imagen(imagen_path):

    img = Image.open(imagen_path)
    w, h = img.size

    # 1. Recortar a cuadrado centrado
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img_cropped = img.crop((left, top, left + side, top + side))

    # 2. Escalar si es más pequeño que 400x400
    if side < 400:
        img_cropped = img_cropped.resize((400, 400), Image.LANCZOS)

    # 3. Guardar en archivo temporal (para no sobreescribir plate_1.png)
    temp_dir = tempfile.gettempdir()
    output_path = os.path.join(temp_dir, "plate_1_processed.png")
    img_cropped.save(output_path, format="PNG")

    return output_path

def subirPerfiles(driver, wait, model_folder):
    perfiles = [f for f in os.listdir(model_folder) if f.endswith(".3mf")]
    imagen_modelo = os.path.join(model_folder, "plate_1.png")

    for perfil in perfiles:
        perfil_path = os.path.join(model_folder, perfil)

        try:
            # 0. Abrir la página principal de subida de modelos
            driver.get("URL_DE_LA_PAGINA_DE_SUBIDA")  # <--- reemplaza con la URL real
            time.sleep(2)

            # 1. Click en 'add-make'
            add_make_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div.add-make"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", add_make_btn)
            time.sleep(0.5)
            try:
                add_make_btn.click()
            except:
                driver.execute_script("arguments[0].click();", add_make_btn)
            time.sleep(2)

            # 2. Subir el archivo .3mf
            input_file = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "input.el-upload__input[type='file'][accept='.3mf']")
                )
            )
            input_file.send_keys(perfil_path)
            print(f"✅ Archivo {perfil} cargado")
            time.sleep(3)

            # 3. Subir la portada (plate_1.png) usando el quinto input
            if os.path.exists(imagen_modelo):
                portada_procesada = procesar_imagen(imagen_modelo)

                inputs_file = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if len(inputs_file) >= 5:
                    input_portada = inputs_file[4]
                    input_portada.send_keys(portada_procesada)
                    print(f"✅ Imagen portada procesada y cargada ({portada_procesada})")
                else:
                    print("⚠️ No se encontró el input correcto para la portada")
                time.sleep(3)

                # 3b. Click en Confirm después de subir la portada
                try:
                    buttons = driver.find_elements(
                        By.CSS_SELECTOR, "button.el-button.el-button--primary.el-button--small"
                    )
                    confirm_btn = None
                    for btn in buttons:
                        try:
                            span = btn.find_element(By.TAG_NAME, "span")
                            if span.text.strip() == "Confirm":
                                confirm_btn = btn
                                break
                        except:
                            continue

                    if confirm_btn:
                        driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                        time.sleep(0.3)
                        try:
                            confirm_btn.click()
                        except:
                            driver.execute_script("arguments[0].click();", confirm_btn)
                        print("✅ Confirm portada clicado")
                        time.sleep(2)
                    else:
                        print("⚠️ No se encontró el botón Confirm")

                except Exception as e:
                    print(f"⚠️ Error al intentar clicar Confirm: {e}")

            else:
                print("⚠️ No se encontró plate_1.png en la carpeta del modelo")

            # 4. Click en Submit
            submit_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(),'Submit')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            time.sleep(0.5)
            try:
                submit_btn.click()
            except:
                driver.execute_script("arguments[0].click();", submit_btn)
            print(f"✅ Perfil '{perfil}' subido correctamente")

            # 5. Esperar un poco antes de pasar al siguiente perfil
            time.sleep(4)

        except Exception as e:
            print(f"⚠️ Error subiendo perfil '{perfil}': {e}")

    # 6. Eliminar la carpeta de perfiles después de subir todos
    try:
        shutil.rmtree(model_folder)
        print(f"🗑️ Carpeta '{model_folder}' eliminada después de subir los perfiles")
    except Exception as e:
        print(f"⚠️ No se pudo eliminar la carpeta '{model_folder}': {e}")

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 10)

url = "https://www.crealitycloud.com/model-category/3d-print-all?timeType=4&isPay=2"
driver.get(url)

# Aplicar zoom al 33% en la página principal
driver.execute_script("document.body.style.zoom='33%'")
time.sleep(3)

login(driver, wait, "adriviciano@gmail.com", "vicibache2003", url)

# Mostrar el popover forzando el display
popover = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.page-popper-content")))
driver.execute_script("arguments[0].style.display='block';", popover)

# Activar Pagination
pagination_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[@title='Pagination']")))
pagination_button.click()
print("Modo paginado activado ✅")

# Esperar a que carguen los modelos
wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.model-name")))

while True:
    # Reaplicar zoom en la página principal por si se refresca
    driver.execute_script("document.body.style.zoom='33%'")

    # Detectar modelos
    model_links = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.model-name")))
    print(f"Encontrados {len(model_links)} modelos en esta página")

    for i, model in enumerate(model_links):
        try:
            # Abrir el modelo en nueva pestaña usando Ctrl + click (o JavaScript)
            model_url = model.get_attribute("href")
            driver.execute_script(f"window.open('{model_url}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            #time.sleep(2)  # esperar a que cargue el modelo
            print(f"Accediendo al modelo {i+1}")

            descargarPerfil(driver, wait)

            try:
                h1 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1.group-name")))
                model_name = h1.text.strip()  # innerText limpio
            except Exception as e:
                print(f"⚠️ No se pudo obtener el nombre del modelo: {e}")
                model_name = "modelo_desconocido"

            procesar3MF(model_name)
            subirPerfiles(driver, wait, os.path.join(r"C:\creality_bot\perfiles_terminados", model_name))

            # Cerrar la pestaña del modelo
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            # Reaplicar zoom en la página principal
            driver.execute_script("document.body.style.zoom='33%'")

        except Exception as e:
            print(f"⚠️ Error en modelo {i+1}: {e}")
            break

    # Pasar a la siguiente página
    try:
        next_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next")))
        next_button.click()
        print("➡️ Pasando a la siguiente página...\n")
        time.sleep(2)
    except:
        print("✅ No se encontró el botón 'Siguiente'. Fin del recorrido.")
        break

driver.quit()
