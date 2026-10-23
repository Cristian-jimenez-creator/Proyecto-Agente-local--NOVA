"""
nova_skills/aplicaciones.py — Reconocimiento y ciclo de vida de procesos/apps.
"""

import os
import time
import shutil
import subprocess
from ._core import skill, _requiere, logger, IS_WINDOWS

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception as e:
    PSUTIL_AVAILABLE = False
    logger.debug(f"[SKILLS] psutil no disponible en aplicaciones.py ({e})")

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except Exception as e:
    PYGETWINDOW_AVAILABLE = False
    logger.debug(f"[SKILLS] pygetwindow no disponible en aplicaciones.py ({e})")


@skill("abrir_aplicacion", "aplicaciones", "Abre una aplicación o archivo por nombre/ruta (usa el comando 'start' de Windows).")
def abrir_aplicacion(nombre_o_ruta: str):
    if IS_WINDOWS:
        if os.path.exists(nombre_o_ruta):
            os.startfile(nombre_o_ruta)
        else:
            subprocess.Popen(f'start "" "{nombre_o_ruta}"', shell=True)
    else:
        subprocess.Popen([nombre_o_ruta])
    return nombre_o_ruta

@skill("cerrar_aplicacion", "aplicaciones", "Cierra (de forma normal) todos los procesos que coincidan con el nombre dado.", requiere=["psutil"])
def cerrar_aplicacion(nombre_proceso: str):
    _requiere(PSUTIL_AVAILABLE, "psutil")
    cerrados = 0
    for p in psutil.process_iter(["name"]):
        try:
            if nombre_proceso.lower() in (p.info["name"] or "").lower():
                p.terminate()
                cerrados += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return cerrados

@skill("forzar_cierre_aplicacion", "aplicaciones", "Mata a la fuerza todos los procesos que coincidan con el nombre dado.", requiere=["psutil"])
def forzar_cierre_aplicacion(nombre_proceso: str):
    _requiere(PSUTIL_AVAILABLE, "psutil")
    matados = 0
    for p in psutil.process_iter(["name"]):
        try:
            if nombre_proceso.lower() in (p.info["name"] or "").lower():
                p.kill()
                matados += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matados

@skill("esta_aplicacion_abierta", "aplicaciones", "Comprueba si hay algún proceso corriendo con ese nombre.", requiere=["psutil"])
def esta_aplicacion_abierta(nombre_proceso: str) -> bool:
    _requiere(PSUTIL_AVAILABLE, "psutil")
    nombre_proceso = nombre_proceso.lower()
    return any(nombre_proceso in (p.info["name"] or "").lower()
               for p in psutil.process_iter(["name"]))

@skill("listar_procesos_en_ejecucion", "aplicaciones", "Lista los procesos activos con su PID y uso de memoria.", requiere=["psutil"])
def listar_procesos_en_ejecucion(limite: int = 30):
    _requiere(PSUTIL_AVAILABLE, "psutil")
    procesos = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            procesos.append({"pid": p.info["pid"], "nombre": p.info["name"],
                              "memoria_pct": round(p.info["memory_percent"] or 0, 2)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procesos.sort(key=lambda x: x["memoria_pct"], reverse=True)
    return procesos[:limite]

@skill("listar_aplicaciones_visibles", "aplicaciones", "Lista las aplicaciones con ventana visible (lo que el usuario ve en pantalla).", requiere=["pygetwindow"])
def listar_aplicaciones_visibles():
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    return sorted(set(w.title for w in gw.getAllWindows() if w.title.strip()))

@skill("esperar_a_que_abra_app", "aplicaciones", "Espera hasta 'timeout' segundos a que un proceso con ese nombre aparezca.", requiere=["psutil"])
def esperar_a_que_abra_app(nombre_proceso: str, timeout: float = 15.0, intervalo: float = 0.5):
    limite = time.time() + timeout
    while time.time() < limite:
        if esta_aplicacion_abierta(nombre_proceso):
            return True
        time.sleep(intervalo)
    raise TimeoutError(f"'{nombre_proceso}' no abrió en {timeout}s")

@skill("reiniciar_aplicacion", "aplicaciones", "Cierra y vuelve a abrir una aplicación (por nombre de proceso y ruta ejecutable).", requiere=["psutil"])
def reiniciar_aplicacion(nombre_proceso: str, ruta_ejecutable: str):
    forzar_cierre_aplicacion(nombre_proceso)
    time.sleep(1.0)
    return abrir_aplicacion(ruta_ejecutable)

@skill("obtener_uso_recursos_proceso", "aplicaciones", "Devuelve % de CPU y memoria usados por un proceso dado su nombre.", requiere=["psutil"])
def obtener_uso_recursos_proceso(nombre_proceso: str):
    _requiere(PSUTIL_AVAILABLE, "psutil")
    nombre_proceso = nombre_proceso.lower()
    for p in psutil.process_iter(["name"]):
        try:
            if nombre_proceso in (p.info["name"] or "").lower():
                return {"pid": p.pid, "cpu_pct": p.cpu_percent(interval=0.2),
                        "memoria_pct": round(p.memory_percent(), 2)}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise RuntimeError(f"Proceso '{nombre_proceso}' no encontrado")

@skill("verificar_aplicacion_instalada", "aplicaciones", "Comprueba si un ejecutable existe en el PATH del sistema.")
def verificar_aplicacion_instalada(nombre_ejecutable: str) -> bool:
    return shutil.which(nombre_ejecutable) is not None

@skill("obtener_ruta_ejecutable", "aplicaciones", "Devuelve la ruta completa de un ejecutable si está en el PATH.")
def obtener_ruta_ejecutable(nombre_ejecutable: str):
    ruta = shutil.which(nombre_ejecutable)
    if not ruta:
        raise RuntimeError(f"'{nombre_ejecutable}' no está en el PATH")
    return ruta
