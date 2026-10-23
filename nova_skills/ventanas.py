"""
nova_skills/ventanas.py — Reconocimiento y manejo de múltiples ventanas.
====================================================================
Otro ejemplo de skill "engordada" de verdad:

  - enfocar_ventana() no se conforma con que w.activate() no haya
    tirado excepción — en Windows, SetForegroundWindow puede negar
    silenciosamente el cambio de foco si Nova no tenía el foco previo.
    Por eso VERIFICA que la ventana objetivo terminó siendo la activa,
    y si no, prueba una estrategia alterna (Alt+Tab) antes de rendirse.
  - cerrar_ventana_por_titulo() espera y confirma que la ventana
    realmente desapareció, en vez de asumir que w.close() funcionó
    (muchas apps interceptan el cierre con un diálogo de "guardar
    cambios", y ahí w.close() "tuvo éxito" pero la ventana sigue ahí).
"""

import time
from ._core import skill, _requiere, logger

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except Exception as e:
    PYGETWINDOW_AVAILABLE = False
    logger.debug(f"[SKILLS] pygetwindow no disponible en ventanas.py ({e})")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


def _obtener_ventana(titulo_parcial: str):
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    titulo_parcial = titulo_parcial.lower()
    for w in gw.getAllWindows():
        if w.title and titulo_parcial in w.title.lower():
            return w
    return None


@skill("listar_ventanas", "ventanas", "Lista todas las ventanas abiertas (título y si están minimizadas/activas).", requiere=["pygetwindow"])
def listar_ventanas():
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    return [
        {"titulo": w.title, "activa": w.isActive, "minimizada": w.isMinimized,
         "x": w.left, "y": w.top, "ancho": w.width, "alto": w.height}
        for w in gw.getAllWindows() if w.title
    ]

@skill("obtener_ventana_activa", "ventanas", "Devuelve el título y geometría de la ventana en primer plano.", requiere=["pygetwindow"])
def obtener_ventana_activa():
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    w = gw.getActiveWindow()
    if not w:
        return None
    return {"titulo": w.title, "x": w.left, "y": w.top, "ancho": w.width, "alto": w.height}

@skill("enfocar_ventana", "ventanas",
       "Trae al frente una ventana por título parcial y VERIFICA que "
       "realmente quedó activa; si Windows le niega el foco, reintenta "
       "con Alt+Tab como estrategia alterna antes de rendirse.", requiere=["pygetwindow"])
def enfocar_ventana(titulo_parcial: str, intentos: int = 3):
    w = _obtener_ventana(titulo_parcial)
    if not w:
        raise RuntimeError(f"No se encontró ninguna ventana con título que contenga '{titulo_parcial}'")

    objetivo = titulo_parcial.lower()
    for intento in range(1, intentos + 1):
        if w.isMinimized:
            w.restore()
        try:
            w.activate()
        except Exception as e:
            logger.debug(f"[VENTANAS] w.activate() falló en intento {intento}: {e}")

        time.sleep(0.2)
        activa = gw.getActiveWindow()
        if activa and objetivo in activa.title.lower():
            return {"titulo": w.title, "confirmado": True, "intentos": intento}

        if PYAUTOGUI_AVAILABLE and intento < intentos:
            logger.debug(f"[VENTANAS] '{titulo_parcial}' no quedó en primer plano, probando Alt+Tab (intento {intento})")
            pyautogui.keyDown("alt"); pyautogui.press("tab"); pyautogui.keyUp("alt")
            time.sleep(0.3)

    return {"titulo": w.title, "confirmado": False, "intentos": intentos}

@skill("cerrar_ventana_activa", "ventanas", "Cierra la ventana actualmente en primer plano (Alt+F4).", requiere=["pyautogui"])
def cerrar_ventana_activa():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.hotkey("alt", "f4")
    return True

@skill("cerrar_ventana_por_titulo", "ventanas",
       "Cierra la ventana con ese título y CONFIRMA que desapareció "
       "(algunas apps interceptan el cierre con un diálogo de 'guardar cambios').", requiere=["pygetwindow"])
def cerrar_ventana_por_titulo(titulo_parcial: str, timeout: float = 5.0):
    w = _obtener_ventana(titulo_parcial)
    if not w:
        raise RuntimeError(f"No se encontró ventana '{titulo_parcial}'")
    w.close()

    limite = time.time() + timeout
    while time.time() < limite:
        if not _obtener_ventana(titulo_parcial):
            return {"cerrada": True}
        time.sleep(0.3)

    logger.debug(f"[VENTANAS] '{titulo_parcial}' seguía existiendo tras cerrar; probablemente pide confirmación")
    return {"cerrada": False, "aviso": "La ventana sigue abierta; puede estar pidiendo confirmación (ej. guardar cambios)"}

