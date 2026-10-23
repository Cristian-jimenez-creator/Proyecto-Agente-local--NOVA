"""
GestorAtencion.py — Atención limitada: un solo foco consciente por ciclo.
=========================================================================
Se enchufa en NucleoCognitivoExtendido._ciclo_extendido, junto a self.sueno
y self.identidad:

    from GestorAtencion import GestorAtencion
    self.atencion = GestorAtencion()
    ...
    # dentro del latido, ANTES de pasarle percepciones a razonamiento:
    percepciones_atendidas = self.atencion.enfocar(percepciones)
    pensamientos = self.razonamiento.razonar(percepciones_atendidas, intenciones_db)

Filosofía
---------
Sin esto, cada ciclo del latido le pasa a razonamiento/narrativa TODAS las
percepciones del ciclo por igual — si en un mismo instante llegan un
mensaje del usuario, un cambio de ventana activa y un reencuentro, Nova
"piensa" las tres cosas a la vez, con el mismo peso. Ninguna mente real
funciona así: la atención es selectiva por naturaleza, y esa selectividad
es justamente lo que le da consistencia narrativa (Nova habla de UNA cosa
por vez, no de un batiburrillo).

Este módulo NO filtra qué puede HACER Nova — Planificador, Predictor y
GeneradorDeMetas (en nova_mente_core.py) siguen recibiendo la lista
COMPLETA de percepciones tal cual, sin pasar por acá, así que ninguna
acción real queda bloqueada por esto. Lo único que se acota es qué entra a
razonamiento/narrativa: qué "piensa" y "narra" Nova en este ciclo.

Dos ideas centrales:

1. RESISTENCIA A FLICKEAR: si el foco actual sigue siendo relevante, un
   candidato nuevo apenas un poco más intenso NO lo desplaza — tiene que
   superarlo por un margen real (UMBRAL_MEJORA_PARA_CAMBIAR). Sin esto,
   con percepciones de intensidad parecida llegando seguido, el foco
   saltaría de una a otra en cada ciclo y Nova "narraría" de forma
   incoherente, cambiando de tema constantemente.

2. DESVANECIMIENTO SI NADA LO RENUEVA: un foco no dura para siempre. Si
   pasan SEGUNDOS_PARA_DESVANECER sin que vuelva a aparecer una percepción
   del mismo tipo, el foco se suelta solo (vuelve a None) — así el próximo
   candidato disponible puede tomar la posta en vez de que Nova se quede
   "pegada" mirando algo que ya dejó de pasar.
"""

import time
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova_mente_core import Percepcion


# =====================================================================
# PARÁMETROS
# =====================================================================

# Cuánto tiene que superar un candidato nuevo la intensidad del foco actual
# para desplazarlo. 0.15 en una escala de intensidad 0-1 es un margen real,
# no cualquier diferencia mínima cuenta.
UMBRAL_MEJORA_PARA_CAMBIAR = 0.15

# Si pasan más de estos segundos sin que vuelva a aparecer una percepción
# del mismo tipo que el foco actual, el foco se suelta solo.
SEGUNDOS_PARA_DESVANECER = 30.0

# Tipos de percepción que casi nunca vale la pena convertir en el foco
# consciente (son ruido de fondo, no algo sobre lo que Nova narre) — si
# aparecen junto con algo más, ese algo más gana por default salvo que
# el ruido de fondo tenga una intensidad desproporcionadamente alta.
TIPOS_BAJA_PRIORIDAD = {"latido_interno", "tick", "heartbeat"}


class GestorAtencion:
    def __init__(self):
        self._foco_tipo: Optional[str] = None
        self._foco_contenido: str = ""
        self._foco_intensidad: float = 0.0
        self._ultima_renovacion: float = 0.0

    # -----------------------------------------------------------------
    def enfocar(self, percepciones: List["Percepcion"]) -> List["Percepcion"]:
        """Llamar UNA vez por ciclo, con la lista completa de percepciones
        de ese ciclo. Devuelve una lista con COMO MUCHO una percepción — la
        que Nova va a 'pensar y narrar' este ciclo — o una lista vacía si
        no hay nada que amerite foco (ciclo tranquilo, o el foco anterior
        ya se desvaneció y nada nuevo lo reemplazó todavía)."""
        ahora = time.time()

        candidato = self._elegir_candidato(percepciones)

        if candidato is not None:
            if self._foco_tipo is None:
                self._asumir_foco(candidato, ahora)
            elif candidato.tipo == self._foco_tipo:
                # Lo mismo que ya estábamos mirando: se renueva sin más
                # trámite, no hace falta que "compita" contra sí mismo.
                self._asumir_foco(candidato, ahora)
            elif candidato.intensidad >= self._foco_intensidad + UMBRAL_MEJORA_PARA_CAMBIAR:
                # Un candidato distinto, pero lo bastante más importante
                # como para justificar el cambio de foco.
                self._asumir_foco(candidato, ahora)
            # si no superó el umbral, el foco actual se mantiene tal cual
            # (resistencia a flickear) — no tocamos nada acá.

        if self._foco_tipo is None:
            return []

        if (ahora - self._ultima_renovacion) > SEGUNDOS_PARA_DESVANECER:
            # Nadie renovó este foco en un buen rato: se suelta solo.
            self._soltar_foco()
            return []

        # Devolvemos SIEMPRE una Percepcion "fresca" con el foco actual,
        # aunque este ciclo no haya traído una nueva igual (para que
        # razonamiento pueda seguir narrando sobre algo activo mientras no
        # se desvanezca, no solo en el instante exacto en que llegó).
        from nova_mente_core import Percepcion  # import diferido: evita ciclo con nova_mente_core
        return [Percepcion(
            timestamp=ahora, tipo=self._foco_tipo, contenido=self._foco_contenido,
            intensidad=self._foco_intensidad, metadata={"foco_atencion": True},
        )]

    def foco_actual(self) -> Optional[str]:
        """El tipo de percepción en el que Nova está 'pensando' ahora
        mismo, o None si no hay ningún foco activo. Llamar después de
        enfocar() en el mismo ciclo para que el valor esté al día."""
        return self._foco_tipo

    # -----------------------------------------------------------------
    def _elegir_candidato(self, percepciones: List["Percepcion"]) -> Optional["Percepcion"]:
        if not percepciones:
            return None
        # Entre las percepciones de este ciclo, preferimos la de mayor
        # intensidad; a igualdad de intensidad, penalizamos los tipos de
        # baja prioridad (ruido de fondo) para que no le ganen a algo con
        # sentido narrativo real solo por casualidad de orden.
        return max(
            percepciones,
            key=lambda p: (p.intensidad, 0 if p.tipo in TIPOS_BAJA_PRIORIDAD else 1),
        )

    def _asumir_foco(self, percepcion: "Percepcion", ahora: float):
        self._foco_tipo = percepcion.tipo
        self._foco_contenido = percepcion.contenido
        self._foco_intensidad = percepcion.intensidad
        self._ultima_renovacion = ahora

    def _soltar_foco(self):
        self._foco_tipo = None
        self._foco_contenido = ""
        self._foco_intensidad = 0.0