"""

GestorSueno.py — Consolidación de memoria durante inactividad ("sueño").
=========================================================================
Se enchufa en NucleoCognitivoExtendido._loop, junto a self.metas:

    from GestorSueno import GestorSueno
    self.sueno = GestorSueno(self.memoria, self.emociones)
    ...
    reflexion = self.sueno.tick(percepciones)
    if reflexion:
        # nace un recuerdo nuevo, más compacto, hecho de otros más viejos
        ...

Filosofía
---------
Una mente que solo acumula recuerdos sin nunca reprocesarlos no se parece a
una mente viva: crece para siempre sin criterio, y nunca convierte
experiencia suelta en algo con forma ("ahora sé que..."). Este módulo hace
tres cosas, y las tres persiguen esa idea:

1. DETECTA inactividad real (nadie habló, no hay intención en curso) para
   no competir nunca con la atención "despierta" de Nova. El sueño ocurre
   SOLO cuando no hay nada más urgente pasando.

2. CONSOLIDA episodios recientes sin consolidar: agrupa los que se
   parecen (misma emoción + palabras en común dentro de una ventana de
   tiempo) en una sola 'reflexión' de más peso semántico — un recuerdo
   nuevo, nacido de varios viejos — y ajusta la importancia de los
   episodios sueltos que no se relacionaron con nada (probablemente no
   valía tanto la pena recordarlos con detalle).

3. DESCANSA de verdad: mientras dura la consolidación, la energía se
   recupera y el estrés/aburrimiento bajan un poco, en pasos chicos.
   Dormir, aunque sea una simulación, tiene que sentirse como descansar,
   no como otra tarea más en la lista.

Trabaja en pasos MUY chicos a propósito (un episodio por 'paso', un paso
cada COOLDOWN_ENTRE_CICLOS_SEG segundos): esto vive adentro del latido
cognitivo (_ciclo_extendido), que corre varias veces por segundo, así que
NUNCA puede bloquearlo con una consolidación pesada de una sola vez.
"""

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova_mente_core import Percepcion, MemoriaEpisodica, SistemaEmocional, MemoriaDBExtendida


# =====================================================================
# PARÁMETROS — ajustables sin tocar la lógica.
# =====================================================================

# Cuánto silencio real (sin hablar, sin intención en curso) hace falta
# para que Nova empiece a "dormir". 4 minutos es un default razonable
# para uso normal; bajalo si querés ver el sueño funcionando rápido en
# una prueba.
UMBRAL_INACTIVIDAD_SEG = 240

# No re-evaluar el estado de sueño ni hacer trabajo de consolidación más
# seguido que esto. Es lo que mantiene el costo de este módulo cercano a
# cero dentro de un latido que corre a varios Hz.
COOLDOWN_ENTRE_PASOS_SEG = 8

# Con menos episodios relacionados que este número, no vale la pena
# convertirlos en una reflexión — es más ruido que patrón.
MIN_EPISODIOS_PARA_REFLEXION = 3

# Ventana de tiempo hacia atrás en la que se buscan episodios
# "relacionados" con el que se está revisando ahora.
VENTANA_RELACION_SEG = 3600 * 6  # 6 horas

# Cuánto se recupera/baja el estado emocional en cada paso de sueño.
# Chico a propósito: varios pasos seguidos (dormir un rato largo) son
# los que hacen que se note de verdad.
RECUPERO_ENERGIA_POR_PASO = 0.01
BAJA_ESTRES_POR_PASO = 0.015
BAJA_ABURRIMIENTO_POR_PASO = 0.01


@dataclass
class Reflexion:
    """Una reflexión es un recuerdo nuevo, nacido de consolidar varios
    episodios parecidos en uno solo con más peso. No reemplaza a los
    episodios originales (siguen en 'episodios', ya marcados como
    consolidados) — los resume."""
    contenido: str
    categoria: str  # 'patron' por ahora; deja lugar para 'emocional', 'aprendizaje', etc.
    importancia: float
    episodios_fuente: List[str] = field(default_factory=list)


