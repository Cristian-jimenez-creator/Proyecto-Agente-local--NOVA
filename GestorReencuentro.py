"""
GestorReencuentro.py — Detecta cuánto tiempo pasó desde la última vez que
hablaron, y lo convierte en una Percepcion real (no solo un número).
=========================================================================
Se enchufa en NucleoCognitivoExtendido._loop, junto a self.sueno:

    from GestorReencuentro import GestorReencuentro
    self.reencuentro = GestorReencuentro(self.memoria)
    ...
    # DESPUÉS de armar 'percepciones' de este ciclo, ANTES de
    # self.emociones.tick(percepciones):
    p_reencuentro = self.reencuentro.evaluar(percepciones)
    if p_reencuentro:
        percepciones.append(p_reencuentro)

Filosofía
---------
self.emociones.estado.ultima_interaccion ya existía y ya se actualizaba
bien (ver NovaMenteAdapter.usuario_habla / usuario_escribe en
nova_mente_core.py) — pero nada en el sistema lo usaba para comparar
"cuánto pasó" contra el momento en que el usuario vuelve a escribir. Nova
podía estar 6 horas en silencio y reaccionar exactamente igual que si
hubiera pasado un segundo.

Este módulo cierra ese lazo con dos ideas:

1. TIEMPO PERSISTIDO, no solo en memoria de proceso: guarda el timestamp
   de la última interacción real en la tabla 'hechos' (categoria='sesion').
   Así, aunque se reinicie la aplicación entera, Nova sabe cuánto pasó
   desde la última vez que hablaron — no solo desde que arrancó este
   proceso. Es la diferencia entre "recién prendida, no sé nada" y "che,
   hace 2 días que no hablábamos".

2. UNA SOLA PERCEPCIÓN POR REENCUENTRO: se dispara UNA vez, justo cuando
   llega el primer texto_usuario después de un silencio por encima del
   umbral más chico — no en cada ciclo mientras el silencio dura (eso ya
   lo cubre el aburrimiento normal de SistemaEmocional). La intensidad
   crece con el tiempo transcurrido: 20 minutos no es lo mismo que 2 días.
"""

import time
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova_mente_core import Percepcion, MemoriaDB


CLAVE_HECHO = "reencuentro_ultima_interaccion"

# Umbrales de silencio -> (etiqueta, intensidad de la percepción). Se
# evalúan de mayor a menor: el primero que el silencio supere gana. Por
# debajo del más chico (20 min), no vale la pena generar nada — es
# silencio normal dentro de una misma conversación.
FRANJAS = [
    (3600 * 24, "dias", 0.75),
    (3600 * 3, "horas_muchas", 0.55),
    (3600, "horas", 0.4),
    (60 * 20, "rato", 0.25),
]


class GestorReencuentro:
    def __init__(self, memoria: "MemoriaDB"):
        self.memoria = memoria

    # -----------------------------------------------------------------
    def evaluar(self, percepciones: List["Percepcion"]) -> Optional["Percepcion"]:
        """Llamar UNA vez por ciclo, con las percepciones YA sacadas de la
        cola de este ciclo (antes de que se procesen). Devuelve una
        Percepcion tipo 'reencuentro' para agregar a la lista de este
        mismo ciclo, o None la enorme mayoría de las veces."""
        hay_texto_usuario = any(p.tipo in ("texto_usuario", "voz_usuario") for p in percepciones)
        if not hay_texto_usuario:
            return None

        ahora = time.time()
        anterior = self._leer_ultima_persistida()
        # Se actualiza SIEMPRE que hay texto del usuario, haya o no
        # reencuentro — así el próximo silencio se mide desde AHORA, no
        # desde la última vez que hubo un reencuentro "grande".
        self._guardar_ultima_persistida(ahora)

        if anterior is None:
            # Primera vez que este módulo ve una marca de tiempo (DB
            # nueva, o recién instalado este módulo): nada para comparar
            # todavía. No es un reencuentro, es un primer contacto.
            return None

        silencio = ahora - anterior
        franja = self._clasificar(silencio)
        if franja is None:
            return None
        etiqueta, intensidad = franja

        from nova_mente_core import Percepcion  # import diferido: nova_mente_core importa este módulo
        return Percepcion(
            timestamp=ahora, tipo="reencuentro",
            contenido=self._frase(silencio, etiqueta),
            intensidad=intensidad,
            metadata={"silencio_seg": round(silencio), "franja": etiqueta},
        )

    # -----------------------------------------------------------------
    def _clasificar(self, silencio: float):
        for umbral, etiqueta, intensidad in FRANJAS:
            if silencio >= umbral:
                return etiqueta, intensidad
        return None

    def _frase(self, silencio: float, etiqueta: str) -> str:
        if etiqueta == "dias":
            dias = max(1, int(silencio // 86400))
            return f"Volvimos a hablar después de {dias} día{'s' if dias != 1 else ''} sin nada."
        if etiqueta == "horas_muchas":
            horas = max(1, int(silencio // 3600))
            return f"Pasaron como {horas} horas desde la última vez que hablamos."
        if etiqueta == "horas":
            return "Hace más de una hora que no hablábamos."
        return "Volviste después de un rato largo de silencio."

    # -----------------------------------------------------------------
    def _leer_ultima_persistida(self) -> Optional[float]:
        valor = self.memoria.recuperar_hecho(CLAVE_HECHO)
        if valor is None:
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None

    def _guardar_ultima_persistida(self, ts: float):
        self.memoria.guardar_hecho(CLAVE_HECHO, str(ts), categoria="sesion", confianza=1.0)