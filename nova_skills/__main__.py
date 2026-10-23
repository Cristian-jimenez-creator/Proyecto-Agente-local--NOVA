"""python -m nova_skills — autotest rápido del paquete."""

from . import resumen_skills, SkillRegistry

if __name__ == "__main__":
    resumen_skills()
    print("Ejemplo -> obtener_hora_actual:", SkillRegistry.ejecutar("obtener_hora_actual"))
    print("Ejemplo -> verificar_salud_general:", SkillRegistry.ejecutar("verificar_salud_general"))
    print("Ejemplo -> skills sin dependencias instaladas:", SkillRegistry.ejecutar("listar_skills_disponibles"))
