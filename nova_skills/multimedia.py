"""
nova_skills/multimedia.py — Control de reproducción y volumen.
"""

from ._core import skill, _requiere, logger

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception as e:
    PYAUTOGUI_AVAILABLE = False
    logger.debug(f"[SKILLS] pyautogui no disponible en multimedia.py ({e})")


@skill("reproducir_pausar", "multimedia", "Play/Pausa de la reproducción multimedia activa.", requiere=["pyautogui"])
def reproducir_pausar():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.press("playpause")
    return True

@skill("siguiente_pista", "multimedia", "Avanza a la siguiente pista/canción.", requiere=["pyautogui"])
def siguiente_pista():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.press("nexttrack")
    return True

@skill("pista_anterior", "multimedia", "Vuelve a la pista/canción anterior.", requiere=["pyautogui"])
def pista_anterior():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.press("prevtrack")
    return True

@skill("subir_volumen", "multimedia", "Sube el volumen del sistema N pasos.", requiere=["pyautogui"])
def subir_volumen(pasos: int = 5):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    for _ in range(pasos):
        pyautogui.press("volumeup")
    return pasos

@skill("bajar_volumen", "multimedia", "Baja el volumen del sistema N pasos.", requiere=["pyautogui"])
def bajar_volumen(pasos: int = 5):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    for _ in range(pasos):
        pyautogui.press("volumedown")
    return pasos

@skill("silenciar_multimedia", "multimedia", "Activa/desactiva el silencio general del sistema.", requiere=["pyautogui"])
def silenciar_multimedia():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.press("volumemute")
    return True