class GestorSueno:
    def __init__(self, memoria: "MemoriaDBExtendida", emociones: "SistemaEmocional"):
        self.memoria = memoria
        self.emociones = emociones
        self._durmiendo = False
        self._ultimo_paso = 0.0
        self._inicio_sueno_actual = 0.0
        self._episodios_pendientes: List["MemoriaEpisodica"] = []

    # -----------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------
    def tick(self, percepciones: List["Percepcion"]) -> Optional[Reflexion]:
        """Llamar UNA vez por ciclo del latido cognitivo. Devuelve una
        Reflexion recién nacida si este paso terminó de construir una
        (para que quien llame la guarde como episodio, la mande a
        NarrativaInterna, o la loguee), o None la enorme mayoría de las
        veces — que es lo esperado."""
        ahora = time.time()

        if self._hay_actividad_reciente(percepciones, ahora):
            if self._durmiendo:
                self._despertar()
            return None

        if ahora - self._ultimo_paso < COOLDOWN_ENTRE_PASOS_SEG:
            return None
        self._ultimo_paso = ahora

        if not self._durmiendo:
            self._dormir()

        return self._paso_de_consolidacion(ahora)

    def esta_durmiendo(self) -> bool:
        return self._durmiendo

    def tiempo_durmiendo(self) -> float:
        return (time.time() - self._inicio_sueno_actual) if self._durmiendo else 0.0

    def episodios_pendientes(self) -> int:
        return len(self._episodios_pendientes)

    # -----------------------------------------------------------------
    # Detección de actividad / transición dormir-despertar
    # -----------------------------------------------------------------
    def _hay_actividad_reciente(self, percepciones: List["Percepcion"], ahora: float) -> bool:
        if any(p.tipo in ("texto_usuario", "voz_usuario") for p in percepciones):
            return True
        silencio = ahora - self.emociones.estado.ultima_interaccion
        return silencio < UMBRAL_INACTIVIDAD_SEG

    def _dormir(self):
        self._durmiendo = True
        self._inicio_sueno_actual = time.time()
        try:
            self._episodios_pendientes = self.memoria.recuperar_episodios_no_consolidados(limite=200)
        except Exception as e:
            print(f"[SUEÑO] Error cargando episodios para consolidar: {e}")
            self._episodios_pendientes = []
        print(f"[SUEÑO] Nova entra en reposo. {len(self._episodios_pendientes)} episodios por revisar.")

    def _despertar(self):
        if self._durmiendo:
            print("[SUEÑO] Nova vuelve a estar alerta.")
        self._durmiendo = False
        self._episodios_pendientes = []

    # -----------------------------------------------------------------
    # El trabajo real, en pasos chicos
    # -----------------------------------------------------------------
    def _paso_de_consolidacion(self, ahora: float) -> Optional[Reflexion]:
        # Descansar de verdad, incluso si no queda nada para consolidar
        # todavía (o ya se terminó de revisar todo por ahora).
        estado = self.emociones.estado
        estado.energia = min(1.0, estado.energia + RECUPERO_ENERGIA_POR_PASO)
        estado.estres = max(0.0, estado.estres - BAJA_ESTRES_POR_PASO)
        estado.aburrimiento = max(0.0, estado.aburrimiento - BAJA_ABURRIMIENTO_POR_PASO)

        if not self._episodios_pendientes:
            return None

        # Un episodio por paso, nunca más: esto corre adentro del latido
        # rápido y no puede volverse el cuello de botella del sistema.
        episodio = self._episodios_pendientes.pop(0)

        try:
            relacionados = self._buscar_relacionados(episodio)
        except Exception as e:
            print(f"[SUEÑO] Error buscando relacionados: {e}")
            relacionados = []

        if len(relacionados) + 1 < MIN_EPISODIOS_PARA_REFLEXION:
            # Evento aislado: no se repitió ni se relacionó con nada más
            # en la ventana reciente. Bajamos un poco su importancia (es
            # una señal débil de que no era tan relevante) y seguimos.
            try:
                self.memoria.marcar_episodio_consolidado(episodio.id)
                self.memoria.ajustar_importancia_episodio(episodio.id, delta=-0.05)
            except Exception as e:
                print(f"[SUEÑO] Error marcando episodio aislado: {e}")
            return None

        grupo = [episodio] + relacionados
        reflexion = self._construir_reflexion(grupo)

        try:
            self.memoria.guardar_hecho(
                clave=f"reflexion_{int(ahora * 1000)}",
                valor=reflexion.contenido,
                categoria="reflexion_onirica",
                confianza=min(1.0, 0.4 + 0.1 * len(grupo)),
            )
            for ep in grupo:
                self.memoria.marcar_episodio_consolidado(ep.id)
                self.memoria.ajustar_importancia_episodio(ep.id, delta=+0.1)
        except Exception as e:
            print(f"[SUEÑO] Error guardando reflexión: {e}")

        # No reintentar estos mismos episodios en lo que queda de este sueño.
        ids_grupo = {ep.id for ep in grupo}
        self._episodios_pendientes = [e for e in self._episodios_pendientes if e.id not in ids_grupo]

        return reflexion

    def _buscar_relacionados(self, episodio: "MemoriaEpisodica") -> List["MemoriaEpisodica"]:
        """Relación simple y barata a propósito: misma emoción + palabras
        en común en el texto del evento, dentro de una ventana de tiempo.
        Si el proyecto ya tiene MemoriaVectorial (Chroma) activa, esto es
        un buen lugar para reemplazar este método por una búsqueda
        semántica real más adelante — acá queda el fallback liviano que
        funciona siempre, sin depender de Ollama ni de Chroma."""
        candidatos = self.memoria.recuperar_episodios(
            desde=episodio.timestamp - VENTANA_RELACION_SEG, limite=100
        )
        palabras_ep = set(episodio.evento.lower().split())
        relacionados = []
        for c in candidatos:
            if c.id == episodio.id:
                continue
            mismo_animo = c.emocion == episodio.emocion
            palabras_c = set(c.evento.lower().split())
            comparten_palabras = len(palabras_ep & palabras_c) >= 2
            if mismo_animo and comparten_palabras:
                relacionados.append(c)
        return relacionados[:6]

    def _construir_reflexion(self, grupo: List["MemoriaEpisodica"]) -> Reflexion:
        emociones_grupo = Counter(ep.emocion for ep in grupo)
        emocion_predominante = emociones_grupo.most_common(1)[0][0]
        eventos = [ep.evento for ep in grupo]
        resumen = eventos[0]
        if len(eventos) > 1:
            resumen += f" (y {len(eventos) - 1} eventos parecidos más)"
        contenido = (
            f"Me di cuenta de un patrón: {resumen}. "
            f"La mayoría de las veces que pasó esto me sentí {emocion_predominante.lower()}."
        )
        importancia = min(1.0, 0.3 + 0.08 * len(grupo))
        return Reflexion(
            contenido=contenido,
            categoria="patron",
            importancia=importancia,
            episodios_fuente=[ep.id for ep in grupo],
        )