"""
nova_skills/raton.py — Habilidades de mouse.
====================================================================
Acá es donde se nota la diferencia entre "una skill delgada" y "una
skill que de verdad sabe si funcionó":

  - click() / doble_click() toman una micro-captura de pantalla
    ALREDEDOR del punto de clic, antes y después, y comparan si hubo
    cambio visual. pyautogui.click() nunca lanza una excepción aunque
    el clic haya caído en el vacío — esta verificación es la única
    forma real de saber si "pasó algo". Si no detecta cambio, reintenta
    una vez con un jitter de 2px (el clic pudo caer justo en el borde
    de un botón).
  - mover_mouse() / click() validan que la posición pedida esté
    realmente dentro de la resolución de pantalla, en vez de dejar
    que pyautogui mueva el cursor a un lugar sin sentido en silencio.
  - arrastrar() confirma que el cursor efectivamente llegó al punto
    de origen antes de iniciar el drag (a veces el movimiento inicial
    se corta por foco perdido u otra ventana tapando el punto).
"""

import time
from ._core import skill, _requiere, logger

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02
    PYAUTOGUI_AVAILABLE = True
except Exception as e:
    # No solo ImportError: en entornos sin pantalla (headless/servidor sin
    # DISPLAY) pyautogui puede fallar con otro tipo de excepción al intentar
    # inicializar el subsistema de mouse. Cualquier falla acá significa
    # "no disponible", nunca debe tumbar el import del módulo.
    PYAUTOGUI_AVAILABLE = False
    logger.debug(f"[SKILLS] pyautogui no disponible en raton.py ({e})")

try:
    from PIL import ImageGrab
    import numpy as np
    _CAPTURA_DISPONIBLE = True
except Exception:
    _CAPTURA_DISPONIBLE = False


def _capturar_region(x: int, y: int, radio: int = 25):
    """Micro-captura alrededor de un punto, usada para detectar cambio
    visual tras un clic. Devuelve None si no se pudo capturar (headless,
    permisos, etc.) — en ese caso simplemente no se verifica, no se falla."""
    if not _CAPTURA_DISPONIBLE or not PYAUTOGUI_AVAILABLE:
        return None
    try:
        sw, sh = pyautogui.size()
        x1, y1 = max(0, x - radio), max(0, y - radio)
        x2, y2 = min(sw, x + radio), min(sh, y + radio)
        return np.array(ImageGrab.grab(bbox=(x1, y1, x2, y2)), dtype=np.float32)
    except Exception:
        return None


def _hubo_cambio_visual(antes, despues, umbral: float = 3.0):
    """None = no se pudo verificar. True/False = sí hubo comparación real."""
    if antes is None or despues is None or antes.shape != despues.shape:
        return None
    diff = float(np.mean(np.abs(antes - despues)))
    return diff > umbral


def _dentro_de_pantalla(x: int, y: int) -> bool:
    sw, sh = pyautogui.size()
    return 0 <= x < sw and 0 <= y < sh


@skill("mover_mouse", "raton", "Mueve el cursor a (x, y) de forma suave, validando que la posición esté dentro de la pantalla.", requiere=["pyautogui"])
def mover_mouse(x: int, y: int, duracion: float = 0.2):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    if not _dentro_de_pantalla(x, y):
        sw, sh = pyautogui.size()
        raise ValueError(f"({x},{y}) está fuera de la resolución de pantalla ({sw}x{sh})")
    pyautogui.moveTo(x, y, duration=duracion)
    return {"x": x, "y": y}

@skill("mover_mouse_relativo", "raton", "Mueve el cursor de forma relativa a su posición actual.", requiere=["pyautogui"])
def mover_mouse_relativo(dx: int, dy: int, duracion: float = 0.15):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.moveRel(dx, dy, duration=duracion)
    p = pyautogui.position()
    return {"x": p.x, "y": p.y}

@skill("click", "raton",
       "Hace clic en (x, y) y VERIFICA con una micro-captura de pantalla que "
       "algo cambió visualmente; si no detecta cambio, reintenta una vez con "
       "un pequeño ajuste antes de darse por vencido.", requiere=["pyautogui"])
def click(x=None, y=None, boton: str = "left", clics: int = 1, verificar: bool = True):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    if x is None or y is None:
        pos = pyautogui.position()
        x, y = pos.x, pos.y
    if not _dentro_de_pantalla(x, y):
        sw, sh = pyautogui.size()
        raise ValueError(f"({x},{y}) está fuera de la resolución de pantalla ({sw}x{sh})")

    antes = _capturar_region(x, y) if verificar else None
    pyautogui.click(x=x, y=y, button=boton, clicks=clics, interval=0.05)

    if not verificar or antes is None:
        return {"click_en": (x, y), "cambio_detectado": None}

    time.sleep(0.15)
    despues = _capturar_region(x, y)
    cambio = _hubo_cambio_visual(antes, despues)

    if cambio is False:
        logger.debug(f"[RATON] click en ({x},{y}) sin cambio visual detectado, reintentando con jitter de 2px")
        pyautogui.click(x=x + 2, y=y + 2, button=boton, clicks=clics, interval=0.05)
        time.sleep(0.15)
        despues2 = _capturar_region(x, y)
        cambio = _hubo_cambio_visual(antes, despues2)

    return {"click_en": (x, y), "cambio_detectado": cambio}

