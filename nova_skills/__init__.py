"""
nova_skills — Paquete de habilidades fundamentales de Nova.
====================================================================
Organizado por CATEGORÍA (un archivo por categoría, no por skill
individual — ver _core.py para la justificación de esa decisión):

    raton.py         teclado.py        ventanas.py
    aplicaciones.py  archivos.py       sistema.py
    red.py           portapapeles.py   multimedia.py
    diagnostico.py

Uso típico:

    from nova_skills import SkillRegistry

    resultado = SkillRegistry.ejecutar("enfocar_ventana", "Chrome")
    if resultado["ok"]:
        print("Listo:", resultado["resultado"])
    else:
        print("Falló:", resultado["error"])

Importar este paquete dispara el auto-registro de todas las skills de
todos los módulos de categoría (se importan más abajo únicamente por
su efecto secundario de registro vía el decorador @skill).
"""
from . import documentos

from ._core import (
    Skill, SKILLS, skill, SaludSistema, salud, SkillRegistry,
    _requiere, logger, IS_WINDOWS,
)

# Los imports de abajo existen solo para disparar el registro de skills
# de cada categoría. No hace falta usar estos módulos directamente desde
# afuera: todo se consulta a través de SkillRegistry.
from . import raton
from . import teclado
from . import ventanas
from . import aplicaciones
from . import archivos
from . import sistema
from . import red
from . import portapapeles
from . import multimedia
from . import diagnostico

__all__ = [
    "Skill", "SKILLS", "skill", "SaludSistema", "salud", "SkillRegistry",
    "IS_WINDOWS", "resumen_skills",
]


def resumen_skills():
    """Imprime cuántas skills hay registradas por categoría. Útil para
    verificar rápidamente que el paquete cargó bien."""
    print(f"\n[NOVA SKILLS] Total de habilidades registradas: {SkillRegistry.total()}\n")
    for cat in SkillRegistry.categorias():
        nombres = SkillRegistry.listar(cat)
        print(f"  · {cat:14s} ({len(nombres):2d}): {', '.join(nombres)}")
    print()
