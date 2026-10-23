"""
nova_skills/_core.py — Núcleo del sistema de habilidades de Nova.
====================================================================
Contiene el registro de skills, el decorador @skill, el manejo de
salud/errores (SaludSistema) y el punto único de ejecución
(SkillRegistry). Los módulos de categoría (raton.py, teclado.py,
ventanas.py, etc.) importan de acá y se auto-registran al ser
importados por nova_skills/__init__.py.

Ningún módulo de categoría debería reimplementar nada de esto: si
necesitás una función nueva de infraestructura común (por ejemplo,
otra forma de reintentar), agregala acá para que todas las skills
se beneficien por igual.
"""

import os
import sys
import time
import threading
import platform
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Dict

# ==========================
# LOGGING — junto a los demás logs de Nova (nova_asistente.log,
# nova_vision.log), un nivel arriba de este paquete.
# ==========================
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_PACKAGE_DIR)
LOG_DIR = os.path.join(_PROJECT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "nova_skills.log")

logger = logging.getLogger("nova_skills")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
    ))
    _console_handler = logging.StreamHandler(stream=sys.stdout)
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter("[SKILLS] %(message)s"))
    logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)
    logger.propagate = False

IS_WINDOWS = platform.system() == "Windows"


# =====================================================================
# REGISTRO DE SKILLS
# =====================================================================

@dataclass
class Skill:
    nombre: str
    categoria: str
    descripcion: str
    fn: Callable
    requiere: List[str] = field(default_factory=list)   # nombres de libs necesarias


SKILLS: Dict[str, Skill] = {}


def skill(nombre: str, categoria: str, descripcion: str, requiere: Optional[List[str]] = None):
    """Decorador: registra una función como habilidad fundamental de Nova."""
    def _wrap(fn):
        if nombre in SKILLS:
            logger.warning(
                f"[SKILLS] Skill '{nombre}' redefinida "
                f"(categoría previa: {SKILLS[nombre].categoria}, nueva: {categoria})"
            )
        SKILLS[nombre] = Skill(nombre, categoria, descripcion, fn, requiere or [])
        return fn
    return _wrap


def _requiere(flag: bool, libreria: str):
    """Lanza un error claro si falta una dependencia opcional, en vez de
    dejar que la skill reviente con un NameError/AttributeError críptico."""
    if not flag:
        raise RuntimeError(f"Dependencia '{libreria}' no instalada. Instálala con: pip install {libreria}")


# =====================================================================
# SALUD DEL SISTEMA — DETECCIÓN Y REACCIÓN ANTE ERRORES
# =====================================================================

class SaludSistema:
    """
    Lleva la cuenta de fallos por skill dentro de una ventana de tiempo.
    Esto es lo que le permite a Nova 'darse cuenta' de que algo se está
    rompiendo repetidamente (en vez de solo tragarse el error una y otra
    vez) y reaccionar: avisar al usuario, dejar de intentar esa acción,
    o escalar el problema a mente_core.
    """
    def __init__(self, max_fallos_ventana: int = 3, ventana_segundos: float = 60.0):
        self._fallos: Dict[str, list] = {}
        self._lock = threading.Lock()
        self.max_fallos_ventana = max_fallos_ventana
        self.ventana_segundos = ventana_segundos
        self._callback_inestabilidad: Optional[Callable[[str, int], None]] = None

    def on_inestabilidad(self, callback: Callable[[str, int], None]):
        """Registra un callback(nombre_skill, n_fallos) llamado cuando una
        skill se vuelve inestable. mente_core puede engancharse acá."""
        self._callback_inestabilidad = callback

    def registrar_fallo(self, nombre_skill: str, error: Exception) -> int:
        with self._lock:
            ahora = time.time()
            hist = self._fallos.setdefault(nombre_skill, [])
            hist[:] = [t for t in hist if ahora - t < self.ventana_segundos]
            hist.append(ahora)
            n = len(hist)
        logger.exception(f"[SALUD] Fallo en skill '{nombre_skill}' (#{n} en {self.ventana_segundos:.0f}s): {error}")
        if n >= self.max_fallos_ventana and self._callback_inestabilidad:
            try:
                self._callback_inestabilidad(nombre_skill, n)
            except Exception:
                logger.exception("Excepcion silenciada en callback de inestabilidad")
        return n

    def registrar_exito(self, nombre_skill: str):
        # Un éxito no borra el historial (así se ve la tendencia real),
        # pero deja la puerta abierta a lógica futura (p.ej. decaimiento).
        pass

    def esta_inestable(self, nombre_skill: str) -> bool:
        with self._lock:
            return len(self._fallos.get(nombre_skill, [])) >= self.max_fallos_ventana

    def resumen(self) -> Dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._fallos.items() if v}

    def limpiar(self, nombre_skill: Optional[str] = None):
        with self._lock:
            if nombre_skill:
                self._fallos.pop(nombre_skill, None)
            else:
                self._fallos.clear()


salud = SaludSistema()


class SkillRegistry:
    """Punto único de ejecución: toda skill pasa por acá. Da manejo de
    errores uniforme, reintentos con backoff y contabilidad de salud."""

    @staticmethod
    def ejecutar(nombre_skill: str, *args, reintentos: int = 0, backoff: float = 0.3, **kwargs) -> dict:
        s = SKILLS.get(nombre_skill)
        if not s:
            return {"ok": False, "resultado": None, "error": f"Skill '{nombre_skill}' no existe"}

        intentos_totales = max(1, reintentos + 1)
        ultimo_error = None
        for intento in range(intentos_totales):
            try:
                resultado = s.fn(*args, **kwargs)
                salud.registrar_exito(nombre_skill)
                return {"ok": True, "resultado": resultado, "error": None, "intentos": intento + 1}
            except Exception as e:
                ultimo_error = f"{type(e).__name__}: {e}"
                salud.registrar_fallo(nombre_skill, e)
                if intento < intentos_totales - 1:
                    time.sleep(backoff * (intento + 1))
        return {"ok": False, "resultado": None, "error": ultimo_error, "intentos": intentos_totales}

    @staticmethod
    def listar(categoria: Optional[str] = None) -> List[str]:
        if categoria:
            return sorted(s.nombre for s in SKILLS.values() if s.categoria == categoria)
        return sorted(SKILLS.keys())

    @staticmethod
    def categorias() -> List[str]:
        return sorted(set(s.categoria for s in SKILLS.values()))

    @staticmethod
    def describir(nombre_skill: str) -> Optional[str]:
        s = SKILLS.get(nombre_skill)
        return s.descripcion if s else None

    @staticmethod
    def total() -> int:
        return len(SKILLS)
