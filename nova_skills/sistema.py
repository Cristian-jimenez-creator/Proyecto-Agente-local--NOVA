"""
nova_skills/sistema.py — Estado y control del sistema operativo.
"""

import ctypes
import platform
import subprocess
from datetime import datetime
from ._core import skill, _requiere, logger, IS_WINDOWS

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception as e:
    PSUTIL_AVAILABLE = False
    logger.debug(f"[SKILLS] psutil no disponible en sistema.py ({e})")

try:
    import screen_brightness_control as sbc
    BRIGHTNESS_AVAILABLE = True
except Exception as e:
    BRIGHTNESS_AVAILABLE = False
    logger.debug(f"[SKILLS] screen_brightness_control no disponible en sistema.py ({e})")


@skill("obtener_uso_cpu", "sistema", "Devuelve el porcentaje de uso actual de CPU.", requiere=["psutil"])
def obtener_uso_cpu() -> float:
    _requiere(PSUTIL_AVAILABLE, "psutil")
    return psutil.cpu_percent(interval=0.5)

@skill("obtener_uso_memoria", "sistema", "Devuelve el porcentaje de uso actual de memoria RAM.", requiere=["psutil"])
def obtener_uso_memoria() -> float:
    _requiere(PSUTIL_AVAILABLE, "psutil")
    return psutil.virtual_memory().percent

@skill("obtener_espacio_disco", "sistema", "Devuelve espacio total/usado/libre (GB) de una unidad, ej: 'C:\\\\'.", requiere=["psutil"])
def obtener_espacio_disco(unidad: str = "C:\\"):
    _requiere(PSUTIL_AVAILABLE, "psutil")
    u = psutil.disk_usage(unidad)
    gb = 1024 ** 3
    return {"total_gb": round(u.total / gb, 1), "usado_gb": round(u.used / gb, 1),
            "libre_gb": round(u.free / gb, 1), "pct_usado": u.percent}

@skill("obtener_hora_actual", "sistema", "Devuelve la fecha y hora actuales del sistema.")
def obtener_hora_actual():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@skill("obtener_info_sistema", "sistema", "Devuelve resumen del SO, versión, arquitectura y nombre de equipo.")
def obtener_info_sistema():
    return {"so": platform.system(), "version": platform.version(),
            "arquitectura": platform.machine(), "equipo": platform.node(),
            "procesador": platform.processor()}

@skill("obtener_bateria", "sistema", "Devuelve el porcentaje de batería y si está cargando (si el equipo tiene batería).", requiere=["psutil"])
def obtener_bateria():
    _requiere(PSUTIL_AVAILABLE, "psutil")
    b = psutil.sensors_battery()
    if b is None:
        raise RuntimeError("Este equipo no reporta información de batería")
    return {"porcentaje": b.percent, "cargando": b.power_plugged}

@skill("apagar_pc", "sistema", "Apaga el equipo tras N segundos (por defecto inmediato).")
def apagar_pc(segundos: int = 0):
    if not IS_WINDOWS:
        raise RuntimeError("apagar_pc solo está implementado para Windows")
    subprocess.run(f"shutdown /s /t {segundos}", shell=True, check=True)
    return True

@skill("reiniciar_pc", "sistema", "Reinicia el equipo tras N segundos (por defecto inmediato).")
def reiniciar_pc(segundos: int = 0):
    if not IS_WINDOWS:
        raise RuntimeError("reiniciar_pc solo está implementado para Windows")
    subprocess.run(f"shutdown /r /t {segundos}", shell=True, check=True)
    return True

@skill("cancelar_apagado", "sistema", "Cancela un apagado/reinicio previamente programado.")
def cancelar_apagado():
    if not IS_WINDOWS:
        raise RuntimeError("cancelar_apagado solo está implementado para Windows")
    subprocess.run("shutdown /a", shell=True, check=True)
    return True

@skill("suspender_pc", "sistema", "Pone el equipo en modo suspensión.")
def suspender_pc():
    if not IS_WINDOWS:
        raise RuntimeError("suspender_pc solo está implementado para Windows")
    subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True, check=True)
    return True

@skill("bloquear_pantalla", "sistema", "Bloquea la sesión de Windows inmediatamente.")
def bloquear_pantalla():
    if not IS_WINDOWS:
        raise RuntimeError("bloquear_pantalla solo está implementado para Windows")
    ctypes.windll.user32.LockWorkStation()
    return True

@skill("ajustar_brillo", "sistema", "Ajusta el brillo de pantalla a un porcentaje (0-100).", requiere=["screen_brightness_control"])
def ajustar_brillo(porcentaje: int):
    _requiere(BRIGHTNESS_AVAILABLE, "screen_brightness_control")
    porcentaje = max(0, min(100, porcentaje))
    sbc.set_brightness(porcentaje)
    return porcentaje

@skill("obtener_brillo", "sistema", "Obtiene el nivel de brillo actual de pantalla (0-100).", requiere=["screen_brightness_control"])
def obtener_brillo():
    _requiere(BRIGHTNESS_AVAILABLE, "screen_brightness_control")
    return sbc.get_brightness()[0]

@skill("listar_unidades_conectadas", "sistema", "Lista las unidades de disco/almacenamiento conectadas.", requiere=["psutil"])
def listar_unidades_conectadas():
    _requiere(PSUTIL_AVAILABLE, "psutil")
    return [{"dispositivo": p.device, "punto_montaje": p.mountpoint, "sistema_archivos": p.fstype}
            for p in psutil.disk_partitions()]
