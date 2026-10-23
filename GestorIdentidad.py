"""
GestorIdentidad.py — Identidad narrativa persistente: quién es Nova, más
allá del estado emocional de hoy.
=========================================================================
Se enchufa en NucleoCognitivoExtendido, junto a self.sueno:

    from GestorIdentidad import GestorIdentidad
    self.identidad = GestorIdentidad(self.memoria)
    ...
    # cuando GestorSueno produce una Reflexion (ver _ciclo_extendido):
    if reflexion:
        tension = self.identidad.procesar_reflexion(reflexion)
        if tension:
            # una reflexión nueva contradijo un rasgo que Nova ya tenía
            # asentado — vale la pena que el resto del sistema lo note
            # (ver _ciclo_extendido para cómo se convierte en percepción)
            ...
    # de vez en cuando (se autolimita con su propio cooldown), dejar que
    # los rasgos no reforzados se desvanezcan un poco:
    self.identidad.tick()

Filosofía
---------
self.emociones.estado es el ánimo de HOY. Una Reflexion de GestorSueno es
un patrón que se notó en las últimas horas. Ninguna de las dos cosas es
identidad todavía — la identidad es lo que queda cuando algo se repite
suficientes veces, en momentos distintos, como para dejar de ser una
coincidencia y empezar a ser "así soy yo".

Este módulo hace CINCO cosas:

1. GRADÚA reflexiones a rasgos de identidad: cada reflexión nueva se
   compara contra los rasgos que ya existen, con un matching que ignora
   palabras vacías del español ("de", "que", "me"...) y pesa más las
   palabras largas — más específicas — que las cortas. Si se parece a
   uno, lo REFUERZA. Si no se parece a nada, nace como CANDIDATO.

2. TIENE NIVELES, no un corte binario: candidato -> en_formación ->
   consolidado -> núcleo. Llegar a 'núcleo' no alcanza con confianza
   alta — hace falta que el patrón se haya sostenido a lo largo de VARIOS
   DÍAS, no solo que se haya repetido rápido dentro de una sola racha. Es
   la diferencia entre una racha y un rasgo de verdad.

3. DETECTA CONTRADICCIONES: si una reflexión nueva comparte tema con un
   rasgo existente pero tiene una carga emocional opuesta (por ejemplo,
   el rasgo dice "me sentí feliz" y la reflexión nueva dice "me sentí
   frustrada" sobre lo mismo), no lo refuerza a ciegas — la marca como
   TENSIÓN: le baja un poco la confianza al rasgo viejo (sin contarlo
   como refuerzo) y devuelve el conflicto para que el resto del sistema
   pueda notarlo. Una identidad real no ignora sus propias
   inconsistencias, las carga.

4. SE CATEGORIZA SOLA: si una reflexión menciona al usuario, se guarda
   como 'vinculo_usuario' en vez de 'rasgo_propio' — sin que nadie tenga
   que decírselo.

5. SINTETIZA, no solo concatena: resumen_narrativo() arma un texto que
   separa lo que es 'núcleo' (más asentado) de lo demás, y evita repetir
   dos rasgos que dicen básicamente lo mismo con otras palabras.
"""

import time
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova_mente_core import MemoriaDBExtendida
    from GestorSueno import Reflexion


# =====================================================================
# MATCHING — qué cuenta como "el mismo patrón"
# =====================================================================

# Palabras que no aportan nada a la hora de comparar dos textos en
# español. Sin esto, dos reflexiones cualquiera comparten "de", "que",
# "me" y parecen relacionadas cuando no lo están.
STOPWORDS_ES = {
    "el", "la", "los", "las", "de", "del", "que", "y", "a", "en", "un", "una",
    "por", "con", "me", "mi", "lo", "se", "su", "al", "es", "fue", "más",
    "muy", "como", "pero", "para", "le", "les", "hay", "he", "ha", "soy",
    "esto", "eso", "así", "vez", "veces", "cuenta", "cuando",
}