@skill("doble_click", "raton", "Doble clic verificado con micro-captura de pantalla (mismo mecanismo que click()).", requiere=["pyautogui"])
def doble_click(x=None, y=None, verificar: bool = True):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    if x is None or y is None:
        pos = pyautogui.position()
        x, y = pos.x, pos.y
    antes = _capturar_region(x, y) if verificar else None
    pyautogui.doubleClick(x=x, y=y)
    if not verificar or antes is None:
        return {"click_en": (x, y), "cambio_detectado": None}
    time.sleep(0.15)
    despues = _capturar_region(x, y)
    return {"click_en": (x, y), "cambio_detectado": _hubo_cambio_visual(antes, despues)}

@skill("click_derecho", "raton", "Clic derecho (abre menú contextual) en (x, y) o en posición actual.", requiere=["pyautogui"])
def click_derecho(x=None, y=None):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.rightClick(x=x, y=y)
    return True

@skill("click_medio", "raton", "Clic con el botón central del mouse.", requiere=["pyautogui"])
def click_medio(x=None, y=None):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.middleClick(x=x, y=y)
    return True

@skill("mantener_click", "raton", "Presiona y mantiene el botón del mouse sin soltarlo (para iniciar un arrastre manual).", requiere=["pyautogui"])
def mantener_click(x=None, y=None, boton: str = "left"):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    if x is not None and y is not None:
        pyautogui.moveTo(x, y)
    pyautogui.mouseDown(button=boton)
    return True

@skill("soltar_click", "raton", "Suelta el botón del mouse previamente mantenido.", requiere=["pyautogui"])
def soltar_click(boton: str = "left"):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.mouseUp(button=boton)
    return True

@skill("arrastrar", "raton",
       "Arrastra desde (x1,y1) hasta (x2,y2), CONFIRMANDO que el cursor "
       "efectivamente llegó al punto de origen antes de iniciar el drag "
       "(evita arrastres 'fantasma' cuando el movimiento inicial se corta).", requiere=["pyautogui"])
def arrastrar(x1: int, y1: int, x2: int, y2: int, duracion: float = 0.4):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.moveTo(x1, y1, duration=0.15)
    pos = pyautogui.position()
    if abs(pos.x - x1) > 3 or abs(pos.y - y1) > 3:
        raise RuntimeError(f"El cursor no llegó al punto de origen esperado ({x1},{y1}); quedó en ({pos.x},{pos.y})")
    pyautogui.dragTo(x2, y2, duration=duracion, button="left")
    return True

@skill("arrastrar_y_soltar", "raton", "Alias semántico de arrastrar: drag and drop de un punto a otro.", requiere=["pyautogui"])
def arrastrar_y_soltar(x1: int, y1: int, x2: int, y2: int, duracion: float = 0.4):
    return arrastrar(x1, y1, x2, y2, duracion)

@skill("scroll", "raton", "Hace scroll vertical; positivo sube, negativo baja.", requiere=["pyautogui"])
def scroll(cantidad: int):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.scroll(cantidad)
    return cantidad

@skill("scroll_arriba", "raton", "Scroll hacia arriba N clics.", requiere=["pyautogui"])
def scroll_arriba(cantidad: int = 5):
    return scroll(abs(cantidad))

@skill("scroll_abajo", "raton", "Scroll hacia abajo N clics.", requiere=["pyautogui"])
def scroll_abajo(cantidad: int = 5):
    return scroll(-abs(cantidad))

@skill("scroll_horizontal", "raton", "Scroll horizontal; positivo derecha, negativo izquierda.", requiere=["pyautogui"])
def scroll_horizontal(cantidad: int):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.hscroll(cantidad)
    return cantidad

@skill("obtener_posicion_mouse", "raton", "Devuelve la posición actual (x, y) del cursor.", requiere=["pyautogui"])
def obtener_posicion_mouse():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    p = pyautogui.position()
    return {"x": p.x, "y": p.y}

@skill("hover", "raton", "Coloca el cursor sobre (x, y) y lo mantiene quieto N segundos (para activar tooltips/menús).", requiere=["pyautogui"])
def hover(x: int, y: int, segundos: float = 1.0):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(segundos)
    return True
