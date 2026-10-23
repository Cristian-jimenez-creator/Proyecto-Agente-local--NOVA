"""
nova_skills/portapapeles.py — Lectura y escritura del portapapeles.
"""

from ._core import skill, _requiere, logger

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except Exception as e:
    PYPERCLIP_AVAILABLE = False
    logger.debug(f"[SKILLS] pyperclip no disponible en portapapeles.py ({e})")


@skill("copiar_al_portapapeles", "portapapeles", "Coloca un texto directamente en el portapapeles del sistema.", requiere=["pyperclip"])
def copiar_al_portapapeles(texto: str):
    _requiere(PYPERCLIP_AVAILABLE, "pyperclip")
    pyperclip.copy(texto)
    return texto

@skill("obtener_portapapeles", "portapapeles", "Lee el contenido de texto actual del portapapeles.", requiere=["pyperclip"])
def obtener_portapapeles():
    _requiere(PYPERCLIP_AVAILABLE, "pyperclip")
    return pyperclip.paste()

@skill("limpiar_portapapeles", "portapapeles", "Vacía el contenido del portapapeles.", requiere=["pyperclip"])
def limpiar_portapapeles():
    _requiere(PYPERCLIP_AVAILABLE, "pyperclip")
    pyperclip.copy("")
    return True

@skill("agregar_al_portapapeles", "portapapeles", "Agrega texto al final de lo que ya hay en el portapapeles.", requiere=["pyperclip"])
def agregar_al_portapapeles(texto: str):
    _requiere(PYPERCLIP_AVAILABLE, "pyperclip")
    actual = pyperclip.paste()
    pyperclip.copy(actual + texto)
    return actual + texto
