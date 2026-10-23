"""
nova_skills/diagnostico.py — Detección y reacción ante errores.
====================================================================
Este módulo es el que le da a Nova la capacidad de 'darse cuenta'
cuando algo se rompe repetidamente y actuar en consecuencia, en vez
de solo tragarse la excepción una y otra vez. Se apoya en SaludSistema
(definida en _core.py), que ya lleva la cuenta de fallos por skill
cada vez que algo pasa por SkillRegistry.ejecutar().
"""

from typing import Optional
from ._core import skill, salud, SKILLS, SkillRegistry, logger
from .sistema import obtener_uso_cpu, obtener_uso_memoria, obtener_espacio_disco
from .red import verificar_conexion_internet

# Solo para armar el reporte de "qué falta instalar" — no se usan directo.
from . import raton, ventanas, aplicaciones, archivos, sistema as _sistema, portapapeles


@skill("diagnosticar_fallo", "diagnostico", "Devuelve cuántas veces falló una skill recientemente y si está inestable.")
def diagnosticar_fallo(nombre_skill: str):
    return {"skill": nombre_skill, "fallos_recientes": salud.resumen().get(nombre_skill, 0),
            "inestable": salud.esta_inestable(nombre_skill)}

@skill("obtener_resumen_salud", "diagnostico", "Devuelve un resumen de fallos recientes de todas las skills.")
def obtener_resumen_salud():
    return salud.resumen()

@skill("skill_esta_inestable", "diagnostico", "Indica si una skill superó el umbral de fallos recientes.")
def skill_esta_inestable(nombre_skill: str) -> bool:
    return salud.esta_inestable(nombre_skill)

@skill("reintentar_accion", "diagnostico", "Ejecuta otra skill con reintentos automáticos y backoff ante fallos.")
def reintentar_accion(nombre_skill: str, *args, intentos: int = 3, **kwargs):
    return SkillRegistry.ejecutar(nombre_skill, *args, reintentos=max(0, intentos - 1), **kwargs)

@skill("verificar_salud_general", "diagnostico", "Chequeo rápido de CPU, memoria, disco e internet — 'signos vitales' del PC.")
def verificar_salud_general():
    resultado = {}
    try:
        resultado["cpu_pct"] = obtener_uso_cpu()
    except Exception as e:
        resultado["cpu_pct"] = None; logger.exception(f"Fallo leyendo CPU: {e}")
    try:
        resultado["memoria_pct"] = obtener_uso_memoria()
    except Exception as e:
        resultado["memoria_pct"] = None; logger.exception(f"Fallo leyendo memoria: {e}")
    try:
        resultado["disco"] = obtener_espacio_disco()
    except Exception as e:
        resultado["disco"] = None; logger.exception(f"Fallo leyendo disco: {e}")
    resultado["internet"] = verificar_conexion_internet()
    return resultado

@skill("limpiar_registro_fallos", "diagnostico", "Reinicia el contador de fallos de una skill (o de todas) tras resolver el problema.")
def limpiar_registro_fallos(nombre_skill: Optional[str] = None):
    salud.limpiar(nombre_skill)
    return True

@skill("listar_skills_disponibles", "diagnostico", "Indica qué skills no pueden usarse porque falta una dependencia instalada.")
def listar_skills_disponibles():
    disponibilidad = {
        "pyautogui": raton.PYAUTOGUI_AVAILABLE,
        "pygetwindow": ventanas.PYGETWINDOW_AVAILABLE,
        "psutil": aplicaciones.PSUTIL_AVAILABLE,
        "pyperclip": portapapeles.PYPERCLIP_AVAILABLE,
        "screen_brightness_control": _sistema.BRIGHTNESS_AVAILABLE,
        "send2trash": archivos.SEND2TRASH_AVAILABLE,
    }
    faltantes = {}
    for nombre, s in SKILLS.items():
        for dep in s.requiere:
            if not disponibilidad.get(dep, True):
                faltantes.setdefault(dep, []).append(nombre)
    return faltantes