@skill("minimizar_ventana", "ventanas", "Minimiza una ventana por título (o la activa si no se especifica).", requiere=["pygetwindow"])
def minimizar_ventana(titulo_parcial=None):
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    w = _obtener_ventana(titulo_parcial) if titulo_parcial else gw.getActiveWindow()
    if not w:
        raise RuntimeError("Ventana no encontrada")
    w.minimize()
    return True

@skill("maximizar_ventana", "ventanas", "Maximiza una ventana por título (o la activa si no se especifica).", requiere=["pygetwindow"])
def maximizar_ventana(titulo_parcial=None):
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    w = _obtener_ventana(titulo_parcial) if titulo_parcial else gw.getActiveWindow()
    if not w:
        raise RuntimeError("Ventana no encontrada")
    w.maximize()
    return True

@skill("restaurar_ventana", "ventanas", "Restaura una ventana minimizada/maximizada a su tamaño normal.", requiere=["pygetwindow"])
def restaurar_ventana(titulo_parcial=None):
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    w = _obtener_ventana(titulo_parcial) if titulo_parcial else gw.getActiveWindow()
    if not w:
        raise RuntimeError("Ventana no encontrada")
    w.restore()
    return True

@skill("mover_ventana", "ventanas", "Mueve una ventana a la posición (x, y) de la pantalla.", requiere=["pygetwindow"])
def mover_ventana(titulo_parcial: str, x: int, y: int):
    w = _obtener_ventana(titulo_parcial)
    if not w:
        raise RuntimeError(f"No se encontró ventana '{titulo_parcial}'")
    w.moveTo(x, y)
    return True

@skill("redimensionar_ventana", "ventanas", "Cambia el tamaño de una ventana (ancho x alto).", requiere=["pygetwindow"])
def redimensionar_ventana(titulo_parcial: str, ancho: int, alto: int):
    w = _obtener_ventana(titulo_parcial)
    if not w:
        raise RuntimeError(f"No se encontró ventana '{titulo_parcial}'")
    w.resizeTo(ancho, alto)
    return True

@skill("centrar_ventana", "ventanas", "Centra una ventana en la pantalla principal.", requiere=["pyautogui", "pygetwindow"])
def centrar_ventana(titulo_parcial: str):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    w = _obtener_ventana(titulo_parcial)
    if not w:
        raise RuntimeError(f"No se encontró ventana '{titulo_parcial}'")
    sw, sh = pyautogui.size()
    w.moveTo(max(0, (sw - w.width) // 2), max(0, (sh - w.height) // 2))
    return True

@skill("ventana_existe", "ventanas", "Comprueba si existe alguna ventana con ese título parcial.", requiere=["pygetwindow"])
def ventana_existe(titulo_parcial: str) -> bool:
    return _obtener_ventana(titulo_parcial) is not None

@skill("esperar_ventana", "ventanas", "Espera hasta 'timeout' segundos a que aparezca una ventana con ese título.", requiere=["pygetwindow"])
def esperar_ventana(titulo_parcial: str, timeout: float = 10.0, intervalo: float = 0.5):
    limite = time.time() + timeout
    while time.time() < limite:
        w = _obtener_ventana(titulo_parcial)
        if w:
            return w.title
        time.sleep(intervalo)
    raise TimeoutError(f"La ventana '{titulo_parcial}' no apareció en {timeout}s")

@skill("organizar_ventanas_mosaico", "ventanas", "Coloca dos ventanas lado a lado (Win+izq/der) para trabajar con ambas a la vez.", requiere=["pyautogui", "pygetwindow"])
def organizar_ventanas_mosaico(titulo_izq: str, titulo_der: str):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    w1 = _obtener_ventana(titulo_izq)
    w2 = _obtener_ventana(titulo_der)
    if not w1 or not w2:
        raise RuntimeError("No se encontraron ambas ventanas para organizar en mosaico")
    w1.activate(); pyautogui.hotkey("win", "left")
    w2.activate(); pyautogui.hotkey("win", "right")
    return True

@skill("alternar_pantalla_completa", "ventanas", "F11 — alterna pantalla completa en la app activa (navegadores, reproductores).", requiere=["pyautogui"])
def alternar_pantalla_completa():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.press("f11")
    return True

@skill("contar_ventanas_abiertas", "ventanas", "Cuenta cuántas ventanas con título visible hay abiertas.", requiere=["pygetwindow"])
def contar_ventanas_abiertas() -> int:
    _requiere(PYGETWINDOW_AVAILABLE, "pygetwindow")
    return len([w for w in gw.getAllWindows() if w.title.strip()])
