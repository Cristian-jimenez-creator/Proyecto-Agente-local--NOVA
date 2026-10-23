"""
nova_autonomia.py — Metas propias + capa de permisos para EJECUTAR_TAREA.
====================================================================
Se enchufa en NucleoCognitivoExtendido._loop, junto a self.predictor.

    from nova_autonomia import GeneradorDeMetas, NivelAutonomia
    self.metas = GeneradorDeMetas(self.memoria, self.emociones)
    ...
    intenciones_metas = self.metas.generar(contexto, percepciones)
    for i in intenciones_metas:
        self.memoria.guardar_intencion(i)

Y en Ejecutor._ejecutar_tarea, ANTES de llamar al actuador 'skill':

    if not NivelAutonomia.permitida(nombre_skill):
        # en vez de ejecutar, generar una intención PREGUNTAR pidiendo
        # confirmación al usuario, y no tocar nada todavía.
        ...
"""

import time
from dataclasses import dataclass
from typing import List, Dict, Set, TYPE_CHECKING

# OJO: nova_mente_core importa este módulo, así que NO podemos importar
# nova_mente_core acá arriba (import circular). Intencion/IntencionTipo se
# importan recién dentro de las funciones que los necesitan, cuando
# nova_mente_core ya terminó de cargar sus propias clases.
if TYPE_CHECKING:
    from nova_mente_core import Intencion, Percepcion


# =====================================================================
# NIVEL DE AUTONOMÍA — qué puede hacer Nova SIN pedir permiso primero.
# =====================================================================
# Filosofía: cuanto más difícil de deshacer o más "hacia afuera" del
# equipo de Nova sea la acción, más alto el nivel requerido. Ajustable
# por el usuario (ej. desde un archivo de config), pero el default es
# conservador a propósito: mejor que Nova pregunte de más al principio
# a que borre algo sin avisar.

# Nivel 1 — Nova puede hacerlas sola, sin avisar antes (son de solo-lectura
# o triviales de deshacer): diagnóstico, lectura de archivos/estado.
AUTONOMAS_LIBRES: Set[str] = {
    "obtener_uso_cpu", "obtener_uso_memoria", "obtener_espacio_disco",
    "obtener_hora_actual", "obtener_info_sistema", "obtener_bateria",
    "listar_procesos_en_ejecucion", "listar_aplicaciones_visibles",
    "listar_ventanas", "obtener_ventana_activa", "verificar_conexion_internet",
    "diagnosticar_fallo", "obtener_resumen_salud", "verificar_salud_general",
    "listar_archivos", "buscar_archivo", "archivo_existe", "carpeta_existe",
    "obtener_portapapeles",
}

# Nivel 2 — Nova puede hacerlas sola pero DEJA REGISTRO explícito
# (episodio de memoria + aviso no bloqueante) para que el usuario pueda
# revisar/deshacer después. Ninguna es destructiva de forma permanente.
AUTONOMAS_CON_AVISO: Set[str] = {
    "limpiar_archivos_temporales",   # solo archivos viejos, y va a una carpeta conocida
    "organizar_carpeta_por_tipo",
    "mover_a_papelera",              # reversible: es papelera, no borrado permanente
    "crear_carpeta", "crear_archivo",
    "copiar_archivo",
    "ajustar_brillo",
    "limpiar_registro_fallos",
}

# Todo lo que NO está en los dos sets de arriba requiere confirmación
# explícita del usuario antes de ejecutarse. Esto incluye, entre otras:
# eliminar_archivo, eliminar_carpeta, forzar_cierre_aplicacion,
# apagar_pc, reiniciar_pc, click/arrastrar en cualquier lugar de la
# pantalla, escribir_texto, combinacion_teclas, cerrar_aplicacion.


class NivelAutonomia:
    @staticmethod
    def clasificar(nombre_skill: str) -> str:
        if nombre_skill in AUTONOMAS_LIBRES:
            return "libre"
        if nombre_skill in AUTONOMAS_CON_AVISO:
            return "con_aviso"
        return "requiere_confirmacion"

    @staticmethod
    def permitida_sin_preguntar(nombre_skill: str) -> bool:
        return NivelAutonomia.clasificar(nombre_skill) in ("libre", "con_aviso")


