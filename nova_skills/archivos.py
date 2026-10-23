"""
nova_skills/archivos.py — Organización y manejo del sistema de archivos.
====================================================================
Tercer ejemplo de skill "engordada":

  - mover_archivo() y copiar_archivo() resuelven colisiones de nombre
    automáticamente (si el destino ya existe, agregan sufijo _1, _2...
    en vez de sobrescribir en silencio o reventar con FileExistsError).
  - Ambas VERIFICAN el resultado: mover_archivo() confirma que el
    origen desapareció y que el destino tiene el tamaño correcto;
    copiar_archivo() confirma tamaño y un hash de muestra, para no
    reportar éxito ante una copia truncada por falta de espacio en
    disco a mitad de camino.
"""

import os
import time
import shutil
import zipfile
import hashlib
from typing import Optional, List
from ._core import skill, _requiere, logger

try:
    from send2trash import send2trash
    SEND2TRASH_AVAILABLE = True
except Exception as e:
    SEND2TRASH_AVAILABLE = False
    logger.debug(f"[SKILLS] send2trash no disponible en archivos.py ({e})")


def _hash_rapido(ruta: str, bytes_muestra: int = 65536) -> str:
    """Hash de una muestra del archivo (inicio) — suficiente para verificar
    integridad tras mover/copiar sin recalcular archivos gigantes enteros."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        h.update(f.read(bytes_muestra))
    return h.hexdigest()


def _ruta_sin_colision(ruta: str) -> str:
    """Si 'ruta' ya existe, agrega sufijo _1, _2... hasta encontrar una
    libre. Evita sobrescribir archivos existentes sin avisar."""
    if not os.path.exists(ruta):
        return ruta
    base, ext = os.path.splitext(ruta)
    i = 1
    nueva = f"{base}_{i}{ext}"
    while os.path.exists(nueva):
        i += 1
        nueva = f"{base}_{i}{ext}"
    return nueva


@skill("crear_archivo", "archivos", "Crea un archivo de texto con el contenido dado (lo sobrescribe si existe).")
def crear_archivo(ruta: str, contenido: str = ""):
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)
    return ruta

@skill("leer_archivo", "archivos", "Lee y devuelve el contenido de texto de un archivo.")
def leer_archivo(ruta: str):
    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

@skill("escribir_archivo", "archivos", "Escribe (o agrega, con modo='a') contenido a un archivo de texto.")
def escribir_archivo(ruta: str, contenido: str, modo: str = "w"):
    with open(ruta, modo, encoding="utf-8") as f:
        f.write(contenido)
    return ruta

@skill("eliminar_archivo", "archivos", "Elimina un archivo de forma permanente.")
def eliminar_archivo(ruta: str):
    os.remove(ruta)
    return True

@skill("mover_a_papelera", "archivos", "Envía un archivo/carpeta a la papelera de reciclaje (recuperable), no lo borra para siempre.", requiere=["send2trash"])
def mover_a_papelera(ruta: str):
    _requiere(SEND2TRASH_AVAILABLE, "send2trash")
    send2trash(ruta)
    return True

@skill("mover_archivo", "archivos",
       "Mueve un archivo evitando colisiones de nombre (si el destino ya "
       "existe, agrega sufijo _1, _2...) y VERIFICA que el origen realmente "
       "desapareció y el destino quedó con el tamaño correcto.")
def mover_archivo(origen: str, destino: str, evitar_colision: bool = True):
    if not os.path.isfile(origen):
        raise FileNotFoundError(f"No existe el archivo origen: {origen}")
    tamano_original = os.path.getsize(origen)

    if os.path.isdir(destino):
        destino = os.path.join(destino, os.path.basename(origen))
    if evitar_colision:
        destino = _ruta_sin_colision(destino)

    shutil.move(origen, destino)

    if os.path.exists(origen):
        raise RuntimeError(f"El archivo origen sigue existiendo tras mover: {origen}")
    if not os.path.isfile(destino) or os.path.getsize(destino) != tamano_original:
        raise RuntimeError(f"El archivo destino no quedó íntegro: {destino}")

    return destino

@skill("copiar_archivo", "archivos",
       "Copia un archivo evitando colisiones de nombre y VERIFICANDO que "
       "el tamaño y un hash de muestra del destino coincidan con el origen "
       "(detecta copias truncadas, ej. por falta de espacio en disco).")
def copiar_archivo(origen: str, destino: str, evitar_colision: bool = True):
    if not os.path.isfile(origen):
        raise FileNotFoundError(f"No existe el archivo origen: {origen}")

    if os.path.isdir(destino):
        destino = os.path.join(destino, os.path.basename(origen))
    if evitar_colision:
        destino = _ruta_sin_colision(destino)

    shutil.copy2(origen, destino)

    if os.path.getsize(origen) != os.path.getsize(destino):
        raise RuntimeError(f"La copia no coincide en tamaño: {origen} -> {destino}")
    if _hash_rapido(origen) != _hash_rapido(destino):
        raise RuntimeError(f"La copia no coincide en contenido (hash de muestra): {origen} -> {destino}")

    return destino

@skill("renombrar_archivo", "archivos", "Renombra un archivo dentro de la misma carpeta.")
def renombrar_archivo(ruta: str, nuevo_nombre: str):
    carpeta = os.path.dirname(ruta)
    nueva_ruta = os.path.join(carpeta, nuevo_nombre)
    os.rename(ruta, nueva_ruta)
    return nueva_ruta

@skill("crear_carpeta", "archivos", "Crea una carpeta (y las intermedias necesarias) si no existe.")
def crear_carpeta(ruta: str):
    os.makedirs(ruta, exist_ok=True)
    return ruta

@skill("eliminar_carpeta", "archivos", "Elimina una carpeta y todo su contenido de forma permanente.")
def eliminar_carpeta(ruta: str):
    shutil.rmtree(ruta)
    return True

@skill("listar_archivos", "archivos", "Lista archivos de una carpeta, opcionalmente filtrados por extensión (ej: '.pdf').")
def listar_archivos(carpeta: str, extension: Optional[str] = None):
    archivos = os.listdir(carpeta)
    if extension:
        archivos = [a for a in archivos if a.lower().endswith(extension.lower())]
    return sorted(archivos)

@skill("buscar_archivo", "archivos", "Busca de forma recursiva archivos cuyo nombre contenga el texto dado.")
def buscar_archivo(nombre_parcial: str, carpeta_raiz: str):
    nombre_parcial = nombre_parcial.lower()
    encontrados = []
    for raiz, _, archivos in os.walk(carpeta_raiz):
        for a in archivos:
            if nombre_parcial in a.lower():
                encontrados.append(os.path.join(raiz, a))
    return encontrados

@skill("organizar_carpeta_por_tipo", "archivos", "Organiza los archivos sueltos de una carpeta en subcarpetas según su extensión.")
def organizar_carpeta_por_tipo(carpeta: str):
    movidos = {}
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if os.path.isdir(ruta):
            continue
        ext = os.path.splitext(nombre)[1].lstrip(".").lower() or "sin_extension"
        subcarpeta = os.path.join(carpeta, ext.upper())
        os.makedirs(subcarpeta, exist_ok=True)
        shutil.move(ruta, _ruta_sin_colision(os.path.join(subcarpeta, nombre)))
        movidos[ext] = movidos.get(ext, 0) + 1
    return movidos

@skill("comprimir_archivos", "archivos", "Comprime una lista de archivos en un .zip.")
def comprimir_archivos(archivos: List[str], destino_zip: str):
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for a in archivos:
            zf.write(a, arcname=os.path.basename(a))
    return destino_zip

@skill("descomprimir_zip", "archivos", "Extrae el contenido de un .zip a una carpeta destino.")
def descomprimir_zip(ruta_zip: str, carpeta_destino: str):
    os.makedirs(carpeta_destino, exist_ok=True)
    with zipfile.ZipFile(ruta_zip, "r") as zf:
        zf.extractall(carpeta_destino)
    return carpeta_destino

@skill("obtener_tamano_archivo", "archivos", "Devuelve el tamaño de un archivo en bytes.")
def obtener_tamano_archivo(ruta: str) -> int:
    return os.path.getsize(ruta)

@skill("archivo_existe", "archivos", "Comprueba si un archivo existe.")
def archivo_existe(ruta: str) -> bool:
    return os.path.isfile(ruta)

@skill("carpeta_existe", "archivos", "Comprueba si una carpeta existe.")
def carpeta_existe(ruta: str) -> bool:
    return os.path.isdir(ruta)

@skill("obtener_ruta_descargas", "archivos", "Devuelve la ruta de la carpeta 'Descargas' del usuario actual.")
def obtener_ruta_descargas():
    return os.path.join(os.path.expanduser("~"), "Downloads")

@skill("obtener_ruta_escritorio", "archivos", "Devuelve la ruta del escritorio del usuario actual.")
def obtener_ruta_escritorio():
    return os.path.join(os.path.expanduser("~"), "Desktop")

@skill("obtener_ruta_documentos", "archivos", "Devuelve la ruta de la carpeta 'Documentos' del usuario actual.")
def obtener_ruta_documentos():
    return os.path.join(os.path.expanduser("~"), "Documents")

@skill("limpiar_archivos_temporales", "archivos", "Elimina de una carpeta los archivos más viejos que N días (limpieza de temporales).")
def limpiar_archivos_temporales(carpeta: str, dias: int = 7):
    limite = time.time() - dias * 86400
    eliminados = []
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if os.path.isfile(ruta) and os.path.getmtime(ruta) < limite:
            try:
                os.remove(ruta)
                eliminados.append(nombre)
            except OSError:
                continue
    return eliminados

@skill("calcular_hash_archivo", "archivos", "Calcula el hash SHA-256 completo de un archivo (útil para verificar integridad/duplicados).")
def calcular_hash_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(8192), b""):
            h.update(bloque)
    return h.hexdigest()

@skill("listar_archivos_recientes", "archivos", "Lista los N archivos modificados más recientemente en una carpeta.")
def listar_archivos_recientes(carpeta: str, n: int = 10):
    archivos = [os.path.join(carpeta, f) for f in os.listdir(carpeta)
                if os.path.isfile(os.path.join(carpeta, f))]
    archivos.sort(key=os.path.getmtime, reverse=True)
    return archivos[:n]

@skill("duplicar_archivo", "archivos", "Crea una copia de un archivo en la misma carpeta con sufijo '_copia' (o '_copia_1', '_copia_2'... si ya existe).")
def duplicar_archivo(ruta: str):
    base, ext = os.path.splitext(ruta)
    destino = _ruta_sin_colision(f"{base}_copia{ext}")
    shutil.copy2(ruta, destino)
    return destino