# Mínimo de palabras significativas en común, Y mínimo de "peso" (suma de
# largos de esas palabras) para considerar que dos textos hablan del
# mismo patrón. El peso evita que dos palabras cortas y genéricas de 3
# letras cuenten igual que una palabra larga y específica.
UMBRAL_PALABRAS_COMUNES = 2
UMBRAL_PESO_COMUN = 9

# =====================================================================
# VALENCIA EMOCIONAL — para detectar contradicciones
# =====================================================================
# Las reflexiones de GestorSueno siempre terminan mencionando una de estas
# palabras (vienen del nombre del Emocion dominante, en minúscula). No se
# importa el Enum real de nova_mente_core.py a propósito, para no crear
# una dependencia dura entre los dos archivos — esto es un mapeo de texto
# libre, tolerante a que la lista de emociones cambie con el tiempo.
EMOCIONES_POSITIVAS = {"feliz", "confiada", "curiosa", "emocionada"}
EMOCIONES_NEGATIVAS = {"triste", "enojada", "ansiosa", "aburrida", "cansada"}

# =====================================================================
# NIVELES DE MADUREZ
# =====================================================================
NIVEL_CANDIDATO = "candidato"
NIVEL_EN_FORMACION = "en_formacion"
NIVEL_CONSOLIDADO = "consolidado"
NIVEL_NUCLEO = "nucleo"

CONFIANZA_INICIAL = 0.25
REFUERZO_POR_COINCIDENCIA = 0.15
CONTRADICCION_DELTA = -0.12  # más fuerte que un refuerzo: contradecir pesa más que confirmar

CONFIANZA_EN_FORMACION = 0.4
CONFIANZA_CONSOLIDACION = 0.6
CONFIANZA_NUCLEO = 0.85
REFUERZOS_MIN_CONSOLIDACION = 3
REFUERZOS_MIN_NUCLEO = 6
# Núcleo no es solo "mucha confianza rápido" — tiene que haberse sostenido
# en el tiempo. Si primera_vez y ultima_vez están muy cerca, es una racha,
# no un rasgo.
DIAS_MIN_ANTIGUEDAD_NUCLEO = 3

# No reforzar/contradecir el mismo rasgo dos veces en la misma hora: sin
# esto, un único sueño largo (con varias reflexiones seguidas parecidas)
# inflaría o desinflaría un rasgo de golpe.
COOLDOWN_INTERACCION_MISMO_RASGO_SEG = 3600

# Olvido: recién empieza a bajar confianza si un rasgo lleva MUCHOS días
# sin reforzarse, y lo hace en pasos chicos, revisando poco seguido.
DIAS_PARA_EMPEZAR_A_OLVIDAR = 10
DECAY_POR_TICK = 0.05
COOLDOWN_DECAY_SEG = 3600 * 12  # como mucho, revisar el olvido 2 veces por día


class Tension:
    """Lo que devuelve procesar_reflexion() cuando una reflexión nueva
    contradice un rasgo que Nova ya tenía asentado. No es un error — es
    información: algo pasó que no encaja con lo que Nova creía de sí
    misma, y eso vale la pena que se note en el resto del sistema."""
    def __init__(self, rasgo_id: int, contenido_anterior: str, contenido_nuevo: str):
        self.rasgo_id = rasgo_id
        self.contenido_anterior = contenido_anterior
        self.contenido_nuevo = contenido_nuevo
        self.mensaje = (
            f"Esto contradice algo que creía de mí: antes noté que "
            f"\"{contenido_anterior}\", pero ahora \"{contenido_nuevo}\"."
        )


