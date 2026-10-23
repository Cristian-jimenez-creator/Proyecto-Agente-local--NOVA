"""
nova_skills/teclado.py — Habilidades de teclado: tecleo y combinaciones
estándar de navegación (pestañas, deshacer, guardar, etc.).
"""

from ._core import skill, _requiere, logger

try:
    import pyautogui
    pyautogui.PAUSE = 0.02
    PYAUTOGUI_AVAILABLE = True
except Exception as e:
    PYAUTOGUI_AVAILABLE = False
    logger.debug(f"[SKILLS] pyautogui no disponible en teclado.py ({e})")


@skill("escribir_texto", "teclado", "Escribe texto simulando pulsaciones de teclado.", requiere=["pyautogui"])
def escribir_texto(texto: str, intervalo: float = 0.02):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.write(texto, interval=intervalo)
    return len(texto)

@skill("presionar_tecla", "teclado", "Presiona una sola tecla (ej: 'enter', 'esc', 'f5', 'tab').", requiere=["pyautogui"])
def presionar_tecla(tecla: str, veces: int = 1):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    for _ in range(veces):
        pyautogui.press(tecla)
    return tecla

@skill("combinacion_teclas", "teclado", "Presiona una combinación de teclas simultáneas (ej: 'ctrl','shift','esc').", requiere=["pyautogui"])
def combinacion_teclas(*teclas: str):
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.hotkey(*teclas)
    return teclas

@skill("copiar", "teclado", "Ctrl+C — copia la selección actual.", requiere=["pyautogui"])
def copiar():
    return combinacion_teclas("ctrl", "c")

@skill("pegar", "teclado", "Ctrl+V — pega el contenido del portapapeles.", requiere=["pyautogui"])
def pegar():
    return combinacion_teclas("ctrl", "v")

@skill("cortar", "teclado", "Ctrl+X — corta la selección actual.", requiere=["pyautogui"])
def cortar():
    return combinacion_teclas("ctrl", "x")

@skill("seleccionar_todo", "teclado", "Ctrl+A — selecciona todo el contenido.", requiere=["pyautogui"])
def seleccionar_todo():
    return combinacion_teclas("ctrl", "a")

@skill("deshacer", "teclado", "Ctrl+Z — deshace la última acción.", requiere=["pyautogui"])
def deshacer():
    return combinacion_teclas("ctrl", "z")

@skill("rehacer", "teclado", "Ctrl+Y — rehace la última acción deshecha.", requiere=["pyautogui"])
def rehacer():
    return combinacion_teclas("ctrl", "y")

@skill("guardar_documento", "teclado", "Ctrl+S — guarda el documento/archivo activo.", requiere=["pyautogui"])
def guardar_documento():
    return combinacion_teclas("ctrl", "s")

@skill("buscar_en_pantalla", "teclado", "Ctrl+F — abre el buscador dentro de la app activa.", requiere=["pyautogui"])
def buscar_en_pantalla():
    return combinacion_teclas("ctrl", "f")

@skill("nueva_pestana", "teclado", "Ctrl+T — abre una nueva pestaña (navegador/editor).", requiere=["pyautogui"])
def nueva_pestana():
    return combinacion_teclas("ctrl", "t")

@skill("cerrar_pestana", "teclado", "Ctrl+W — cierra la pestaña activa.", requiere=["pyautogui"])
def cerrar_pestana():
    return combinacion_teclas("ctrl", "w")

@skill("reabrir_pestana_cerrada", "teclado", "Ctrl+Shift+T — reabre la última pestaña cerrada.", requiere=["pyautogui"])
def reabrir_pestana_cerrada():
    return combinacion_teclas("ctrl", "shift", "t")

@skill("cambiar_pestana_siguiente", "teclado", "Ctrl+Tab — pasa a la siguiente pestaña.", requiere=["pyautogui"])
def cambiar_pestana_siguiente():
    return combinacion_teclas("ctrl", "tab")

@skill("cambiar_pestana_anterior", "teclado", "Ctrl+Shift+Tab — pasa a la pestaña anterior.", requiere=["pyautogui"])
def cambiar_pestana_anterior():
    return combinacion_teclas("ctrl", "shift", "tab")

@skill("alt_tab", "teclado", "Alt+Tab — cambia a la siguiente ventana abierta.", requiere=["pyautogui"])
def alt_tab():
    _requiere(PYAUTOGUI_AVAILABLE, "pyautogui")
    pyautogui.keyDown("alt")
    pyautogui.press("tab")
    pyautogui.keyUp("alt")
    return True

@skill("mostrar_escritorio", "teclado", "Win+D — muestra el escritorio (minimiza todo).", requiere=["pyautogui"])
def mostrar_escritorio():
    return combinacion_teclas("win", "d")

@skill("minimizar_todo", "teclado", "Win+M — minimiza todas las ventanas.", requiere=["pyautogui"])
def minimizar_todo():
    return combinacion_teclas("win", "m")

@skill("abrir_buscador_windows", "teclado", "Win — abre el menú/buscador de inicio de Windows.", requiere=["pyautogui"])
def abrir_buscador_windows():
    return presionar_tecla("win")

@skill("capturar_pantalla_recorte", "teclado", "Win+Shift+S — abre la herramienta de recorte de pantalla.", requiere=["pyautogui"])
def capturar_pantalla_recorte():
    return combinacion_teclas("win", "shift", "s")

@skill("bloquear_pantalla_atajo", "teclado", "Win+L — bloquea la pantalla mediante atajo de teclado.", requiere=["pyautogui"])
def bloquear_pantalla_atajo():
    return combinacion_teclas("win", "l")