# =====================================================================
# GENERADOR DE METAS — produce EJECUTAR_TAREA reales, no solo charla.
# =====================================================================

@dataclass
class Meta:
    """Una meta propia de más largo aliento que una Intención puntual.
    Vive en memoria (tabla 'hechos', categoria='meta_activa') para que
    sobreviva a un reinicio: si Nova 'quería' terminar de organizar la
    carpeta de Descargas, sigue queriéndolo al arrancar de nuevo."""
    nombre: str
    skill: str
    args: list
    kwargs: dict
    motivo: str
    prioridad: float
    cooldown: float = 300.0  # no repetir la misma meta antes de N segundos


class GeneradorDeMetas:
    def __init__(self, memoria, emociones):
        self.memoria = memoria
        self.emociones = emociones
        self._ultima_vez: Dict[str, float] = {}

    def _lista_para(self, ahora: float, nombre: str, cooldown: float) -> bool:
        return (ahora - self._ultima_vez.get(nombre, 0)) >= cooldown

    def generar(self, contexto: dict, percepciones: List["Percepcion"]) -> List["Intencion"]:
        """Convierte 'estado del mundo + estado interno' en intenciones
        EJECUTAR_TAREA concretas. Cada una es una meta que Nova decidió
        perseguir por su cuenta, no una respuesta a una orden."""
        from nova_mente_core import Intencion, IntencionTipo
        ahora = time.time()
        estado = self.emociones.estado
        intenciones = []

        # --- Mantenimiento propio: disco casi lleno ---------------------
        # Requiere que 'contexto' traiga 'disco' (ver verificar_salud_general).
        disco = contexto.get("disco")
        if disco and disco.get("pct_usado", 0) > 90 and self._lista_para(ahora, "limpieza_disco", 1800):
            intenciones.append(self._meta_a_intencion(
                Meta("limpieza_disco", "limpiar_archivos_temporales",
                     [contexto.get("carpeta_temp", "")], {"dias": 14},
                     motivo="Disco por encima del 90% de uso", prioridad=0.5)
            ))
            self._ultima_vez["limpieza_disco"] = ahora

        # --- Curiosidad/aburrimiento alto y mucho rato sin novedades ----
        # Esto es lo más parecido a un 'impulso propio' real: no lo pidió
        # el usuario ni lo dispara ningún evento externo, nace del estado
        # interno de Nova.
        if estado.curiosidad > 0.75 and estado.aburrimiento > 0.6 and self._lista_para(ahora, "explorar", 600):
            intenciones.append(Intencion(
                id=f"meta_explorar_{int(ahora*1000)}",
                tipo=IntencionTipo.EXPLORAR_PANTALLA,
                descripcion="Impulso propio: tengo curiosidad por ver qué está pasando en pantalla",
                prioridad=0.35, creada_en=ahora,
                metadata={"origen": "meta_propia", "motivo": "curiosidad_alta"}
            ))
            self._ultima_vez["explorar"] = ahora

        # --- Skill inestable detectada por diagnostico.py ---------------
        # Si SaludSistema marca una skill como inestable, generar una meta
        # de bajo impacto: limpiar su registro de fallos DESPUÉS de que el
        # usuario confirme que ya la revisó (no auto-limpiar en silencio,
        # eso ocultaría el problema real).
        # (Este bloque es deliberadamente un ejemplo de meta que SÍ debe
        # pasar por confirmación, aunque "limpiar_registro_fallos" esté en
        # el set libre — la decisión de cuándo es distinta a la de cómo.)

        return intenciones

    def _meta_a_intencion(self, meta: Meta) -> "Intencion":
        from nova_mente_core import Intencion, IntencionTipo
        return Intencion(
            id=f"meta_{meta.nombre}_{int(time.time()*1000)}",
            tipo=IntencionTipo.EJECUTAR_TAREA,
            descripcion=f"Meta propia: {meta.motivo}",
            prioridad=meta.prioridad,
            creada_en=time.time(),
            metadata={
                "skill": meta.skill, "args": meta.args, "kwargs": meta.kwargs,
                "origen": "meta_propia", "motivo": meta.motivo,
            }
        )