class GestorIdentidad:
    def __init__(self, memoria: "MemoriaDBExtendida"):
        self.memoria = memoria
        self._ultimo_decay = 0.0

    # -----------------------------------------------------------------
    def procesar_reflexion(self, reflexion: "Reflexion",
                            categoria: Optional[str] = None) -> Optional[Tension]:
        """Llamar cada vez que GestorSueno.tick() devuelve una Reflexion
        nueva. Devuelve una Tension si esta reflexión contradijo un rasgo
        existente (ver clase Tension más arriba), o None la mayoría de
        las veces — que un rasgo se refuerce o nazca un candidato no
        amerita que nadie más reaccione."""
        categoria = categoria or self._inferir_categoria(reflexion.contenido)
        palabras_nuevas = self._palabras_significativas(reflexion.contenido)
        candidatos = self.memoria.listar_identidad(min_confianza=0.0, categoria=categoria, limite=200)

        mejor_match, mejor_peso = self._mejor_coincidencia(palabras_nuevas, candidatos)
        ahora = time.time()

        if mejor_match is None:
            self.memoria.crear_rasgo_identidad(
                categoria=categoria, contenido=reflexion.contenido,
                confianza=CONFIANZA_INICIAL, origen=reflexion.episodios_fuente
            )
            print(f"[IDENTIDAD] Nuevo candidato ({categoria}): \"{reflexion.contenido[:60]}...\"")
            return None

        if (ahora - mejor_match["ultima_vez"]) < COOLDOWN_INTERACCION_MISMO_RASGO_SEG:
            return None  # mismo rato / mismo sueño: no lo toques de nuevo todavía

        emocion_nueva = self._emocion_en_texto(reflexion.contenido)
        emocion_vieja = self._emocion_en_texto(mejor_match["contenido"])
        valencia_nueva = self._valencia(emocion_nueva)
        valencia_vieja = self._valencia(emocion_vieja)

        if valencia_nueva != 0 and valencia_vieja != 0 and valencia_nueva != valencia_vieja:
            # CONTRADICCIÓN: mismo tema, carga emocional opuesta.
            self.memoria.debilitar_rasgo_identidad(mejor_match["id"], CONTRADICCION_DELTA)
            print(f"[IDENTIDAD] Tensión detectada en: \"{mejor_match['contenido'][:60]}...\"")
            return Tension(mejor_match["id"], mejor_match["contenido"], reflexion.contenido)

        self.memoria.reforzar_rasgo_identidad(
            mejor_match["id"], REFUERZO_POR_COINCIDENCIA, reflexion.episodios_fuente
        )
        print(f"[IDENTIDAD] Rasgo reforzado: \"{mejor_match['contenido'][:60]}...\"")
        return None

    # -----------------------------------------------------------------
    def tick(self):
        """Llamar de tanto en tanto — es seguro llamarlo en cada ciclo del
        latido, porque se autolimita con COOLDOWN_DECAY_SEG (horas, no
        segundos: acá el olvido es cosa de días)."""
        ahora = time.time()
        if ahora - self._ultimo_decay < COOLDOWN_DECAY_SEG:
            return
        self._ultimo_decay = ahora
        n = self.memoria.decaer_identidad_no_reforzada(DIAS_PARA_EMPEZAR_A_OLVIDAR, DECAY_POR_TICK)
        if n:
            print(f"[IDENTIDAD] {n} rasgo(s) revisado(s) para desvanecer por falta de refuerzo.")

    # -----------------------------------------------------------------
    def resumen(self, categoria: Optional[str] = None, limite: int = 6) -> str:
        """Compatibilidad con lo que ya usa NarrativaInterna: solo texto
        consolidado o superior, concatenado. Para algo mejor sintetizado,
        ver resumen_narrativo()."""
        rasgos = self._consolidados_o_mas(categoria, limite)
        if not rasgos:
            return ""
        return " ".join(r["contenido"] for r in rasgos)

    def resumen_narrativo(self, categoria: Optional[str] = None, limite: int = 6) -> str:
        """Versión sintetizada: separa lo que ya es 'núcleo' de lo que es
        'solo' consolidado, y evita mostrar dos rasgos que en el fondo
        dicen lo mismo con otras palabras."""
        rasgos = self._consolidados_o_mas(categoria, limite * 3)
        if not rasgos:
            return ""

        elegidos: List[Dict] = []
        vistas: List[set] = []
        for r in rasgos:
            palabras = self._palabras_significativas(r["contenido"])
            if any(len(palabras & v) >= 3 for v in vistas):
                continue  # muy parecido a algo que ya está incluido
            elegidos.append(r)
            vistas.append(palabras)
            if len(elegidos) >= limite:
                break

        nucleo = [r["contenido"] for r in elegidos if r["nivel"] == NIVEL_NUCLEO]
        resto = [r["contenido"] for r in elegidos if r["nivel"] != NIVEL_NUCLEO]

        partes = []
        if nucleo:
            partes.append("En el fondo: " + " ".join(nucleo))
        if resto:
            partes.append(" ".join(resto))
        return " ".join(partes)

    def hay_identidad_consolidada(self) -> bool:
        return bool(self._consolidados_o_mas(None, 1))

    def detalle(self, min_confianza: float = 0.0, categoria: Optional[str] = None,
                limite: int = 50) -> List[Dict]:
        """Para inspección/debug/UI: todos los rasgos con su nivel ya
        calculado, sin filtrar por consolidación."""
        rasgos = self.memoria.listar_identidad(min_confianza, categoria, limite)
        for r in rasgos:
            r["nivel"] = self._nivel(r)
        return rasgos

    # -----------------------------------------------------------------
    def _consolidados_o_mas(self, categoria: Optional[str], limite: int) -> List[Dict]:
        rasgos = self.memoria.listar_identidad(min_confianza=CONFIANZA_CONSOLIDACION,
                                                categoria=categoria, limite=limite)
        rasgos = [r for r in rasgos if r["veces_reforzado"] >= REFUERZOS_MIN_CONSOLIDACION]
        for r in rasgos:
            r["nivel"] = self._nivel(r)
        return [r for r in rasgos if r["nivel"] in (NIVEL_CONSOLIDADO, NIVEL_NUCLEO)]

    def _nivel(self, rasgo: Dict) -> str:
        antiguedad_dias = (rasgo["ultima_vez"] - rasgo["primera_vez"]) / 86400
        if (rasgo["confianza"] >= CONFIANZA_NUCLEO
                and rasgo["veces_reforzado"] >= REFUERZOS_MIN_NUCLEO
                and antiguedad_dias >= DIAS_MIN_ANTIGUEDAD_NUCLEO):
            return NIVEL_NUCLEO
        if rasgo["confianza"] >= CONFIANZA_CONSOLIDACION and rasgo["veces_reforzado"] >= REFUERZOS_MIN_CONSOLIDACION:
            return NIVEL_CONSOLIDADO
        if rasgo["confianza"] >= CONFIANZA_EN_FORMACION:
            return NIVEL_EN_FORMACION
        return NIVEL_CANDIDATO

    def _mejor_coincidencia(self, palabras_nuevas: set, candidatos: List[Dict]):
        mejor_match, mejor_peso = None, 0
        for c in candidatos:
            comunes = palabras_nuevas & self._palabras_significativas(c["contenido"])
            if len(comunes) < UMBRAL_PALABRAS_COMUNES:
                continue
            peso = sum(len(w) for w in comunes)
            if peso >= UMBRAL_PESO_COMUN and peso > mejor_peso:
                mejor_match, mejor_peso = c, peso
        return mejor_match, mejor_peso

    def _inferir_categoria(self, contenido: str) -> str:
        palabras = self._palabras_significativas(contenido)
        if "usuario" in palabras:
            return "vinculo_usuario"
        return "rasgo_propio"

    @staticmethod
    def _emocion_en_texto(texto: str) -> Optional[str]:
        texto_l = texto.lower()
        for emo in EMOCIONES_POSITIVAS | EMOCIONES_NEGATIVAS:
            if emo in texto_l:
                return emo
        return None

    @staticmethod
    def _valencia(emocion: Optional[str]) -> int:
        if emocion in EMOCIONES_POSITIVAS:
            return 1
        if emocion in EMOCIONES_NEGATIVAS:
            return -1
        return 0

    @staticmethod
    def _palabras_significativas(texto: str) -> set:
        return {w for w in texto.lower().split() if len(w) > 2 and w not in STOPWORDS_ES}