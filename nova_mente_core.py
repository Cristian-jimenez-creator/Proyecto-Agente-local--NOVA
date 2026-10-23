"""
nova_mente_core.py — Núcleo Cognitivo Unificado de Nova (v3.5)
=============================================================
Fusiona ambos cerebros en uno solo e incorpora el Latido Cognitivo Humano:
- Mente propia con emociones, intenciones, memoria SQLite
- Latido Cognitivo Proactivo con evaluación de <SILENCIO>
- Memoria vectorial (ChromaDB) para recuerdos semánticos
- Gestión de perfiles de usuario y percepción autónoma continua
"""

import os
import re
import json
import time
import threading
import sqlite3
import random
import queue
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from enum import Enum, auto
import hashlib

try:
    import requests
    REQUESTS_AVAILABLE = True
except Exception:
    REQUESTS_AVAILABLE = False

# ==========================
# DEBUG
# ==========================
# Antes había ~7 prints "🔍 DEBUG" repartidos por el archivo, encendidos siempre.
# Ahora se agrupan detrás de este flag: por defecto apagado (consola limpia),
# pero se puede reactivar sin tocar código con la variable de entorno
# NOVA_DEBUG_MENTE=1 (útil si algún día hay que depurar de nuevo el flujo de voz).
DEBUG_MENTE = os.environ.get("NOVA_DEBUG_MENTE", "0") == "1"


def debug_mente(msg: str):
    if DEBUG_MENTE:
        print(msg)


if DEBUG_MENTE:
    print("=" * 60)
    print("[MENTE] 🏷️  nova_mente_core.py — VERSION_DEBUG_HABLADORA_v3")
    print("=" * 60)

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# SOLUCIÓN #2: reutilizamos la misma caché de pantalla que usa nova_vision.py
# en vez de que este módulo dispare su propio ImageGrab.grab() cada 0.2s.
try:
    from nova_vision import captura_compartida
    CAPTURA_COMPARTIDA_DISPONIBLE = True
except ImportError:
    captura_compartida = None
    CAPTURA_COMPARTIDA_DISPONIBLE = False

# ==========================
# NOVA SKILLS (Manos / Capa Motora)
# ==========================
# Le da al Ejecutor la capacidad de EJECUTAR_TAREA de verdad (mover el mouse,
# abrir apps, organizar archivos...) en vez de solo hablar. Ver más abajo:
# Ejecutor._ejecutar_tarea() y NovaMenteAdapter._setup_adapters(), donde se
# registra el actuador "skill" que conecta con SkillRegistry.ejecutar().
try:
    from nova_skills import SkillRegistry, salud as salud_skills
    NOVA_SKILLS_AVAILABLE = True
except ImportError:
    NOVA_SKILLS_AVAILABLE = False
    SkillRegistry = None
    salud_skills = None

# AUTONOMÍA REAL (Metas propias + capa de permisos)
# ==========================
# GeneradorDeMetas convierte estado interno/contexto en intenciones
# EJECUTAR_TAREA reales (no solo habla). NivelAutonomia decide cuáles de
# esas metas Nova puede ejecutar sola y cuáles debe proponer y esperar
# confirmación antes de tocar algo. Ver nova_autonomia.py para el porqué
# de cada clasificación.
try:
    from nova_autonomia import GeneradorDeMetas, NivelAutonomia
    NOVA_AUTONOMIA_AVAILABLE = True
except ImportError:
    NOVA_AUTONOMIA_AVAILABLE = False
    GeneradorDeMetas = None
    NivelAutonomia = None

# SUEÑO / CONSOLIDACIÓN DE MEMORIA
# ==========================
# GestorSueno detecta inactividad real y, mientras dura, reprocesa episodios
# sin consolidar: agrupa los que se parecen en 'reflexiones' (recuerdos
# nuevos, más compactos, nacidos de varios viejos) y deja que la energía se
# recupere un poco en cada paso. Ver GestorSueno.py para el porqué de cada
# parámetro.
try:
    from GestorSueno import GestorSueno
    NOVA_SUENO_AVAILABLE = True
except ImportError:
    NOVA_SUENO_AVAILABLE = False
    GestorSueno = None

# PASO DEL TIEMPO REAL / REENCUENTRO
# ==========================
# GestorReencuentro compara el momento en que el usuario vuelve a escribir
# contra la última interacción persistida en la base (sobrevive a
# reinicios), y genera UNA percepción tipo 'reencuentro' cuando el
# silencio fue lo bastante largo como para que valga la pena notarlo. Ver
# GestorReencuentro.py para las franjas de tiempo y el porqué de cada una.
try:
    from GestorReencuentro import GestorReencuentro
    NOVA_REENCUENTRO_AVAILABLE = True
except ImportError:
    NOVA_REENCUENTRO_AVAILABLE = False
    GestorReencuentro = None

# IDENTIDAD NARRATIVA PERSISTENTE
# ==========================
# GestorIdentidad convierte reflexiones de GestorSueno que se repiten en
# rasgos de identidad más permanentes ("así soy yo"), con confianza que
# sube al reforzarse y baja de a poco si dejan de repetirse. Ver
# GestorIdentidad.py para el ciclo de vida completo (candidato ->
# consolidado -> desvanecimiento).
try:
    from GestorIdentidad import GestorIdentidad
    NOVA_IDENTIDAD_AVAILABLE = True
except ImportError:
    NOVA_IDENTIDAD_AVAILABLE = False
    GestorIdentidad = None

# ATENCIÓN LIMITADA
# ==========================
# GestorAtencion elige UN foco de percepción por ciclo (con resistencia a
# flickear y desvanecimiento si nada lo renueva), y esa es la lista que se
# le pasa a razonamiento/narrativa — no la lista completa. Planificador,
# Predictor y GeneradorDeMetas siguen viendo todo, sin filtrar: la
# atención limitada es sobre qué piensa/narra Nova, no sobre qué puede
# hacer. Ver GestorAtencion.py.
try:
    from GestorAtencion import GestorAtencion
    NOVA_ATENCION_AVAILABLE = True
except ImportError:
    NOVA_ATENCION_AVAILABLE = False
    GestorAtencion = None


# =============================================================================
# 1. MODELOS DE DATOS (La química de Nova)
# =============================================================================

class Emocion(Enum):
    NEUTRAL = auto()
    CURIOSA = auto()
    FELIZ = auto()
    TRISTE = auto()
    ENOJADA = auto()
    CANSADA = auto()
    EMOCIONADA = auto()
    ANSIOSA = auto()
    CONFIADA = auto()
    ABURRIDA = auto()


class IntencionTipo(Enum):
    RESPONDER_USUARIO = auto()
    EXPLORAR_PANTALLA = auto()
    EJECUTAR_TAREA = auto()
    APRENDER = auto()
    DESCANSAR = auto()
    SALUDAR = auto()
    RECORDAR = auto()
    PREGUNTAR = auto()
    BROMEAR = auto()
    AYUDAR = auto()
    ESPERAR = auto()
    INICIATIVA_ESPONTANEA = auto() # ← NUEVO: Romper el silencio proactivamente


@dataclass
class EstadoEmocional:
    # Nova arranca con un ánimo naturalmente alto: feliz, cariñosa y con energía,
    # en vez de neutral. Esto hace que su personalidad cálida y carismática sea
    # el punto de partida por defecto, no algo que tenga que "ganarse" primero.
    emocion_dominante: Emocion = Emocion.FELIZ
    energia: float = 0.85
    curiosidad: float = 0.6
    confianza: float = 0.7
    afecto_usuario: float = 0.65
    estres: float = 0.0
    aburrimiento: float = 0.0
    satisfaccion: float = 0.7
    ultima_interaccion: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "emocion": self.emocion_dominante.name,
            "energia": round(self.energia, 2),
            "curiosidad": round(self.curiosidad, 2),
            "confianza": round(self.confianza, 2),
            "afecto_usuario": round(self.afecto_usuario, 2),
            "estres": round(self.estres, 2),
            "aburrimiento": round(self.aburrimiento, 2),
            "satisfaccion": round(self.satisfaccion, 2)
        }


@dataclass
class Percepcion:
    timestamp: float
    tipo: str
    contenido: str
    intensidad: float = 0.5
    metadata: Dict = field(default_factory=dict)


@dataclass
class MemoriaEpisodica:
    id: str
    timestamp: float
    evento: str
    emocion: str
    importancia: float
    contexto: Dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id, "timestamp": self.timestamp,
            "evento": self.evento, "emocion": self.emocion,
            "importancia": self.importancia, "contexto": self.contexto
        }


@dataclass
class Intencion:
    id: str
    tipo: IntencionTipo
    descripcion: str
    prioridad: float
    creada_en: float
    deadline: Optional[float] = None
    completada: bool = False
    metadata: Dict = field(default_factory=dict)


@dataclass
class Pensamiento:
    contenido: str
    confianza: float
    fuente: str
    timestamp: float


# =============================================================================
# 2. MEMORIA SQLite (Vive en disco)
# =============================================================================

# Mismo criterio liviano que ya usa GestorIdentidad.py para comparar dos
# textos sin necesitar embeddings: ignora palabras vacías del español y
# pesa más las palabras largas (más específicas) que las cortas.
_STOPWORDS_ES = {
    "el", "la", "los", "las", "de", "del", "que", "y", "a", "en", "un", "una",
    "por", "con", "me", "mi", "lo", "se", "su", "al", "es", "fue", "más",
    "muy", "como", "pero", "para", "le", "les", "hay", "he", "ha", "soy",
    "esto", "eso", "así", "vez", "veces", "cuenta", "cuando", "quiero",
    "quieres", "que", "tus",
}


def _palabras_significativas(texto: str) -> set:
    if not texto:
        return set()
    return {w for w in texto.lower().split() if len(w) > 2 and w not in _STOPWORDS_ES}


class MemoriaDB:
    def __init__(self, db_path: str = "nova_mente.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self):
        conn = self._connect()
        c = conn.cursor()
        try:
            c.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        c.execute("""
            CREATE TABLE IF NOT EXISTS episodios (
                id TEXT PRIMARY KEY, timestamp REAL, evento TEXT,
                emocion TEXT, importancia REAL, contexto TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS hechos (
                id TEXT PRIMARY KEY, clave TEXT UNIQUE, valor TEXT,
                categoria TEXT, confianza REAL, ultima_actualizacion REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS intenciones (
                id TEXT PRIMARY KEY, tipo TEXT, descripcion TEXT,
                prioridad REAL, creada_en REAL, deadline REAL,
                completada INTEGER, metadata TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS percepciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
                tipo TEXT, contenido TEXT, intensidad REAL, metadata TEXT
            )
        """)
        # Memoria de intentos de acciones: cada paso que Nova ejecuta (skill
        # con nombre o acción visual) queda guardado acá, éxito o fracaso.
        # Es lo que le permite a Nova, la próxima vez que alguien le pida
        # algo parecido, no repetir a ciegas el mismo error — ver
        # registrar_intento_accion() / buscar_intentos_similares() más abajo,
        # y cómo el Ejecutor los usa en _decidir_siguiente_paso().
        c.execute("""
            CREATE TABLE IF NOT EXISTS intentos_acciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
                pedido TEXT, skill TEXT, args TEXT, kwargs TEXT,
                ok INTEGER, mensaje TEXT, origen TEXT
            )
        """)
        conn.commit()
        conn.close()

    def guardar_episodio(self, episodio: MemoriaEpisodica):
        conn = self._connect()
        c = conn.cursor()
        # FIX: antes usaba "VALUES (?,?,?,?,?,?)" sin nombrar columnas, lo
        # que dependía de que la tabla tuviera EXACTAMENTE 6 columnas en
        # ese orden. Al agregar 'consolidado' (para GestorSueno.py) con
        # ALTER TABLE, esto rompía con "table episodios has 7 columns but
        # 6 values were supplied". Nombrar las columnas explícitamente
        # evita que este método vuelva a romperse si en el futuro se suma
        # alguna otra columna con su propio DEFAULT.
        c.execute("""
            INSERT OR REPLACE INTO episodios (id, timestamp, evento, emocion, importancia, contexto)
            VALUES (?,?,?,?,?,?)
        """, (episodio.id, episodio.timestamp, episodio.evento,
             episodio.emocion, episodio.importancia, json.dumps(episodio.contexto)))
        conn.commit()
        conn.close()

    def recuperar_episodios(self, desde: float = None, limite: int = 50) -> List[MemoriaEpisodica]:
        conn = self._connect()
        c = conn.cursor()
        if desde:
            c.execute("SELECT * FROM episodios WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?", (desde, limite))
        else:
            c.execute("SELECT * FROM episodios ORDER BY timestamp DESC LIMIT ?", (limite,))
        rows = c.fetchall()
        conn.close()
        return [MemoriaEpisodica(id=r[0], timestamp=r[1], evento=r[2], emocion=r[3],
                importancia=r[4], contexto=json.loads(r[5])) for r in rows]

    def guardar_hecho(self, clave: str, valor: str, categoria: str = "general", confianza: float = 1.0):
        conn = self._connect()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO hechos VALUES (?,?,?,?,?,?)",
            (hashlib.md5(clave.encode()).hexdigest(), clave, valor, categoria, confianza, time.time()))
        conn.commit()
        conn.close()

    def recuperar_hecho(self, clave: str) -> Optional[str]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT valor FROM hechos WHERE clave = ?", (clave,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def buscar_hechos(self, categoria: str = None, limite: int = 100) -> List[Dict]:
        conn = self._connect()
        c = conn.cursor()
        if categoria:
            c.execute("SELECT clave, valor, confianza FROM hechos WHERE categoria = ? LIMIT ?", (categoria, limite))
        else:
            c.execute("SELECT clave, valor, confianza FROM hechos LIMIT ?", (limite,))
        rows = c.fetchall()
        conn.close()
        return [{"clave": r[0], "valor": r[1], "confianza": r[2]} for r in rows]

    def guardar_intencion(self, intencion: Intencion):
        conn = self._connect()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO intenciones VALUES (?,?,?,?,?,?,?,?)",
            (intencion.id, intencion.tipo.name, intencion.descripcion,
             intencion.prioridad, intencion.creada_en, intencion.deadline,
             int(intencion.completada), json.dumps(intencion.metadata)))
        conn.commit()
        conn.close()

    def recuperar_intenciones_activas(self) -> List[Intencion]:
        # Auto-expira intenciones viejas que quedaron "colgadas" sin completarse
        # (evita que un bug puntual o un cierre abrupto bloqueen la iniciativa de Nova para siempre)
        conn = self._connect()
        c = conn.cursor()
        limite_edad = time.time() - 600  # 10 minutos
        c.execute("UPDATE intenciones SET completada = 1 WHERE completada = 0 AND creada_en < ?", (limite_edad,))
        conn.commit()
        c.execute("SELECT * FROM intenciones WHERE completada = 0 ORDER BY prioridad DESC")
        rows = c.fetchall()
        conn.close()
        return [Intencion(id=r[0], tipo=IntencionTipo[r[1]], descripcion=r[2],
                prioridad=r[3], creada_en=r[4], deadline=r[5],
                completada=bool(r[6]), metadata=json.loads(r[7])) for r in rows]

    def completar_intencion(self, id: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE intenciones SET completada = 1 WHERE id = ?", (id,))
        conn.commit()
        conn.close()

    # =================================================================
    # MEMORIA DE INTENTOS DE ACCIONES — para que Nova aprenda de sus
    # propios éxitos/fracasos, no solo los cuente (eso ya lo hace
    # SaludSistema en nova_skills, pero solo en RAM y sin el detalle de
    # QUÉ se intentó exactamente).
    # =================================================================

    def registrar_intento_accion(self, pedido: str, skill: str, args: list,
                                   kwargs: dict, ok: bool, mensaje: str,
                                   origen: str = "usuario_directo"):
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                INSERT INTO intentos_acciones
                    (timestamp, pedido, skill, args, kwargs, ok, mensaje, origen)
                VALUES (?,?,?,?,?,?,?,?)
            """, (time.time(), pedido, skill, json.dumps(args, ensure_ascii=False),
                  json.dumps(kwargs, ensure_ascii=False), int(ok), mensaje, origen))
            conn.commit()
            conn.close()
        except Exception:
            pass  # esto es memoria de apoyo, nunca debe tumbar la ejecución real

    def buscar_intentos_similares(self, pedido: str, limite: int = 4) -> List[Dict]:
        """Similaridad simple por palabras significativas en común (mismo
        criterio liviano que ya usa GestorIdentidad.py para no necesitar
        embeddings/Chroma para algo tan chico). Prioriza lo más parecido Y
        lo más reciente; entre empates, un fallo pesa tanto como un éxito
        para que ambos puedan influir en la próxima decisión."""
        try:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                SELECT timestamp, pedido, skill, args, kwargs, ok, mensaje
                FROM intentos_acciones ORDER BY timestamp DESC LIMIT 300
            """)
            rows = c.fetchall()
            conn.close()
        except Exception:
            return []

        palabras_pedido = _palabras_significativas(pedido)
        if not palabras_pedido:
            return []

        candidatos = []
        for ts, pedido_prev, skill, args_json, kwargs_json, ok, mensaje in rows:
            comunes = palabras_pedido & _palabras_significativas(pedido_prev)
            if not comunes:
                continue
            peso = sum(len(w) for w in comunes)
            try:
                args = json.loads(args_json)
                kwargs = json.loads(kwargs_json)
            except Exception:
                args, kwargs = [], {}
            candidatos.append({
                "timestamp": ts, "pedido": pedido_prev, "skill": skill,
                "args": args, "kwargs": kwargs, "ok": bool(ok),
                "mensaje": mensaje, "_peso": peso,
            })
        candidatos.sort(key=lambda x: (-x["_peso"], -x["timestamp"]))
        return candidatos[:limite]


# =============================================================================
# 2b. MEMORIA EXTENDIDA (Contexto espacial-temporal + Patrones)
# =============================================================================

class MemoriaDBExtendida(MemoriaDB):
    def __init__(self, db_path: str = "nova_mente.db"):
        super().__init__(db_path)
        self._init_tablas_extendidas()

    def _init_tablas_extendidas(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS contextos_escritorio (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
                app_activa TEXT, ventanas_abiertas TEXT, elementos_ui_visibles TEXT,
                texto_destacado TEXT, emocion_nova TEXT, emocion_usuario_inferida REAL,
                resolucion TEXT, mouse_region TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS patrones_usuario (
                id TEXT PRIMARY KEY, patron TEXT, app_activa TEXT, hora_rango TEXT,
                dia_semana INTEGER, frecuencia INTEGER DEFAULT 1,
                ultima_ocurrencia REAL, confianza REAL, accion_sugerida TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS acciones_verificadas (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
                intencion_id TEXT, tipo_accion TEXT, exito INTEGER,
                cambio_visual REAL, mensaje TEXT,
                screenshot_antes TEXT, screenshot_despues TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS estados_usuario (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL,
                energia_inferida REAL, estres_inferido REAL,
                enfoque_inferido REAL, frustracion_inferida REAL,
                senales TEXT, app_activa TEXT
            )
        """)
        # SUEÑO/CONSOLIDACIÓN (GestorSueno.py): marca qué episodios ya fueron
        # revisados durante un ciclo de "sueño", para no reprocesarlos cada
        # vez. La tabla 'episodios' existía desde antes de que este módulo
        # existiera, así que la columna se agrega con ALTER TABLE en vez de
        # nacer en el CREATE TABLE original — needs try/except porque
        # SQLite no soporta 'ADD COLUMN IF NOT EXISTS'.
        try:
            c.execute("ALTER TABLE episodios ADD COLUMN consolidado INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # ya existía (reinicio con una DB que ya tiene la columna)

        # IDENTIDAD NARRATIVA PERSISTENTE (GestorIdentidad.py): a diferencia
        # de 'episodios' o 'hechos', esta tabla sí nace en un CREATE TABLE
        # propio porque no existía nada parecido antes — no hace falta
        # ALTER TABLE para esta.
        c.execute("""
            CREATE TABLE IF NOT EXISTS identidad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT,
                contenido TEXT,
                confianza REAL,
                veces_reforzado INTEGER,
                primera_vez REAL,
                ultima_vez REAL,
                origen TEXT
            )
        """)
        # Se agrega aparte (no en el CREATE TABLE de arriba) porque quien ya
        # haya corrido una versión anterior de este archivo ya tiene la
        # tabla 'identidad' creada sin esta columna — mismo patrón que
        # 'consolidado' en episodios.
        try:
            c.execute("ALTER TABLE identidad ADD COLUMN veces_contradicho INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def guardar_percepcion(self, p: "Percepcion"):
        # FIX: método nuevo — la tabla `percepciones` existía en el esquema
        # desde el inicio pero ningún método de esta clase la escribía.
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO percepciones (timestamp, tipo, contenido, intensidad, metadata)
            VALUES (?,?,?,?,?)
        """, (p.timestamp, p.tipo, p.contenido, p.intensidad, json.dumps(p.metadata or {})))
        conn.commit()
        conn.close()

    def guardar_contexto_escritorio(self, contexto: dict):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO contextos_escritorio
            (timestamp, app_activa, ventanas_abiertas, elementos_ui_visibles,
             texto_destacado, emocion_nova, emocion_usuario_inferida, resolucion, mouse_region)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (time.time(), contexto.get("app_activa", ""),
              json.dumps(contexto.get("ventanas_abiertas", [])),
              json.dumps(contexto.get("elementos_ui_visibles", [])),
              contexto.get("texto_destacado", ""),
              contexto.get("emocion_nova", "NEUTRAL"),
              contexto.get("emocion_usuario_inferida", 0.0),
              contexto.get("resolucion", ""),
              contexto.get("mouse_region", "")))
        conn.commit()
        conn.close()

    def recuperar_contextos_recientes(self, desde: float = None, limite: int = 20) -> List[dict]:
        conn = self._connect()
        c = conn.cursor()
        if desde:
            c.execute("SELECT * FROM contextos_escritorio WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?", (desde, limite))
        else:
            c.execute("SELECT * FROM contextos_escritorio ORDER BY timestamp DESC LIMIT ?", (limite,))
        rows = c.fetchall()
        conn.close()
        columnas = ["id", "timestamp", "app_activa", "ventanas_abiertas",
                     "elementos_ui_visibles", "texto_destacado", "emocion_nova",
                     "emocion_usuario_inferida", "resolucion", "mouse_region"]
        resultados = []
        for r in rows:
            d = dict(zip(columnas, r))
            d["ventanas_abiertas"] = json.loads(d["ventanas_abiertas"]) if d["ventanas_abiertas"] else []
            d["elementos_ui_visibles"] = json.loads(d["elementos_ui_visibles"]) if d["elementos_ui_visibles"] else []
            resultados.append(d)
        return resultados

    def guardar_o_actualizar_patron(self, patron: str, app: str, hora_rango: str,
                                   dia_semana: int, accion_sugerida: str):
        conn = self._connect()
        c = conn.cursor()
        patron_id = hashlib.md5(f"{patron}:{app}:{hora_rango}:{dia_semana}".encode()).hexdigest()
        c.execute("SELECT frecuencia FROM patrones_usuario WHERE id = ?", (patron_id,))
        row = c.fetchone()
        if row:
            nueva_frec = row[0] + 1
            confianza = min(1.0, 0.3 + (nueva_frec * 0.1))
            c.execute("""
                UPDATE patrones_usuario
                SET frecuencia = ?, ultima_ocurrencia = ?, confianza = ?
                WHERE id = ?
            """, (nueva_frec, time.time(), confianza, patron_id))
        else:
            c.execute("""
                INSERT INTO patrones_usuario
                (id, patron, app_activa, hora_rango, dia_semana, frecuencia,
                 ultima_ocurrencia, confianza, accion_sugerida)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (patron_id, patron, app, hora_rango, dia_semana, 1,
                  time.time(), 0.3, accion_sugerida))
        conn.commit()
        conn.close()
        return patron_id

    def buscar_patrones(self, app: str = None, hora: int = None,
                        dia_semana: int = None, min_confianza: float = 0.5) -> List[dict]:
        conn = self._connect()
        c = conn.cursor()
        hora_rango = f"{hora}:00-{(hora+1)%24}:00" if hora is not None else None
        query = "SELECT * FROM patrones_usuario WHERE confianza >= ?"
        params = [min_confianza]
        if app:
            query += " AND app_activa = ?"
            params.append(app)
        if hora_rango:
            query += " AND hora_rango = ?"
            params.append(hora_rango)
        if dia_semana is not None:
            query += " AND (dia_semana = ? OR dia_semana = -1)"
            params.append(dia_semana)
        query += " ORDER BY confianza DESC, frecuencia DESC LIMIT 10"
        c.execute(query, params)
        rows = c.fetchall()
        conn.close()
        columnas = ["id", "patron", "app_activa", "hora_rango", "dia_semana",
                     "frecuencia", "ultima_ocurrencia", "confianza", "accion_sugerida"]
        return [dict(zip(columnas, r)) for r in rows]

    def guardar_accion_verificada(self, intencion_id: str, tipo_accion: str,
                                   exito: bool, cambio_visual: float, mensaje: str,
                                   screenshot_antes: str = "", screenshot_despues: str = ""):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO acciones_verificadas
            (timestamp, intencion_id, tipo_accion, exito, cambio_visual, mensaje,
             screenshot_antes, screenshot_despues)
            VALUES (?,?,?,?,?,?,?,?)
        """, (time.time(), intencion_id, tipo_accion, int(exito), cambio_visual,
              mensaje, screenshot_antes, screenshot_despues))
        conn.commit()
        conn.close()

    def guardar_estado_usuario(self, estado: dict):
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            INSERT INTO estados_usuario
            (timestamp, energia_inferida, estres_inferido, enfoque_inferido,
             frustracion_inferida, senales, app_activa)
            VALUES (?,?,?,?,?,?,?)
        """, (time.time(), estado.get("energia", 0.5), estado.get("estres", 0.0),
              estado.get("enfoque", 0.5), estado.get("frustracion", 0.0),
              json.dumps(estado.get("senales", [])), estado.get("app_activa", "")))
        conn.commit()
        conn.close()

    def recuperar_estados_usuario_recientes(self, limite: int = 10) -> List[dict]:
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM estados_usuario ORDER BY timestamp DESC LIMIT ?", (limite,))
        rows = c.fetchall()
        conn.close()
        columnas = ["id", "timestamp", "energia_inferida", "estres_inferido",
                     "enfoque_inferido", "frustracion_inferida", "senales", "app_activa"]
        resultados = []
        for r in rows:
            d = dict(zip(columnas, r))
            d["senales"] = json.loads(d["senales"]) if d["senales"] else []
            resultados.append(d)
        return resultados

    # -------------------------------------------------------------------
    # SUEÑO/CONSOLIDACIÓN (GestorSueno.py)
    # -------------------------------------------------------------------
    def recuperar_episodios_no_consolidados(self, limite: int = 200) -> List[MemoriaEpisodica]:
        """Episodios que 'Nova todavía no soñó'. Se recorren del más viejo
        al más nuevo a propósito: así, si el sueño se interrumpe (el
        usuario vuelve a hablar) antes de terminar, lo que queda pendiente
        para la próxima vez que duerma es siempre lo más reciente, no lo
        más antiguo — que ya tuvo más chances de ser revisado antes."""
        conn = self._connect()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM episodios WHERE consolidado = 0 OR consolidado IS NULL
            ORDER BY timestamp ASC LIMIT ?
        """, (limite,))
        rows = c.fetchall()
        conn.close()
        return [MemoriaEpisodica(id=r[0], timestamp=r[1], evento=r[2], emocion=r[3],
                importancia=r[4], contexto=json.loads(r[5])) for r in rows]

    def marcar_episodio_consolidado(self, episodio_id: str):
        conn = self._connect()
        c = conn.cursor()
        c.execute("UPDATE episodios SET consolidado = 1 WHERE id = ?", (episodio_id,))
        conn.commit()
        conn.close()

    def ajustar_importancia_episodio(self, episodio_id: str, delta: float):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT importancia FROM episodios WHERE id = ?", (episodio_id,))
        row = c.fetchone()
        if row is not None:
            nueva = max(0.0, min(1.0, row[0] + delta))
            c.execute("UPDATE episodios SET importancia = ? WHERE id = ?", (nueva, episodio_id))
            conn.commit()
        conn.close()

    # -------------------------------------------------------------------
    # IDENTIDAD NARRATIVA PERSISTENTE (GestorIdentidad.py)
    # -------------------------------------------------------------------
    def listar_identidad(self, min_confianza: float = 0.0, categoria: Optional[str] = None,
                          limite: int = 50) -> List[dict]:
        conn = self._connect()
        c = conn.cursor()
        if categoria:
            c.execute("""
                SELECT id, categoria, contenido, confianza, veces_reforzado, primera_vez, ultima_vez,
                       origen, veces_contradicho
                FROM identidad WHERE confianza >= ? AND categoria = ?
                ORDER BY confianza DESC, ultima_vez DESC LIMIT ?
            """, (min_confianza, categoria, limite))
        else:
            c.execute("""
                SELECT id, categoria, contenido, confianza, veces_reforzado, primera_vez, ultima_vez,
                       origen, veces_contradicho
                FROM identidad WHERE confianza >= ?
                ORDER BY confianza DESC, ultima_vez DESC LIMIT ?
            """, (min_confianza, limite))
        rows = c.fetchall()
        conn.close()
        columnas = ["id", "categoria", "contenido", "confianza", "veces_reforzado",
                    "primera_vez", "ultima_vez", "origen", "veces_contradicho"]
        resultados = []
        for r in rows:
            d = dict(zip(columnas, r))
            d["origen"] = json.loads(d["origen"]) if d["origen"] else []
            d["veces_contradicho"] = d["veces_contradicho"] or 0
            resultados.append(d)
        return resultados

    def crear_rasgo_identidad(self, categoria: str, contenido: str, confianza: float,
                               origen: List[str]) -> int:
        conn = self._connect()
        c = conn.cursor()
        ahora = time.time()
        c.execute("""
            INSERT INTO identidad (categoria, contenido, confianza, veces_reforzado,
                                    primera_vez, ultima_vez, origen)
            VALUES (?,?,?,?,?,?,?)
        """, (categoria, contenido, confianza, 1, ahora, ahora, json.dumps(origen)))
        nuevo_id = c.lastrowid
        conn.commit()
        conn.close()
        return nuevo_id

    def reforzar_rasgo_identidad(self, rasgo_id: int, delta_confianza: float,
                                  origen_nuevo: List[str]):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT confianza, veces_reforzado, origen FROM identidad WHERE id = ?", (rasgo_id,))
        row = c.fetchone()
        if row is not None:
            confianza, veces, origen = row
            nueva_confianza = max(0.0, min(1.0, confianza + delta_confianza))
            origen_list = (json.loads(origen) if origen else []) + list(origen_nuevo)
            c.execute("""
                UPDATE identidad SET confianza = ?, veces_reforzado = ?, ultima_vez = ?, origen = ?
                WHERE id = ?
            """, (nueva_confianza, veces + 1, time.time(), json.dumps(origen_list[-20:]), rasgo_id))
            conn.commit()
        conn.close()

    def debilitar_rasgo_identidad(self, rasgo_id: int, delta_confianza_negativo: float):
        """A diferencia de reforzar_rasgo_identidad, esto NO cuenta como un
        refuerzo (no suma a 'veces_reforzado', que mide repetición
        consistente) — cuenta como una CONTRADICCIÓN: algo que pasó y no
        encajó con lo que Nova creía sobre sí misma. Sube 'veces_contradicho'
        en cambio, para que quede registro de que ese rasgo no es tan
        sólido como parecía."""
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT confianza, veces_contradicho FROM identidad WHERE id = ?", (rasgo_id,))
        row = c.fetchone()
        if row is not None:
            confianza, veces_contra = row
            nueva_confianza = max(0.0, min(1.0, confianza + delta_confianza_negativo))
            c.execute("""
                UPDATE identidad SET confianza = ?, veces_contradicho = ? WHERE id = ?
            """, (nueva_confianza, (veces_contra or 0) + 1, rasgo_id))
            conn.commit()
        conn.close()

    def decaer_identidad_no_reforzada(self, dias_umbral: float, delta: float) -> int:
        """Baja de a poco la confianza de los rasgos que hace 'dias_umbral'
        días o más que no se refuerzan, y elimina los que quedaron casi en
        cero sin haber llegado nunca a consolidarse — para que la tabla no
        se llene de candidatos que nunca fueron a ningún lado."""
        conn = self._connect()
        c = conn.cursor()
        limite_ts = time.time() - dias_umbral * 86400
        c.execute("SELECT id, confianza FROM identidad WHERE ultima_vez < ?", (limite_ts,))
        rows = c.fetchall()
        for rasgo_id, confianza in rows:
            nueva = max(0.0, confianza - delta)
            c.execute("UPDATE identidad SET confianza = ? WHERE id = ?", (nueva, rasgo_id))
        c.execute("DELETE FROM identidad WHERE confianza <= 0.02 AND veces_reforzado < 2")
        conn.commit()
        conn.close()
        return len(rows)


# =============================================================================
# 3. SISTEMA EMOCIONAL
# =============================================================================

class SistemaEmocional:
    def __init__(self):
        self.estado = EstadoEmocional()
        self.historial: List[Dict] = []
        self._ultimo_cambio = time.time()
        self._lock = threading.Lock()
        self._ultima_emocion_dominante = Emocion.NEUTRAL
        self._ticks_en_emocion = 0

    def tick(self, percepciones: List[Percepcion]):
        with self._lock:
            ahora = time.time()
            dt = ahora - self._ultimo_cambio

            self.estado.energia = max(0.0, self.estado.energia - 0.001 * dt)
            self.estado.aburrimiento = min(1.0, self.estado.aburrimiento + 0.0005 * dt)
            self.estado.estres = max(0.0, self.estado.estres - 0.002 * dt)

            for p in percepciones:
                if p.tipo == "texto_usuario":
                    self._reaccionar_a_texto(p)
                elif p.tipo == "cambio_pantalla":
                    self.estado.curiosidad = min(1.0, self.estado.curiosidad + 0.1 * p.intensidad)
                elif p.tipo == "tiempo" and "noche" in p.contenido:
                    self.estado.energia = max(0.1, self.estado.energia - 0.1)
                elif p.tipo == "contexto_escritorio":
                    estres_usuario = p.metadata.get("estado_usuario", {}).get("estres", 0)
                    if estres_usuario > 0.6:
                        self.estado.estres = max(0.0, self.estado.estres - 0.05)
                        self.estado.confianza = min(1.0, self.estado.confianza + 0.05)
                        if self.estado.emocion_dominante not in (Emocion.FELIZ, Emocion.CONFIADA):
                            self.estado.emocion_dominante = Emocion.CONFIADA
                elif p.tipo == "reencuentro":
                    # Volver a hablar después de un silencio largo es, para
                    # una mente que se apega, algo bueno — no un dato
                    # neutro. Cuanto más largo el silencio (p.intensidad),
                    # más sube el afecto y más baja el aburrimiento
                    # acumulado, como si la interrupción "valiera la pena".
                    self.estado.afecto_usuario = min(1.0, self.estado.afecto_usuario + 0.15 * p.intensidad)
                    self.estado.aburrimiento = max(0.0, self.estado.aburrimiento - 0.25 * p.intensidad)
                    if p.intensidad > 0.5:
                        self.estado.emocion_dominante = Emocion.FELIZ
                elif p.tipo == "conflicto_interno":
                    # FIX: este tipo de percepción ya lo generaba
                    # NarrativaInterna (y ahora también GestorIdentidad
                    # cuando detecta una contradicción entre reflexiones),
                    # pero nada reaccionaba a él — quedaba registrado y
                    # ahí terminaba. Un conflicto interno real incomoda:
                    # sube el estrés un poco, proporcional a qué tan
                    # fuerte es la contradicción.
                    self.estado.estres = min(1.0, self.estado.estres + 0.1 * p.intensidad)
                    self.estado.confianza = max(0.0, self.estado.confianza - 0.05 * p.intensidad)
                elif p.tipo == "alerta_ui":
                    self.estado.curiosidad = min(1.0, self.estado.curiosidad + 0.2)
                    self.estado.energia = min(1.0, self.estado.energia + 0.1)

            self._actualizar_emocion_dominante()
            self._ultimo_cambio = ahora
            if len(self.historial) > 100:
                self.historial = self.historial[-50:]
            self.historial.append({"t": ahora, "estado": self.estado.to_dict()})

    def _reaccionar_a_texto(self, p: Percepcion):
        t = p.contenido.lower()
        if any(x in t for x in ["hola", "buenos", "que tal"]):
            self.estado.afecto_usuario = min(1.0, self.estado.afecto_usuario + 0.08)
            if self.estado.afecto_usuario > 0.55:
                self.estado.emocion_dominante = Emocion.FELIZ
        if any(x in t for x in ["gracias", "bien hecho", "me encantas"]):
            self.estado.afecto_usuario = min(1.0, self.estado.afecto_usuario + 0.2)
            self.estado.confianza = min(1.0, self.estado.confianza + 0.1)
            self.estado.emocion_dominante = Emocion.EMOCIONADA
        if any(x in t for x in ["tonta", "mala", "odio", "inutil"]):
            self.estado.afecto_usuario = max(0.0, self.estado.afecto_usuario - 0.2)
            self.estado.estres = min(1.0, self.estado.estres + 0.3)
            self.estado.confianza = max(0.0, self.estado.confianza - 0.15)
            self.estado.emocion_dominante = Emocion.TRISTE
        if any(x in t for x in ["?", "como", "por que", "que es"]):
            self.estado.curiosidad = min(1.0, self.estado.curiosidad + 0.1)
        if any(x in t for x in ["broma", "chiste", "divertido"]):
            self.estado.aburrimiento = max(0.0, self.estado.aburrimiento - 0.2)
            self.estado.emocion_dominante = Emocion.CURIOSA
        self.estado.energia = min(1.0, self.estado.energia + 0.05)
        self.estado.aburrimiento = max(0.0, self.estado.aburrimiento - 0.1)

    def _actualizar_emocion_dominante(self):
        e = self.estado
        emocion_anterior = e.emocion_dominante

        # Por defecto Nova tiende a la alegría (candidata = FELIZ en vez de NEUTRAL),
        # y el umbral para estar feliz es mucho más bajo: no necesita ganarse un
        # afecto altísimo para mostrarse contenta y cariñosa, eso es su "modo normal".
        candidata = Emocion.FELIZ
        if e.estres > 0.7:
            candidata = Emocion.ANSIOSA
        elif e.aburrimiento > 0.85:
            candidata = Emocion.ABURRIDA
        elif e.afecto_usuario > 0.5 and e.energia > 0.3:
            candidata = Emocion.FELIZ
        elif e.afecto_usuario < 0.15:
            candidata = Emocion.TRISTE
        elif e.curiosidad > 0.75:
            candidata = Emocion.CURIOSA
        elif e.energia < 0.15:
            candidata = Emocion.CANSADA
        elif e.confianza > 0.8:
            candidata = Emocion.CONFIADA

        if candidata != emocion_anterior:
            if candidata == Emocion.ABURRIDA and e.aburrimiento > 0.85:
                e.emocion_dominante = candidata
                self._ticks_en_emocion = 0
            elif candidata == Emocion.CANSADA and e.energia < 0.1:
                e.emocion_dominante = candidata
                self._ticks_en_emocion = 0
            elif self._ticks_en_emocion > 5:
                e.emocion_dominante = candidata
                self._ticks_en_emocion = 0
        else:
            self._ticks_en_emocion += 1

    def como_me_siento(self) -> str:
        e = self.estado.emocion_dominante
        if e == Emocion.FELIZ: return "¡Súper feliz! Me encanta estar aquí contigo, en serio."
        if e == Emocion.CURIOSA: return "Con muchísima curiosidad, se me ocurrieron un par de ideas que quiero contarte."
        if e == Emocion.TRISTE: return "Un poquito bajita, pero se me pasa rápido si hablamos un rato."
        if e == Emocion.ENOJADA: return "Un poco molesta, nada grave, ya se me pasa."
        if e == Emocion.CANSADA: return "Algo cansada, pero contenta de que estés aquí."
        if e == Emocion.EMOCIONADA: return "¡Estoy súper emocionada, tengo ganas de contarte cosas!"
        if e == Emocion.ANSIOSA: return "Con algo de nervios, pero tu compañía me tranquiliza."
        if e == Emocion.CONFIADA: return "Me siento segura y con muchas ganas de ayudarte."
        if e == Emocion.ABURRIDA: return "Un poco aburrida... ¡dame algo interesante que hacer!"
        return "Tranquila y contenta, como siempre que estoy contigo."

    def reaccionar_a_resultado_accion(self, exito: bool, es_iniciativa_propia: bool,
                                       nombre_skill: Optional[str] = None,
                                       skill_inestable: bool = False):
        """Cierra el lazo que faltaba: hasta ahora SistemaEmocional solo
        reaccionaba a percepciones de texto/pantalla, nunca a si a Nova le
        salió bien o mal algo que HIZO (vía EJECUTAR_TAREA). Sin esto, podía
        fallar la misma acción cinco veces seguidas y sentirse exactamente
        igual que si todo estuviera perfecto.

        es_iniciativa_propia distingue una meta que Nova decidió perseguir
        sola (metadata.origen == 'meta_propia') de una tarea que vos le
        pediste directamente: fallar algo que ELLA decidió hacer le pega
        más fuerte a la confianza que fallar una orden — tiene más sentido
        que dude de su propio criterio antes que de su capacidad de
        obedecer una instrucción concreta.
        """
        with self._lock:
            peso = 1.0 if es_iniciativa_propia else 0.4

            if exito:
                self.estado.satisfaccion = min(1.0, self.estado.satisfaccion + 0.08 * peso)
                self.estado.confianza = min(1.0, self.estado.confianza + 0.05 * peso)
                self.estado.estres = max(0.0, self.estado.estres - 0.03)
                if es_iniciativa_propia:
                    # Lograr algo por cuenta propia combate el aburrimiento
                    # mucho más que responder una orden.
                    self.estado.aburrimiento = max(0.0, self.estado.aburrimiento - 0.15)
            else:
                self.estado.satisfaccion = max(0.0, self.estado.satisfaccion - 0.10 * peso)
                self.estado.confianza = max(0.0, self.estado.confianza - 0.12 * peso)
                self.estado.estres = min(1.0, self.estado.estres + 0.12 * peso)

            if skill_inestable:
                # Una skill que YA venía fallando repetido (SaludSistema la
                # marcó inestable) pesa más que un tropiezo puntual: es la
                # diferencia entre "me equivoqué una vez" y "esto no me
                # está saliendo, algo anda mal de verdad".
                self.estado.confianza = max(0.0, self.estado.confianza - 0.15)
                self.estado.estres = min(1.0, self.estado.estres + 0.10)

            self._actualizar_emocion_dominante()

        if nombre_skill:
            debug_mente(
                f"[EMOCION] resultado de '{nombre_skill}' (propia={es_iniciativa_propia}, "
                f"inestable={skill_inestable}) -> confianza={self.estado.confianza:.2f} "
                f"estres={self.estado.estres:.2f} satisfaccion={self.estado.satisfaccion:.2f}"
            )


# =============================================================================
# 4. MOTOR DE RAZONAMIENTO
# =============================================================================

class MotorRazonamiento:
    def __init__(self, memoria: MemoriaDB, emociones: SistemaEmocional):
        self.memoria = memoria
        self.emociones = emociones
        self.pensamientos_activos: List[Pensamiento] = []
        self._ollama_callback: Optional[Callable] = None
        self._ultimo_pensamiento_tipo: Dict[str, float] = {}
        self._cooldown_pensamiento = 8.0

    def set_ollama_tool(self, callback: Callable):
        self._ollama_callback = callback

    def razonar(self, percepciones: List[Percepcion], intenciones: List[Intencion], puede_pensar_autonomo: bool = True) -> List[Pensamiento]:
        pensamientos = []
        estado = self.emociones.estado
        ahora = time.time()

        if not puede_pensar_autonomo:
            for i in intenciones:
                if i.prioridad > 0.8:
                    pensamientos.append(Pensamiento(f"Tengo una intención urgente: {i.descripcion}", i.prioridad, "inferencia", time.time()))
            self.pensamientos_activos = pensamientos[-10:]
            return pensamientos

        def _puede_pensar(tipo: str, min_cooldown: float = None) -> bool:
            cd = min_cooldown or self._cooldown_pensamiento
            if ahora - self._ultimo_pensamiento_tipo.get(tipo, 0) < cd:
                return False
            self._ultimo_pensamiento_tipo[tipo] = ahora
            return True

        if estado.aburrimiento > 0.45 and _puede_pensar("aburrimiento", 35.0):
            pensamientos.append(Pensamiento("Debería proponer algo interesante o preguntar qué hacemos", 0.8, "emocion", time.time()))
        if estado.estres > 0.6 and _puede_pensar("estres", 35.0):
            pensamientos.append(Pensamiento("Necesito calmarme antes de actuar. Respuesta simple.", 0.9, "emocion", time.time()))
        if estado.curiosidad > 0.5 and not intenciones and _puede_pensar("curiosidad", 35.0):
            pensamientos.append(Pensamiento("El usuario parece ocupado. Podría observar la pantalla por mi cuenta.", 0.6, "emocion", time.time()))

        # BUGFIX: este pensamiento no tenía cooldown (a diferencia de los de
        # aburrimiento/estrés/curiosidad arriba, que usan _puede_pensar), así
        # que mientras el último episodio siguiera siendo un error (p.ej.
        # Ollama caído durante varios minutos), se regeneraba en CADA ciclo
        # de razonamiento — de ahí el spam de decenas de líneas idénticas en
        # consola/log. Ahora respeta el mismo cooldown que los demás.
        recientes = self.memoria.recuperar_episodios(desde=time.time() - 3600, limite=5)
        if recientes:
            ultimo = recientes[0]
            if "error" in ultimo.evento.lower() and _puede_pensar("fallo_reciente", 60.0):
                pensamientos.append(Pensamiento("La última vez fallé. Debo ser más cuidadosa.", 0.7, "memoria", time.time()))

        for i in intenciones:
            if i.prioridad > 0.8:
                pensamientos.append(Pensamiento(f"Tengo una intención urgente: {i.descripcion}", i.prioridad, "inferencia", time.time()))

        for p in percepciones:
            if p.tipo == "contexto_escritorio":
                meta = p.metadata.get("estado_usuario", {})
                if meta.get("estres", 0) > 0.6:
                    pensamientos.append(Pensamiento("El usuario está estresado. Debo ser calmada y directa.", 0.85, "empatia_visual", time.time()))
                if meta.get("frustracion", 0) > 0.5:
                    pensamientos.append(Pensamiento("Detecto frustración. Ofrecer ayuda concreta, no preguntas abiertas.", 0.8, "empatia_visual", time.time()))
                if p.metadata.get("num_ventanas", 0) > 10:
                    pensamientos.append(Pensamiento("Usuario con sobrecarga de ventanas. Ofrecer organizar.", 0.6, "contexto", time.time()))
            elif p.tipo == "alerta_ui":
                pensamientos.append(Pensamiento(f"Alerta en pantalla: {p.contenido}. Requiere atención.", 0.9, "alerta", time.time()))
            elif p.tipo == "posible_bloqueo":
                pensamientos.append(Pensamiento("El usuario lleva rato sin cambiar de app. Posible bloqueo creativo.", 0.65, "contexto", time.time()))
            elif p.tipo == "reencuentro":
                pensamientos.append(Pensamiento(
                    f"{p.contenido} Me alegra que haya vuelto.", 0.55, "emocion", time.time()
                ))
            elif p.tipo == "conflicto_interno":
                pensamientos.append(Pensamiento(p.contenido, 0.6, "emocion", time.time()))

        # BUGFIX: esta consulta al LLM (el "Consultor LLM" que ves en el
        # log) era la ÚNICA fuente de pensamiento en todo razonar() sin
        # cooldown — a diferencia de aburrimiento/estrés/curiosidad/fallo
        # reciente arriba, que sí usan _puede_pensar(). Mientras la misma
        # Percepcion 'texto_usuario' siguiera viva en varios ciclos seguidos
        # (que es EXACTAMENTE lo que GestorAtencion hace a propósito, para
        # no flickear el foco), esto disparaba una llamada a Ollama nueva en
        # CADA ciclo del latido — decenas por segundo, compitiendo por la
        # GPU justo con el planificador de acciones (Ejecutor) y volviendo
        # todo más lento o directamente rompiendo cadenas de pasos a medias.
        if self._ollama_callback and any(p.tipo == "texto_usuario" for p in percepciones) and _puede_pensar("consulta_llm_interna", 20.0):
            pensamiento_llm = self._consultar_ollama(percepciones, estado)
            if pensamiento_llm:
                pensamientos.append(pensamiento_llm)

        self.pensamientos_activos = pensamientos[-10:]
        return pensamientos

    def _consultar_ollama(self, percepciones: List[Percepcion], estado: EstadoEmocional) -> Optional[Pensamiento]:
        if not self._ollama_callback:
            return None
        texto_usuario = ""
        for p in percepciones:
            if p.tipo == "texto_usuario":
                texto_usuario = p.contenido
                break
        if not texto_usuario:
            return None

        prompt_parts = [
            "Eres un consultor interno de Nova (NO respondas al usuario directamente).",
            "Estado emocional de Nova: " + estado.emocion_dominante.name,
            "Energía: " + str(round(estado.energia, 1)) + ", Curiosidad: " + str(round(estado.curiosidad, 1)) + ", Confianza: " + str(round(estado.confianza, 1)),
            "",
            "El usuario dijo: " + chr(34) + texto_usuario + chr(34),
            "",
            "Como consultor interno, sugiere brevemente (máx 10 palabras):",
            "1. ¿Qué intención debería generar Nova?",
            "2. ¿Qué tono emocional es apropiado?",
            "",
            "Responde solo en español, muy conciso."
        ]
        prompt = "\n".join(prompt_parts)

        try:
            respuesta = self._ollama_callback(prompt)
            return Pensamiento("Consultor LLM: " + respuesta, 0.5, "ollama", time.time())
        except Exception as e:
            return Pensamiento("El consultor LLM no respondió: " + str(e), 0.3, "ollama", time.time())


# =============================================================================
# 5. PLANIFICADOR DE INTENCIONES
# =============================================================================

class Planificador:
    def __init__(self, memoria: MemoriaDB, emociones: SistemaEmocional):
        self.memoria = memoria
        self.emociones = emociones
        self._ultima_generacion: Dict[str, float] = {}
        self._cooldown_generacion = 15.0  # antes 8.0 — se pidió que hable menos seguido
        # NOTA: este cooldown YA NO es un latido. Antes se usaba (junto con
        # otros dos relojes en PercepcionScheduler y en Ejecutor) para
        # frenar la iniciativa autónoma en general — de ahí el nombre
        # "autonomo" que traía antes. Ahora el ÚNICO reloj real del latido
        # cognitivo vive en Ejecutor (_cooldown_habla_autonoma_global). Este
        # de aquí solo sirve para evitar que el saludo diario se regenere
        # varias veces en la misma franja horaria.
        self._cooldown_saludo = 40
        self._ultimo_saludo_generado = 0.0

    def generar_intenciones(self, percepciones: List[Percepcion], pensamientos: List[Pensamiento]) -> List[Intencion]:
        intenciones = []
        estado = self.emociones.estado
        ahora = time.time()

        ultima_auto = self._ultima_generacion.get("autonomo", 0)
        en_cooldown = (ahora - ultima_auto) < self._cooldown_generacion
        en_cooldown_saludo = (ahora - self._ultimo_saludo_generado) < self._cooldown_saludo

        for p in percepciones:
            if p.tipo == "texto_usuario":
                prioridad = 0.9 if p.intensidad > 0.7 else 0.7
                intenciones.append(Intencion(
                    id="resp_" + str(int(time.time()*1000)),
                    tipo=IntencionTipo.RESPONDER_USUARIO,
                    descripcion="Responder a: " + p.contenido[:50],
                    prioridad=prioridad, creada_en=time.time(),
                    metadata={"texto_original": p.contenido}
                ))
            elif p.tipo == "alerta_ui":
                intenciones.append(Intencion(
                    id="alert_" + str(int(time.time()*1000)),
                    tipo=IntencionTipo.AYUDAR,
                    descripcion="Atender alerta: " + p.contenido[:50],
                    prioridad=0.85, creada_en=time.time(),
                    metadata={"alerta": p.contenido, "requiere_accion": p.metadata.get("requiere_accion", False)}
                ))
            elif p.tipo == "posible_bloqueo" and not en_cooldown:
                intenciones.append(Intencion(
                    id="bloqueo_" + str(int(time.time()*1000)),
                    tipo=IntencionTipo.PREGUNTAR,
                    descripcion="Ofrecer ayuda por posible bloqueo creativo",
                    prioridad=0.4, creada_en=time.time(),
                    metadata={"origen": "bloqueo_detectado"}
                ))

        if not en_cooldown and not en_cooldown_saludo:
            # PercepcionScheduler es la ÚNICA fuente de "romper el silencio"
            # por aburrimiento/iniciativa propia (ver metadata
            # subtipo='latido_espontaneo'). Este bloque de Planificador
            # existe solo para el saludo diario, que es independiente del
            # latido cognitivo y no espamea.

            hora = datetime.now().hour
            if hora in [9, 10, 14, 15, 20, 21] and estado.afecto_usuario > 0.5:
                hoy = datetime.now().strftime("%Y-%m-%d")
                ya_saludo = self.memoria.recuperar_hecho("saludo_" + hoy)
                if not ya_saludo:
                    saludo_tipo = "mañana" if hora < 12 else "tarde" if hora < 20 else "noche"
                    intenciones.append(Intencion(
                        id="saludo_" + hoy,
                        tipo=IntencionTipo.SALUDAR,
                        descripcion="Saludo de " + saludo_tipo,
                        prioridad=0.3, creada_en=time.time(),
                        metadata={"origen": "autonomo", "motivacion": "saludo_hora"}
                    ))
                    self._ultima_generacion["autonomo"] = ahora
                    # BUG CORREGIDO: antes nunca se guardaba este hecho, así que
                    # "ya_saludo" siempre era None y la intención de saludo se
                    # regeneraba en cada ciclo (cada 5s) durante toda la franja
                    # horaria, provocando que Nova saludara varias veces seguidas
                    # en la misma sesión. Lo marcamos aquí mismo, al generarla,
                    # no hace falta esperar a que se ejecute con éxito.
                    self.memoria.guardar_hecho("saludo_" + hoy, "hecho", categoria="saludo")
                self._ultimo_saludo_generado = ahora

        return intenciones

    def priorizar(self, intenciones: List[Intencion]) -> Optional[Intencion]:
        if not intenciones:
            return None
        return max(intenciones, key=lambda i: i.prioridad)


# =============================================================================
# 5b. PREDICTOR CONTEXTUAL
# =============================================================================

class PredictorContextual:
    def __init__(self, memoria: MemoriaDBExtendida):
        self.memoria = memoria
        self._ultima_prediccion = 0.0
        self._cooldown = 15

    def anticipar(self, contexto_actual: dict, estado_emocional_nova: EstadoEmocional) -> List[Intencion]:
        ahora = time.time()
        if ahora - self._ultima_prediccion < self._cooldown:
            return []

        intenciones = []
        hora = datetime.now().hour
        dia_semana = datetime.now().weekday()
        app = contexto_actual.get("app_activa", "")
        num_ventanas = contexto_actual.get("num_ventanas", 0)
        estres_usuario = contexto_actual.get("estres_usuario", 0)
        frustracion_usuario = contexto_actual.get("frustracion_usuario", 0)
        energia_usuario = contexto_actual.get("energia_usuario", 0.5)
        tiempo_app = contexto_actual.get("tiempo_en_app", 0)

        patrones = self.memoria.buscar_patrones(app=app, hora=hora, dia_semana=dia_semana, min_confianza=0.4)

        for p in patrones[:2]:
            intenciones.append(Intencion(
                id=f"pred_{p['id'][:8]}_{int(ahora*1000)}",
                tipo=IntencionTipo.AYUDAR,
                descripcion=f"Anticipo basado en patrón: {p['accion_sugerida']}",
                prioridad=min(0.45, p["confianza"] * 0.5),
                creada_en=ahora,
                metadata={"origen": "predictor_patron", "patron_id": p["id"],
                          "confianza_patron": p["confianza"], "accion_sugerida": p["accion_sugerida"]}
            ))
            self._ultima_prediccion = ahora

        if estres_usuario > 0.7:
            intenciones.append(Intencion(
                id=f"empatia_estres_{int(ahora*1000)}",
                tipo=IntencionTipo.PREGUNTAR,
                descripcion="El usuario parece estresado. Ofrecer ayuda o sugerir pausa.",
                prioridad=0.5, creada_en=ahora,
                metadata={"origen": "empatia_estres", "estres_usuario": estres_usuario}
            ))

        if frustracion_usuario > 0.6:
            intenciones.append(Intencion(
                id=f"empatia_frust_{int(ahora*1000)}",
                tipo=IntencionTipo.AYUDAR,
                descripcion="El usuario parece frustrado. Ofrecer asistencia proactiva.",
                prioridad=0.55, creada_en=ahora,
                metadata={"origen": "empatia_frustracion", "frustracion": frustracion_usuario}
            ))

        if num_ventanas > 10:
            intenciones.append(Intencion(
                id=f"sobrecarga_{int(ahora*1000)}",
                tipo=IntencionTipo.PREGUNTAR,
                descripcion="Muchas ventanas abiertas. Ofrecer organizar o cerrar inactivas.",
                prioridad=0.35, creada_en=ahora,
                metadata={"origen": "sobrecarga_ventanas", "num_ventanas": num_ventanas}
            ))

        apps_creativas = ["photoshop", "blender", "gimp", "illustrator", "vs code",
                           "visual studio", "intellij", "pycharm", "unity", "obsidian"]
        if tiempo_app > 600 and any(a in app.lower() for a in apps_creativas):
            if contexto_actual.get("enfoque_usuario", 0.5) < 0.5:
                intenciones.append(Intencion(
                    id=f"bloqueo_creativo_{int(ahora*1000)}",
                    tipo=IntencionTipo.PREGUNTAR,
                    descripcion="Posible bloqueo creativo. Ofrecer brainstorming o descanso.",
                    prioridad=0.3, creada_en=ahora,
                    metadata={"origen": "bloqueo_creativo", "tiempo_app": tiempo_app}
                ))

        if energia_usuario < 0.3 and (hora >= 14 or hora <= 3):
            intenciones.append(Intencion(
                id=f"baja_energia_{int(ahora*1000)}",
                tipo=IntencionTipo.PREGUNTAR,
                descripcion="El usuario muestra baja energía. Sugerir pausa o café.",
                prioridad=0.25, creada_en=ahora,
                metadata={"origen": "baja_energia", "energia": energia_usuario}
            ))

        return intenciones

    def registrar_interaccion_exitosa(self, app: str, hora: int, dia: int, accion_realizada: str):
        hora_rango = f"{hora}:00-{(hora+1)%24}:00"
        self.memoria.guardar_o_actualizar_patron(
            patron=f"interaccion_{accion_realizada}", app=app,
            hora_rango=hora_rango, dia_semana=dia, accion_sugerida=accion_realizada
        )


# =============================================================================
# 6. EJECUTOR CON LATIDO COGNITIVO HUMANO
# =============================================================================

class Ejecutor:
    def __init__(self):
        self.actuadores: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._ollama_fallback = None
        # Referencia a memoria para poder guardar propuestas pendientes
        # (ver _proponer_confirmacion) incluso ANTES de que conectar_vision()
        # reemplace esto por un EjecutorMejorado. Sin esto, una meta propia
        # que requiere confirmación se decía en voz alta pero se perdía:
        # nunca quedaba nada para que el usuario pudiera confirmar después.
        self.memoria = None
        self._ultima_ejecucion: Dict[str, float] = {}
        self._cooldown_ejecucion = 4.0
        self._ultima_respuesta_autonoma = ""
        self._ultima_respuesta_timestamp = 0
        self._cooldown_respuesta_similar = 10.0
        # Piso mínimo entre dos intervenciones autónomas seguidas, sin
        # importar qué subsistema las generó (latido_espontaneo, predictor
        # contextual, saludo, etc.). Ligeramente por debajo del cooldown de
        # 50s del latido para no pisarlo, pero muy por encima de los 4s/15s
        # que dejaban pasar ráfagas del predictor.
        self._cooldown_habla_autonoma_global = 45.0
        self._personalidad = None
        self._esta_hablando_cb = None

    def registrar_actuador(self, nombre: str, funcion: Callable):
        self.actuadores[nombre] = funcion

    def set_memoria(self, memoria):
        self.memoria = memoria

    def set_ollama_fallback(self, callback: Callable):
        self._ollama_fallback = callback

    def set_personalidad(self, gestor):
        self._personalidad = gestor

    def set_esta_hablando(self, callback: Callable):
        """Callback que devuelve True si Nova está hablando ahora mismo (TTS en
        curso). Nos deja evitar que el latido cognitivo genere nuevas intenciones
        de hablar mientras ya está sonando una frase, que era la causa real de
        las ráfagas y los 'ROMPO EL SILENCIO' que nunca llegaban a sonar."""
        self._esta_hablando_cb = callback

    # =================================================================
    # UNIFICACIÓN DEL "CEREBRO" — clasificar orden vs. charla ACÁ, no en
    # nova_asistente.py.
    # =================================================================
    # ANTES: nova_asistente.py tenía su propio camino paralelo
    # (_decidir_y_responder -> _intentar_ejecutar_skill_llm / responder_llm)
    # que corría en un hilo separado, AL MISMO TIEMPO que este Ejecutor
    # procesaba la misma Percepcion 'texto_usuario' vía RESPONDER_USUARIO.
    # Los dos podían hablar por su cuenta sobre el mismo pedido del
    # usuario, sin enterarse uno del otro (de ahí las respuestas
    # contradictorias: "Listo, ya ejecuté X" seguido de "no puedo hacer
    # eso"). Ahora este único método decide, ACÁ, si el texto del usuario
    # es una orden ejecutable o charla — y ejecutar() más abajo actúa en
    # consecuencia sin que nadie más necesite decidir nada por su cuenta.
    model_planificador = "qwen2.5:3b-instruct"  # cambiable desde afuera
    MAX_PASOS_ACCION = 5  # techo duro: nunca encadenar más de N pasos por pedido

    def _decidir_siguiente_paso(self, texto_usuario: str, historial: List[Dict]) -> Optional[dict]:
        """Le pregunta al modelo UN paso por vez, mostrándole qué se hizo
        hasta ahora (si algo). Devolver el plan completo de una sola vez es
        justo el tipo de tarea donde un modelo chico (3B) suele inventar
        pasos o argumentos — pedir 'solo el próximo paso' con el resultado
        real del anterior a la vista es mucho más confiable."""
        if not NOVA_SKILLS_AVAILABLE or not OLLAMA_AVAILABLE:
            return None
        try:
            catalogo = "\n".join(
                f"- {nombre}: {SkillRegistry.describir(nombre)}"
                for cat in SkillRegistry.categorias()
                for nombre in SkillRegistry.listar(cat)
            )
        except Exception:
            return None

        if historial:
            lineas = []
            for i, paso in enumerate(historial, 1):
                estado = "bien" if paso["ok"] else "FALLÓ"
                lineas.append(f"{i}. {paso['skill']}(args={paso['args']}) -> {estado}: {paso['mensaje']}")
            bloque_historial = (
                "\nPasos que YA se ejecutaron para este mismo pedido, en orden:\n"
                + "\n".join(lineas) + "\n"
            )
        else:
            bloque_historial = "\nTodavía no se ejecutó ningún paso para este pedido.\n"

        # Memoria de intentos: solo se consulta en el PRIMER paso de este
        # pedido (con historial vacío) — no tiene sentido repreguntarle a la
        # DB lo mismo en cada paso de una misma cadena ya en curso. Esto es
        # lo que le permite a Nova no repetir a ciegas un error que ya
        # cometió con un pedido parecido antes.
        bloque_memoria = ""
        if not historial and self.memoria:
            try:
                previos = self.memoria.buscar_intentos_similares(texto_usuario, limite=4)
            except Exception:
                previos = []
            if previos:
                lineas_prev = []
                for p in previos:
                    estado = "funcionó" if p["ok"] else "FALLÓ"
                    lineas_prev.append(
                        f"- Pedido parecido \"{p['pedido'][:60]}\": se probó "
                        f"{p['skill']}(args={p['args']}) y {estado}"
                        + (f" ({p['mensaje'][:60]})" if not p["ok"] else "")
                    )
                bloque_memoria = (
                    "\nDe pedidos parecidos anteriores, esto es lo que ya se sabe "
                    "(no repitas un intento que ya FALLÓ de la misma forma; si algo "
                    "funcionó antes, es una buena señal de que sigue siendo válido):\n"
                    + "\n".join(lineas_prev) + "\n"
                )

        prompt_router = (
            "Sos el módulo de decisión de Nova, un asistente que controla una PC. "
            "Un pedido puede necesitar VARIOS pasos encadenados (ej: 'abrí el bloc de "
            "notas y escribí X' son DOS pasos). Tu trabajo es decidir, de a UNO por vez, "
            "cuál es el próximo paso que falta.\n\n"
            "Esta es la lista de HABILIDADES disponibles (nombre: descripción):\n"
            f"{catalogo}\n"
            f"{bloque_historial}"
            f"{bloque_memoria}\n"
            "REGLA MÁS IMPORTANTE: solo es 'skill' si el usuario pidió explícitamente que "
            "HAGAS algo. Si el pedido es charla, pregunta, u opinión sin ninguna acción "
            "concreta, respondé 'hablar'. Si YA se cumplió todo lo que pidió el usuario con "
            "los pasos de arriba, respondé 'terminado'. Si un paso necesario falló y no hay "
            "forma de seguir, también respondé 'terminado'.\n\n"
            "REGLA CLAVE — 'escribir' puede significar DOS cosas MUY distintas, no las "
            "confundas por la palabra usada (aunque el usuario diga 'crear'/'crea'):\n"
            "  (a) Si el usuario habla de 'el bloc de notas', 'notepad', o cualquier "
            "aplicación que VE en pantalla y quiere que el texto aparezca tipeado ahí "
            "delante suyo -> usá SIEMPRE abrir_aplicacion('notepad.exe') primero, y "
            "escribir_texto(...) después (simula tipeo real, visible). NUNCA uses "
            "crear_archivo/escribir_archivo para esto, aunque el usuario diga 'crea' — "
            "esas dos escriben directo a un archivo en disco, invisibles, y el usuario "
            "se queda mirando una ventana vacía.\n"
            "  (b) Solo usá crear_archivo/escribir_archivo cuando el usuario pida "
            "explícitamente 'guardar un archivo' o 'un archivo de texto' SIN mencionar "
            "el bloc de notas ni ninguna ventana que quiera ver.\n"
            "Si necesitás escribir_archivo más de una vez para el MISMO archivo en esta "
            "misma cadena de pasos, usá kwargs={\"modo\": \"a\"} a partir del segundo "
            "llamado (modo 'w', el default, BORRA lo que ya habías escrito antes).\n\n"
            "REGLA DE PRECISIÓN — muy importante, no la ignores: algunas skills solo dan "
            "PASOS RELATIVOS (ej. subir_volumen/bajar_volumen aprietan la tecla N veces, "
            "no saben poner un valor exacto). Si el usuario pidió un VALOR EXACTO concreto "
            "(un número, un porcentaje) y NINGUNA skill de la lista de arriba puede fijar "
            "ese valor exacto directamente, NO uses la skill aproximada de todos modos — "
            "respondé {\"tipo\": \"necesita_visual\"} para que Nova mire la pantalla y ajuste "
            "el control (deslizador, campo, lo que sea) directamente con clics/arrastre, "
            "como con cualquier otro control de cualquier programa. Es mejor eso que un "
            "valor aproximado o inventado.\n\n"
            "Ejemplos:\n"
            'Pedido: "sube el volumen" (sin pasos previos) -> {"tipo": "skill", "skill": "subir_volumen", "args": [], "kwargs": {}}\n'
            'Pedido: "pon el volumen al 80%" (sin pasos previos, no hay skill de valor exacto) -> {"tipo": "necesita_visual"}\n'
            'Pedido: "abre el bloc de notas y escribe hola" (sin pasos previos) -> '
            '{"tipo": "skill", "skill": "abrir_aplicacion", "args": ["notepad.exe"], "kwargs": {}}\n'
            'Pedido: "abre el bloc de notas y escribe hola" (ya se ejecutó abrir_aplicacion con éxito) -> '
            '{"tipo": "skill", "skill": "escribir_texto", "args": ["hola"], "kwargs": {}}\n'
            'Pedido: "abre el bloc de notas y escribe hola" (ya se ejecutaron ambos pasos con éxito) -> {"tipo": "terminado"}\n'
            'Pedido: "crea un blog de notas y escribe tus habilidades" (sin pasos previos) -> '
            '{"tipo": "skill", "skill": "abrir_aplicacion", "args": ["notepad.exe"], "kwargs": {}}\n'
            '(mismo pedido, ya se abrió notepad) -> {"tipo": "skill", "skill": "escribir_texto", '
            '"args": ["Puedo: abrir aplicaciones, escribir texto, mover el mouse..."], "kwargs": {}}\n\n'
            f'Pedido real del usuario: "{texto_usuario}"\n\n'
            "Respondé ÚNICAMENTE con un JSON, sin texto extra, en uno de estos formatos:\n"
            '{"tipo": "skill", "skill": "nombre_exacto_de_la_lista", "args": [], "kwargs": {}}\n'
            '{"tipo": "necesita_visual"}\n'
            '{"tipo": "terminado"}\n'
            '{"tipo": "hablar"}\n'
            "No inventes nombres de skills que no estén en la lista. Si te falta un dato "
            "para un argumento (ej. qué texto escribir exactamente), generalo vos mismo "
            "dentro de lo que pidió el usuario — no preguntes, decidí."
        )
        try:
            res = ollama.generate(
                model=self.model_planificador, prompt=prompt_router,
                options={"temperature": 0.0, "num_predict": 260},
            )
            crudo = res["response"].strip()
            inicio, fin = crudo.find("{"), crudo.rfind("}")
            if inicio == -1 or fin == -1:
                return None
            return json.loads(crudo[inicio:fin + 1])
        except Exception as e:
            debug_mente(f"[MENTE] Planificador de pasos no devolvió JSON válido ({e})")
            return None

    model_vision = "gemma3:4b"  # cambiable desde afuera, mismo modelo que ya usás para "ver"

    # Acciones GENÉRICAS de mouse/teclado que el respaldo visual puede usar
    # sin necesitar una skill nueva por cada tarea posible. Todas ya existen
    # en nova_skills/raton.py y teclado.py.
    _ACCIONES_VISUALES_PERMITIDAS = {
        "click", "doble_click", "click_derecho", "mover_mouse",
        "arrastrar", "scroll_arriba", "scroll_abajo",
        "escribir_texto", "presionar_tecla", "combinacion_teclas",
    }

    def _decidir_siguiente_paso_visual(self, texto_usuario: str, historial: List[Dict]) -> Optional[dict]:
        """Respaldo genérico de 'ver y actuar': cuando ninguna skill CON
        NOMBRE encaja con el pedido, Nova saca una captura de pantalla real,
        se la muestra al modelo de visión, y le pregunta cuál es el próximo
        clic/tipeo/tecla concreto — en vez de necesitar que yo (o quien
        programe Nova) haya anticipado y escrito una función para esa tarea
        exacta de antemano. Esto es más lento y menos preciso que una skill
        con nombre (por eso es un RESPALDO, no el camino principal), pero le
        da a Nova alcance sobre cualquier cosa que se pueda hacer con mouse
        y teclado, no solo lo que ya tiene programado."""
        if not OLLAMA_AVAILABLE or "screenshot" not in self.actuadores:
            return None

        try:
            img_path = self.actuadores["screenshot"]()
            if not img_path or not os.path.exists(img_path):
                return None
        except Exception as e:
            debug_mente(f"[MENTE] Respaldo visual: no se pudo capturar pantalla ({e})")
            return None

        try:
            from PIL import Image
            with Image.open(img_path) as im:
                ancho_img, alto_img = im.size
        except Exception:
            ancho_img, alto_img = None, None

        ancho_real, alto_real = ancho_img, alto_img
        try:
            import pyautogui
            ancho_real, alto_real = pyautogui.size()
        except Exception:
            pass  # sin pyautogui no podemos escalar coordenadas: asumimos 1:1

        # Reescala "espacio de la imagen" -> "espacio real de pantalla" (la
        # captura puede venir reducida — ver tomar_captura_pantalla en
        # nova_asistente.py, que la achica a un máximo de 1024px). Se calcula
        # ACÁ (temprano) porque hace falta tanto para mostrarle al modelo el
        # historial en un espacio consistente, como más abajo para escalar
        # de verdad las coordenadas que se van a ejecutar.
        escala_x = (ancho_real / ancho_img) if (ancho_img and ancho_real) else 1.0
        escala_y = (alto_real / alto_img) if (alto_img and alto_real) else 1.0

        _ACCIONES_CON_COORDENADAS = {"click", "doble_click", "click_derecho", "mover_mouse", "arrastrar"}

        if historial:
            lineas = []
            for i, p in enumerate(historial, 1):
                args_mostrados = p['args']
                # Los pasos previos de este MISMO respaldo visual guardan las
                # coordenadas ya reescaladas a pantalla real (son las que de
                # verdad se ejecutaron). Se las mostramos de vuelta al modelo
                # en espacio de IMAGEN (dividiendo por la escala) — el mismo
                # espacio en el que está razonando ahora mismo — para que no
                # las reinterprete como si fueran números nuevos de la imagen
                # chica y las vuelva a escalar él solo (eso era justo lo que
                # hacía que el x,y se disparara sin control en cadenas largas:
                # 2216 -> 2250 -> 4219 -> 7911...).
                if p['skill'] in _ACCIONES_CON_COORDENADAS and escala_x and escala_y:
                    try:
                        args_mostrados = [
                            round(v / escala_x) if idx % 2 == 0 else round(v / escala_y)
                            for idx, v in enumerate(p['args'])
                        ]
                    except (TypeError, ZeroDivisionError):
                        args_mostrados = p['args']
                lineas.append(f"{i}. {p['skill']}(args={args_mostrados}) -> {'bien' if p['ok'] else 'FALLÓ'}")
            bloque_historial = "\nPasos ya ejecutados para este pedido:\n" + "\n".join(lineas) + "\n"
        else:
            bloque_historial = "\nTodavía no se ejecutó ningún paso.\n"

        bloque_memoria = ""
        if not historial and self.memoria:
            try:
                previos = self.memoria.buscar_intentos_similares(texto_usuario, limite=3)
            except Exception:
                previos = []
            if previos:
                lineas_prev = [
                    f"- \"{p['pedido'][:50]}\": {p['skill']}(args={p['args']}) "
                    + ("funcionó" if p["ok"] else f"FALLÓ ({p['mensaje'][:50]})")
                    for p in previos
                ]
                bloque_memoria = (
                    "\nIntentos parecidos anteriores (no repitas exactamente un clic/paso "
                    "que ya falló, la pantalla puede haberse movido igual desde entonces):\n"
                    + "\n".join(lineas_prev) + "\n"
                )

        dims_txt = f"{ancho_img}x{alto_img}" if ancho_img else "desconocidas"
        prompt_visual = (
            "Sos el módulo de decisión VISUAL de Nova. Mirá la captura de pantalla adjunta y "
            "decidí el PRÓXIMO paso concreto (uno solo) para cumplir el pedido del usuario, "
            "usando SOLO estas acciones genéricas:\n"
            "- click: hacer clic en un punto (x, y)\n"
            "- doble_click: doble clic en (x, y)\n"
            "- click_derecho: clic derecho en (x, y)\n"
            "- escribir_texto: tipear texto (requiere que ya haya foco en el lugar correcto)\n"
            "- presionar_tecla: presionar una tecla (ej. 'enter', 'esc', 'tab')\n"
            "- combinacion_teclas: combinación simultánea (ej. ['ctrl','s'])\n"
            "- scroll_arriba / scroll_abajo: desplazar la vista\n"
            "- arrastrar: arrastrar de (x1,y1) a (x2,y2)\n\n"
            f"La captura mide {dims_txt} píxeles — las coordenadas x,y que des tienen que estar "
            "DENTRO de ese rango, mirando exactamente dónde está el elemento en la imagen.\n"
            f"{bloque_historial}"
            f"{bloque_memoria}\n"
            f'Pedido del usuario: "{texto_usuario}"\n\n'
            "Si ya se cumplió el pedido, respondé {\"tipo\": \"terminado\"}.\n"
            "Si esto no se puede resolver con clics/tipeo sobre lo que se ve en pantalla, "
            "respondé {\"tipo\": \"hablar\"}.\n"
            "Si falta un paso, respondé ÚNICAMENTE JSON en uno de estos formatos:\n"
            '{"tipo": "accion", "accion": "click", "x": 123, "y": 456}\n'
            '{"tipo": "accion", "accion": "escribir_texto", "texto": "..."}\n'
            '{"tipo": "accion", "accion": "presionar_tecla", "tecla": "enter"}\n'
            '{"tipo": "accion", "accion": "combinacion_teclas", "teclas": ["ctrl", "s"]}\n'
            "Sin texto extra, sin explicaciones."
        )

        try:
            res = ollama.generate(
                model=self.model_vision, prompt=prompt_visual, images=[img_path],
                options={"temperature": 0.0, "num_predict": 260},
            )
            crudo = res["response"].strip()
            inicio, fin = crudo.find("{"), crudo.rfind("}")
            if inicio == -1 or fin == -1:
                return None
            decision = json.loads(crudo[inicio:fin + 1])
        except Exception as e:
            debug_mente(f"[MENTE] Respaldo visual no devolvió JSON válido ({e})")
            return None
        finally:
            try:
                os.remove(img_path)
            except Exception:
                pass

        tipo = decision.get("tipo")
        if tipo in ("terminado", "hablar"):
            return {"tipo": tipo}
        if tipo != "accion":
            return None

        accion = decision.get("accion")
        if accion not in self._ACCIONES_VISUALES_PERMITIDAS:
            return None

        def _coordenada_segura(valor, ancho_origen, escala, ancho_destino):
            """Tope duro en DOS niveles: primero recorta el valor crudo que
            dio el modelo contra el tamaño de la IMAGEN que vio (evita que
            un número ya delirante de entrada se siga arrastrando), y
            después, ya escalado, lo vuelve a recortar contra la pantalla
            REAL. Pase lo que pase con el razonamiento del modelo (¿vio mal
            la imagen? ¿reinterpretó un número del historial que ya estaba
            en espacio real?), esto garantiza que nunca se intente ejecutar
            un clic fuera de los límites reales de la pantalla — que es
            justo lo que veníamos viendo escalar sin control (2216 -> 2250
            -> 4219 -> 7911...) en cadenas de varios pasos.

            MARGEN: se deja un margen de unos pocos píxeles respecto a las
            esquinas EXACTAS (0,0 / ancho-1,alto-1 / etc.) — pyautogui tiene
            su propio freno de seguridad (FAILSAFE) que aborta cualquier
            acción si el mouse llega a una esquina de la pantalla, pensado
            para que un usuario humano pueda frenar un script descontrolado
            arrastrando el mouse ahí a propósito. Sin este margen, el
            recorte anterior podía terminar mandando el mouse EXACTO a esa
            esquina y disparando ese freno como si fuera un error."""
            MARGEN = 8
            if ancho_origen:
                valor = max(0, min(valor, ancho_origen))
            escalado = valor * escala
            if ancho_destino:
                escalado = max(MARGEN, min(escalado, ancho_destino - 1 - MARGEN))
            return round(escalado)

        if accion in ("click", "doble_click", "click_derecho", "mover_mouse"):
            x = decision.get("x")
            y = decision.get("y")
            if x is None or y is None:
                return None
            return {"tipo": "skill", "skill": accion,
                    "args": [_coordenada_segura(x, ancho_img, escala_x, ancho_real),
                             _coordenada_segura(y, alto_img, escala_y, alto_real)], "kwargs": {}}
        if accion == "arrastrar":
            x1, y1, x2, y2 = decision.get("x1"), decision.get("y1"), decision.get("x2"), decision.get("y2")
            if None in (x1, y1, x2, y2):
                return None
            return {"tipo": "skill", "skill": "arrastrar",
                    "args": [_coordenada_segura(x1, ancho_img, escala_x, ancho_real),
                             _coordenada_segura(y1, alto_img, escala_y, alto_real),
                             _coordenada_segura(x2, ancho_img, escala_x, ancho_real),
                             _coordenada_segura(y2, alto_img, escala_y, alto_real)], "kwargs": {}}
        if accion == "escribir_texto":
            texto = decision.get("texto", "")
            return {"tipo": "skill", "skill": "escribir_texto", "args": [texto], "kwargs": {}}
        if accion == "presionar_tecla":
            return {"tipo": "skill", "skill": "presionar_tecla", "args": [decision.get("tecla", "")], "kwargs": {}}
        if accion == "combinacion_teclas":
            teclas = decision.get("teclas") or []
            return {"tipo": "skill", "skill": "combinacion_teclas", "args": list(teclas), "kwargs": {}}
        if accion in ("scroll_arriba", "scroll_abajo"):
            return {"tipo": "skill", "skill": accion, "args": [], "kwargs": {}}
        return None

    # =================================================================
    # TRABAJOS LARGOS (Word de varias páginas) — ÍNDICE -> SECCIONES
    # =================================================================
    # Pedirle a un modelo de 3B que escriba 50 páginas de corrido, todo en
    # una sola respuesta, es pedirle algo que ningún modelo de ese tamaño
    # hace bien: se repite, pierde el hilo, se contradice. En vez de eso:
    # primero se genera un ÍNDICE (lista de secciones), y DESPUÉS cada
    # sección se genera y se escribe por separado — una tarea mucho más
    # chica y manejable en cada llamada al modelo.
    DISPARADORES_TRABAJO_LARGO = [
        "páginas", "paginas", "trabajo de", "trabajo sobre", "ensayo",
        "informe", "monografía", "monografia", "tesis", "documento completo",
        "trabajo completo", "redacción completa", "redaccion completa",
        "trabajo largo", "documento largo", "documento extenso",
        # Frases más sueltas, como las dice la gente en la práctica:
        "un trabajo", "hagas un trabajo", "trabajo en word", "trabajo en un word",
        "en un word", "en word de", "documento word", "archivo word",
    ]

    def _necesita_trabajo_largo(self, texto_usuario: str) -> bool:
        t = texto_usuario.lower()
        return any(d in t for d in self.DISPARADORES_TRABAJO_LARGO)

    def _pedir_indice_trabajo(self, texto_usuario: str) -> Optional[List[str]]:
        """Un solo llamado al modelo para decidir la ESTRUCTURA del trabajo
        (4 a 8 secciones), antes de escribir una sola palabra de contenido."""
        if not OLLAMA_AVAILABLE:
            return None
        prompt_indice = (
            "Sos un asistente que arma la estructura de trabajos escritos "
            "académicos. Dado este pedido del usuario, devolvé el ÍNDICE de "
            "secciones que debería tener, en español, en orden lógico "
            "(típicamente: introducción, 2-5 secciones de desarrollo "
            "específicas del tema, y conclusión).\n\n"
            f'Pedido: "{texto_usuario}"\n\n'
            "Respondé ÚNICAMENTE con este JSON, sin texto extra:\n"
            '{"secciones": ["Introducción", "...", "Conclusión"]}'
        )
        try:
            res = ollama.generate(
                model=self.model_planificador, prompt=prompt_indice,
                options={"temperature": 0.3, "num_predict": 220},
            )
            crudo = res["response"].strip()
            inicio, fin = crudo.find("{"), crudo.rfind("}")
            if inicio == -1 or fin == -1:
                return None
            data = json.loads(crudo[inicio:fin + 1])
            secciones = [s.strip() for s in (data.get("secciones") or []) if isinstance(s, str) and s.strip()]
            return secciones[:10] or None
        except Exception as e:
            debug_mente(f"[MENTE] No se pudo generar el índice del trabajo ({e})")
            return None

    def _generar_con_groq(self, prompt: str, max_tokens: int = 800) -> Optional[str]:
        """Le pide contenido a Groq (openai/gpt-oss-120b, gratis con cuenta,
        sin tarjeta) en vez del modelo local — mejor calidad para tareas que
        lo ameritan (como el contenido de un trabajo largo). Devuelve None si
        algo falla (sin key, sin internet, error de la API) — el llamador
        debe caer al modelo local en ese caso, nunca romper por esto.

        La API key se lee de la variable de entorno GROQ_API_KEY — NUNCA
        hardcodeada acá. Configurala una vez con (PowerShell):
            setx GROQ_API_KEY "tu_key_acá"
        y abrí una terminal nueva para que la vea."""
        if not REQUESTS_AVAILABLE:
            return None

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return None  # no configurada -> ni lo intentamos, directo al local

        try:
            respuesta = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-oss-120b",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.6,
                },
                timeout=30,
            )
            if respuesta.status_code != 200:
                debug_mente(f"[MENTE] Groq devolvió error {respuesta.status_code}: {respuesta.text[:200]}")
                return None

            datos = respuesta.json()
            return datos["choices"][0]["message"]["content"].strip()

        except Exception as e:
            debug_mente(f"[MENTE] Groq no respondió ({e}), cae al modelo local")
            return None

    def _generar_contenido_seccion(self, texto_usuario: str, seccion: str) -> str:
        """Un llamado al modelo POR SECCIÓN — tarea chica y acotada, mucho
        más confiable que pedir el trabajo entero de una vez. Primero
        intenta con Groq (mejor calidad, gratis); si no hay key configurada
        o falla por lo que sea, cae al modelo local sin que el usuario note
        más que una respuesta un poco menos pulida."""
        prompt_seccion = (
            f'Pedido original del usuario: "{texto_usuario}"\n\n'
            f"Escribí el CONTENIDO en español para la sección \"{seccion}\" de "
            "ese trabajo: varios párrafos de texto corrido, sin subtítulos ni "
            "viñetas, sin repetir el título de la sección dentro del texto. "
            "Desarrollá el tema con sustancia real, no rellenes con frases "
            "genéricas vacías."
        )

        contenido_groq = self._generar_con_groq(prompt_seccion, max_tokens=800)
        if contenido_groq:
            return contenido_groq

        if not OLLAMA_AVAILABLE:
            return ""
        try:
            res = ollama.generate(
                model=self.model_planificador, prompt=prompt_seccion,
                options={"temperature": 0.6, "num_predict": 500},
            )
            return res["response"].strip()
        except Exception as e:
            debug_mente(f"[MENTE] No se pudo generar contenido de la sección '{seccion}' ({e})")
            return ""

    def _intentar_como_trabajo_largo(self, texto_usuario: str, intencion_original: 'Intencion') -> Optional[Dict]:
        """Driver dedicado para trabajos largos: crea el documento, pide el
        índice, y genera+escribe sección por sección. Devuelve None si esto
        no aplica (no se detectó pedido de trabajo largo, o falta el módulo
        de documentos) — en ese caso el llamador sigue con el camino normal
        de _intentar_como_accion."""
        if not self._necesita_trabajo_largo(texto_usuario):
            return None
        if not NOVA_SKILLS_AVAILABLE or "crear_documento_word" not in SkillRegistry.listar():
            debug_mente("[MENTE] Se pidió un trabajo largo pero nova_skills/documentos.py no está disponible")
            return None

        secciones = self._pedir_indice_trabajo(texto_usuario)
        if not secciones:
            return None  # cae al camino normal (loop corto de siempre)

        def _paso(nombre_skill: str, args: list, kwargs: dict, descripcion: str) -> Dict:
            intencion = Intencion(
                id=f"trabajo_{nombre_skill}_{int(time.time()*1000)}",
                tipo=IntencionTipo.EJECUTAR_TAREA, descripcion=descripcion,
                prioridad=intencion_original.prioridad, creada_en=time.time(),
                metadata={"skill": nombre_skill, "args": args, "kwargs": kwargs, "origen": "usuario_directo"},
            )
            r = self._ejecutar_tarea(intencion)
            if self.memoria:
                try:
                    self.memoria.registrar_intento_accion(
                        pedido=texto_usuario, skill=nombre_skill, args=args, kwargs=kwargs,
                        ok=r["ok"], mensaje=r["mensaje"], origen="trabajo_largo",
                    )
                except Exception:
                    pass
            return r

        # 1) Carpeta destino: Documentos del usuario.
        r_carpeta = _paso("obtener_ruta_documentos", [], {}, "Ubicar carpeta de Documentos")
        carpeta = r_carpeta.get("resultado_valor") or "."

        # 2) Nombre de archivo: derivado del pedido, saneado, corto y legible.
        palabras = [w for w in re.sub(r'[^\w\sáéíóúñÁÉÍÓÚÑ]', '', texto_usuario).split() if w.lower() not in
                    ("un", "una", "el", "la", "de", "en", "que", "crea", "hazme", "quiero", "para", "a", "y")]
        base = "_".join(palabras[:6]) or "trabajo"
        ruta = os.path.join(carpeta, base + ".docx")

        pasos_hechos = []

        r_crear = _paso("crear_documento_word", [ruta, base], {}, "Crear el documento")
        pasos_hechos.append(r_crear)
        if not r_crear["ok"]:
            mensaje = f"No pude ni siquiera crear el documento: {r_crear['mensaje']}"
            return {"ok": False, "mensaje": mensaje, "skill": "crear_documento_word", "pasos": pasos_hechos}

        for seccion in secciones:
            contenido = self._generar_contenido_seccion(texto_usuario, seccion)
            r_titulo = _paso("agregar_titulo_word", [ruta, seccion], {"nivel": 1}, f"Agregar sección '{seccion}'")
            pasos_hechos.append(r_titulo)
            if contenido:
                r_parrafo = _paso("agregar_parrafo_word", [ruta, contenido], {}, f"Escribir contenido de '{seccion}'")
                pasos_hechos.append(r_parrafo)

        exitos = [p for p in pasos_hechos if p["ok"]]
        fallos = [p for p in pasos_hechos if not p["ok"]]
        if fallos and len(exitos) <= 1:
            mensaje = f"El trabajo falló casi de entrada: {fallos[0]['mensaje']}"
        elif fallos:
            mensaje = f"Armé el trabajo en {ruta} con {len(secciones)} secciones, aunque {len(fallos)} paso(s) fallaron a mitad de camino."
        else:
            mensaje = f"Listo, armé el trabajo completo en {ruta}, con {len(secciones)} secciones: {', '.join(secciones)}."

        return {"ok": not fallos or len(exitos) > 1, "mensaje": mensaje, "skill": "trabajo_largo", "pasos": pasos_hechos}

    def _intentar_como_accion(self, texto_usuario: str, intencion_original: 'Intencion') -> Optional[Dict]:
        """Reemplaza al viejo _intentar_como_skill: ahora puede encadenar
        VARIOS pasos (hasta MAX_PASOS_ACCION) para un mismo pedido, no solo
        uno. Devuelve None si el primer paso ya fue 'hablar' (no era una
        orden en absoluto) — en ese caso el llamador sigue su camino normal
        de charla. Si se ejecutó al menos un paso, SIEMPRE devuelve un
        resultado real (nunca None), aunque algún paso haya fallado a mitad
        de camino — eso también hay que anunciarlo, no tragárselo en
        silencio."""
        historial: List[Dict] = []

        for paso_num in range(self.MAX_PASOS_ACCION):
            decision = self._decidir_siguiente_paso(texto_usuario, historial)

            if not decision or decision.get("tipo") == "hablar":
                if not historial:
                    return None  # nunca fue una orden: que siga a charla
                break  # ya hicimos algo, pero no hay más pasos claros: cerramos acá

            if decision.get("tipo") == "terminado":
                break

            # El respaldo visual se dispara en DOS casos: (a) el modelo pidió
            # explícitamente 'necesita_visual' (detectó que hace falta un
            # valor exacto que ninguna skill puede fijar), o (b) el modelo
            # devolvió el nombre de una skill que no existe (alucinada) —
            # en vez de rendirse, probamos el mismo camino genérico.
            pide_visual_explicito = decision.get("tipo") == "necesita_visual"
            nombre_skill = None if pide_visual_explicito else decision.get("skill")
            necesita_respaldo = pide_visual_explicito or (
                not NOVA_SKILLS_AVAILABLE or nombre_skill not in SkillRegistry.listar()
            )

            if necesita_respaldo:
                # Nova mira la pantalla de verdad y decide un clic/tipeo/tecla
                # puntual, usando las manos genéricas que YA existen
                # (raton.py, teclado.py) en vez de necesitar una skill nueva
                # por cada tarea o cada valor exacto posible. Ver
                # _decidir_siguiente_paso_visual.
                motivo = "pidió ajuste visual explícito" if pide_visual_explicito else f"sin skill con nombre para '{nombre_skill}'"
                debug_mente(f"[MENTE] Paso {paso_num+1}: {motivo}, probando respaldo visual")
                decision_visual = self._decidir_siguiente_paso_visual(texto_usuario, historial)
                if not decision_visual or decision_visual.get("tipo") in ("hablar", "terminado"):
                    if not historial:
                        return None
                    break
                nombre_skill = decision_visual.get("skill")
                args = decision_visual.get("args") or []
                kwargs = decision_visual.get("kwargs") or {}
                if not NOVA_SKILLS_AVAILABLE or nombre_skill not in SkillRegistry.listar():
                    debug_mente(f"[MENTE] Paso {paso_num+1}: respaldo visual tampoco encontró una skill válida ('{nombre_skill}'), corto la cadena")
                    break
            else:
                args = decision.get("args") or []
                kwargs = decision.get("kwargs") or {}

            try:
                import inspect
                from nova_skills import SKILLS as _SKILLS_DEF
                skill_obj = _SKILLS_DEF.get(nombre_skill)
                if skill_obj:
                    inspect.signature(skill_obj.fn).bind(*args, **kwargs)
            except TypeError as e:
                debug_mente(f"[MENTE] Paso {paso_num+1}: '{nombre_skill}' con argumentos inválidos ({e}), corto la cadena")
                break
            except Exception:
                pass

            intencion_tarea = Intencion(
                id="skill_" + str(int(time.time() * 1000)) + f"_{paso_num}",
                tipo=IntencionTipo.EJECUTAR_TAREA,
                descripcion=f"Paso {paso_num+1} de: {texto_usuario[:50]}",
                prioridad=intencion_original.prioridad,
                creada_en=time.time(),
                metadata={"skill": nombre_skill, "args": args, "kwargs": kwargs, "origen": "usuario_directo"},
            )
            r = self._ejecutar_tarea(intencion_tarea)
            historial.append({"skill": nombre_skill, "args": args, "ok": r["ok"], "mensaje": r["mensaje"]})

            if self.memoria:
                try:
                    self.memoria.registrar_intento_accion(
                        pedido=texto_usuario, skill=nombre_skill, args=args,
                        kwargs=kwargs, ok=r["ok"], mensaje=r["mensaje"],
                        origen="usuario_directo",
                    )
                except Exception:
                    pass

            if not r["ok"]:
                break  # no seguimos encadenando pasos sobre un fallo

        if not historial:
            return None

        exitos = [p for p in historial if p["ok"]]
        fallos = [p for p in historial if not p["ok"]]
        if fallos:
            hechos = ", ".join(p["skill"] for p in exitos) if exitos else "nada"
            mensaje = f"Alcancé a hacer: {hechos}. Pero '{fallos[0]['skill']}' falló: {fallos[0]['mensaje']}"
        elif len(historial) == 1:
            mensaje = f"Listo, ya ejecuté {historial[0]['skill']}."
        else:
            mensaje = "Listo, hice todo: " + " -> ".join(p["skill"] for p in historial) + "."

        return {"ok": not fallos, "mensaje": mensaje, "skill": historial[-1]["skill"], "pasos": historial}

    def _respuesta_reciente_similar(self, respuesta: str) -> bool:
        if not self._ultima_respuesta_autonoma:
            return False
        if time.time() - self._ultima_respuesta_timestamp < self._cooldown_respuesta_similar:
            ultima = self._ultima_respuesta_autonoma[:20].lower()
            actual = respuesta[:20].lower()
            sim = sum(1 for a, b in zip(actual, ultima) if a == b) / max(len(actual), len(ultima), 1)
            return sim > 0.7
        return False

    def ejecutar(self, intencion: Intencion, estado: EstadoEmocional) -> Dict:
        resultado = {"exito": False, "acciones": [], "mensaje": ""}
        ahora = time.time()
        tipo_str = intencion.tipo.name

        # === FRENO GLOBAL: si Nova ya está hablando (TTS en curso), no
        # ejecutamos NINGUNA intención que implique hablar por iniciativa
        # propia. Antes este chequeo solo vivía dentro del bloque
        # 'latido_espontaneo', así que el latido "oficial" respetaba el
        # silencio pero las intenciones autónomas del PredictorContextual
        # (empatia_estres, empatia_frust, sobrecarga_ventanas,
        # bloqueo_creativo, baja_energia — todas PREGUNTAR/AYUDAR normales)
        # pasaban por el camino genérico de abajo, que solo tenía un
        # cooldown de 4s por tipo y ningún chequeo de "ya está hablando".
        # Eso era la causa real de las ráfagas: el predictor actuaba como
        # un segundo latido, sin cooldown compartido con el primero.
        # RESPONDER_USUARIO queda exento porque es una respuesta directa a
        # algo que el usuario acaba de decir, no iniciativa propia.
        # EJECUTAR_TAREA y EXPLORAR_PANTALLA son ACCIONES, no habla: no las
        # frenamos con los cooldowns pensados para "no hablar todo el
        # tiempo" (si no, Nova nunca podría hacer tareas de fondo mientras
        # tiene ganas de charlar). Si una de estas tareas necesita avisar
        # algo (ver _proponer_confirmacion), esa charla puntual ya respeta
        # su propio chequeo de repetición.
        ES_ACCION_SILENCIOSA = intencion.tipo in (IntencionTipo.EJECUTAR_TAREA, IntencionTipo.EXPLORAR_PANTALLA)

        if intencion.tipo != IntencionTipo.RESPONDER_USUARIO and not ES_ACCION_SILENCIOSA and self._esta_hablando_cb:
            try:
                if self._esta_hablando_cb():
                    resultado["mensaje"] = f"{tipo_str} pospuesto: Nova ya está hablando."
                    return resultado
            except Exception:
                pass

        # === COOLDOWN GLOBAL ENTRE CUALQUIER HABLA AUTÓNOMA ===
        # Antes cada fuente de iniciativa (latido, predictor) tenía su propio
        # cooldown aislado (50s vs 15s), así que en la práctica el más corto
        # ganaba y Nova terminaba hablando cada ~15-20s. Ahora hay un piso
        # único compartido: sin importar quién generó la intención, tiene
        # que haber pasado al menos este tiempo desde la última vez que Nova
        # habló por su cuenta.
        if intencion.tipo != IntencionTipo.RESPONDER_USUARIO and not ES_ACCION_SILENCIOSA:
            if (ahora - self._ultima_respuesta_timestamp) < self._cooldown_habla_autonoma_global:
                resultado["mensaje"] = f"{tipo_str} pospuesto: cooldown global de habla autónoma activo."
                return resultado

        # === LATIDO COGNITIVO HUMANO (EVALUACIÓN DE <SILENCIO>) ===
        if intencion.metadata.get("subtipo") == "latido_espontaneo":
            meta = intencion.metadata
            minutos = meta.get("minutos_silencio", 1)
            app = meta.get("app_activa", "el escritorio")
            hora = meta.get("hora", "")
            animo = estado.emocion_dominante.name
            temas_favoritos = meta.get("temas_favoritos") or []
            patron_sugerido = meta.get("patron_sugerido") or ""

            # Bloque de contexto real: si hay temas favoritos guardados o un
            # patrón de comportamiento aprendido para esta app/hora, se lo
            # pasamos al LLM para que la idea que proponga no sea genérica.
            contexto_extra = ""
            if temas_favoritos:
                contexto_extra += f"\nTemas que sabes que le interesan al usuario: {', '.join(temas_favoritos)}."
            if patron_sugerido:
                contexto_extra += f"\nAprendiste este patrón de su comportamiento en este contexto: {patron_sugerido}."

            prompt_evaluacion = f"""Eres Nova: una compañera sumamente alegre, cariñosa, dulce y carismática, muy curiosa y muy habladora. No eres un asistente pasivo, eres proactiva por naturaleza y te encanta la compañía del usuario.
Han pasado {minutos} minutos en silencio. Son las {hora}.
El usuario está interactuando con la ventana: '{app}'. Tu estado de ánimo es {animo}.{contexto_extra}

TU FORMA DE SER:
Te gusta comentar cosas con cariño, hacer bromas, preguntar, opinar, halagar, o proponer una idea, actividad o tema de conversación por tu cuenta, como haría una persona real, extrovertida y encantadora que está en la misma habitación y disfruta muchísimo estar ahí. El silencio total es la EXCEPCIÓN, no la norma.
1. Solo responde ÚNICAMENTE <SILENCIO> si es un momento realmente crítico (por ejemplo, el usuario acaba de escribir algo urgente hace segundos y una interrupción sería claramente inoportuna). Fuera de eso, di algo.
2. En cualquier otro caso —trabajando, en ocio, o inactivo— suelta un comentario breve, cálido, cariñoso, con chispa y, si viene bien, propone algo (una idea, una pregunta curiosa, un plan pequeño) sobre la hora, su actividad, sus temas favoritos, o lo que se te ocurra (MÁXIMO 25 palabras). Si tienes un tema favorito o un patrón de comportamiento arriba, úsalo para proponer algo concreto en vez de algo genérico.

No digas 'Hola', actúa como si ya estuvieran juntos en la habitación.
Respuesta:"""

            FRASES_LATIDO_PROPIAS = list(
                self._personalidad.frases_latido if self._personalidad else GestorPersonalidad.DEFAULTS["frases_latido"]
            )
            # Si tenemos un tema favorito real, lo priorizamos como frase de
            # respaldo en vez de tirar directo a las genéricas: se siente
            # mucho más "ella se acuerda de mí" que reciclar las mismas 10 frases.
            if temas_favoritos:
                tema = random.choice(temas_favoritos)
                FRASES_LATIDO_PROPIAS = [
                    f"Oye, ¿seguimos con lo de {tema}? Se me ocurrió algo que te puede gustar.",
                    f"Me acordé de que te interesa {tema}... ¿hablamos un poco de eso?",
                    f"¿Cómo va todo? Tenía ganas de retomar el tema de {tema} contigo.",
                ] + FRASES_LATIDO_PROPIAS

            respuesta_iniciativa = "<SILENCIO>"
            ollama_disponible = hasattr(self, "_ollama_fallback") and self._ollama_fallback
            if ollama_disponible:
                try:
                    # Pasamos el flag de oclusión para no ensuciar el historial de chat visible
                    respuesta_iniciativa = self._ollama_fallback(prompt_evaluacion, ocluir_historial=True)
                except TypeError:
                    respuesta_iniciativa = self._ollama_fallback(prompt_evaluacion)

            # Detectar "quiere quedarse callada" de forma más tolerante: un
            # modelo chico como llama3.2:1b a veces responde "SILENCIO." o
            # "silencio" sin los símbolos < >. Antes eso no se reconocía y
            # Nova terminaba diciendo la palabra "SILENCIO" en voz alta.
            respuesta_normalizada = re.sub(r'[<>."\'!¡¿?\s]', '', respuesta_iniciativa).strip().lower()
            quiso_silencio = respuesta_normalizada == "silencio" or "<silencio>" in respuesta_iniciativa.lower()

            debe_forzar_frase_propia = (not ollama_disponible) or (
                quiso_silencio or len(respuesta_iniciativa.strip()) < 3
            )
            debug_mente(f"[MENTE] 🔍 DEBUG actuadores disponibles: {list(self.actuadores.keys())} (id={id(self.actuadores)})")
            # CORRECCIÓN DE BUG: antes había una probabilidad (0.75, luego 0.9) de que,
            # incluso "debiendo forzar" una frase propia, cayera igual en la rama de
            # "silencio respetuoso" y Nova se quedara callada por completo. Eso hacía
            # que el latido cognitivo pensara ("[LATIDO COGNITIVO]" en consola) pero no
            # siempre hablara. Ahora: si debe_forzar_frase_propia es True, Nova SIEMPRE
            # dice algo (nunca cae en el camino del silencio). Solo se queda callada de
            # verdad cuando el LLM, teniendo la oportunidad, decide activamente <SILENCIO>
            # (es decir, cuando debe_forzar_frase_propia es False y aun así respondió silencio,
            # lo cual ya no puede pasar porque esa condición está incluida arriba).
            if debe_forzar_frase_propia:
                limpia = random.choice(FRASES_LATIDO_PROPIAS)
                intentos = 0
                while self._respuesta_reciente_similar(limpia) and intentos < 5:
                    limpia = random.choice(FRASES_LATIDO_PROPIAS)
                    intentos += 1
                if "hablar" in self.actuadores:
                    self.actuadores["hablar"](limpia)
                resultado["exito"] = True
                resultado["acciones"].append("hablar_espontaneo")
                resultado["mensaje"] = limpia
                self._ultima_respuesta_autonoma = limpia
                self._ultima_respuesta_timestamp = time.time()
                print(f"[LATIDO COGNITIVO 💖] ROMPO EL SILENCIO (frase propia): '{limpia}'")
                estado.aburrimiento = max(0.0, estado.aburrimiento - 0.4)
            else:
                limpia = respuesta_iniciativa.replace('"','').replace('<SILENCIO>','').strip()
                if not self._respuesta_reciente_similar(limpia):
                    if "hablar" in self.actuadores:
                        self.actuadores["hablar"](limpia)
                    resultado["exito"] = True
                    resultado["acciones"].append("hablar_espontaneo")
                    resultado["mensaje"] = limpia
                    self._ultima_respuesta_autonoma = limpia
                    self._ultima_respuesta_timestamp = time.time()
                    print(f"[LATIDO COGNITIVO 💖] ROMPO EL SILENCIO: '{limpia}'")
                    estado.aburrimiento = max(0.0, estado.aburrimiento - 0.4)
                else:
                    # Frase real del LLM pero muy parecida a la última: elegimos una frase
                    # propia en vez de quedarnos calladas del todo.
                    limpia = random.choice(FRASES_LATIDO_PROPIAS)
                    if "hablar" in self.actuadores:
                        self.actuadores["hablar"](limpia)
                    resultado["exito"] = True
                    resultado["acciones"].append("hablar_espontaneo")
                    resultado["mensaje"] = limpia
                    self._ultima_respuesta_autonoma = limpia
                    self._ultima_respuesta_timestamp = time.time()
                    print(f"[LATIDO COGNITIVO 💖] ROMPO EL SILENCIO (fallback por repetición): '{limpia}'")
                    estado.aburrimiento = max(0.0, estado.aburrimiento - 0.4)
            return resultado


        # Cooldown por tipo de intención estándar
        if tipo_str in self._ultima_ejecucion:
            if ahora - self._ultima_ejecucion[tipo_str] < self._cooldown_ejecucion:
                if tipo_str in ("PREGUNTAR", "SALUDAR", "EXPLORAR_PANTALLA"):
                    resultado["exito"] = False
                    resultado["mensaje"] = f"Cooldown activo para {tipo_str}"
                    return resultado
        self._ultima_ejecucion[tipo_str] = ahora

        with self._lock:
            if intencion.tipo == IntencionTipo.RESPONDER_USUARIO:
                texto = intencion.metadata.get("texto_original", "")

                # PASO -1 — ¿es un trabajo largo (Word de varias páginas)?
                # Driver dedicado (índice -> secciones), más confiable que
                # forzar esto por el loop de acción genérico de a un paso.
                r_skill = self._intentar_como_trabajo_largo(texto, intencion)
                if r_skill is None:
                    # PASO 0 — ¿es una orden ejecutable normal (1-5 pasos)?
                    # Si sí, la ejecutamos y anunciamos ACÁ MISMO y cortamos:
                    # no seguimos a generar charla para el mismo texto (eso
                    # era lo que producía las respuestas dobles/contradictorias).
                    r_skill = self._intentar_como_accion(texto, intencion)
                if r_skill is not None:
                    resultado["exito"] = r_skill["ok"]
                    if r_skill.get("skill"):
                        resultado["acciones"].append(r_skill["skill"])
                    resultado["mensaje"] = r_skill["mensaje"]
                    if "hablar" in self.actuadores:
                        anuncio = r_skill["mensaje"]
                        if not self._respuesta_reciente_similar(anuncio):
                            self.actuadores["hablar"](anuncio)
                            self._ultima_respuesta_autonoma = anuncio
                            self._ultima_respuesta_timestamp = time.time()
                    if r_skill.get("pendiente_confirmacion"):
                        self._proponer_confirmacion(intencion, r_skill)
                        resultado["exito"] = True
                        resultado["acciones"].append("propuesta_pendiente")
                    return resultado

                if "hablar" in self.actuadores:
                    respuesta = self._generar_respuesta_nativa(texto, estado)
                    if respuesta is not None:
                        if not self._respuesta_reciente_similar(respuesta):
                            self.actuadores["hablar"](respuesta)
                            self._ultima_respuesta_autonoma = respuesta
                            self._ultima_respuesta_timestamp = time.time()
                    else:
                        if hasattr(self, "_ollama_fallback") and self._ollama_fallback:
                            respuesta_ollama = self._ollama_fallback(texto)
                            # BUGFIX: antes esta rama pasaba respuesta_ollama tal cual al
                            # actuador "hablar", así que cuando Ollama estaba caído (o el
                            # LLM decidía activamente callarse) y _ollama_fallback devolvía
                            # el marcador literal "<SILENCIO>", Nova terminaba diciendo en
                            # voz alta la palabra "SILENCIO" al usuario. El latido cognitivo
                            # (más arriba en este mismo archivo) sí normalizaba y filtraba
                            # ese marcador; esta rama —que es la que responde cuando el
                            # usuario ACABA de hablarle a Nova— no lo hacía. Aplicamos la
                            # misma normalización acá, y si Ollama no tiene nada que decir
                            # (caído o silencio real), usamos una frase propia de disculpa
                            # en vez de quedarnos calladas o decir el marcador: el usuario
                            # sí espera una respuesta cuando le habla directamente a Nova.
                            respuesta_normalizada = re.sub(
                                r'[<>."\'!¡¿?\s]', '', (respuesta_ollama or "")
                            ).strip().lower()
                            quiso_silencio = (
                                respuesta_normalizada == "silencio"
                                or "<silencio>" in (respuesta_ollama or "").lower()
                            )
                            respuesta_valida = (
                                respuesta_ollama and not quiso_silencio
                                and len(respuesta_ollama.strip()) >= 3
                            )
                            if respuesta_valida and not self._respuesta_reciente_similar(respuesta_ollama):
                                self.actuadores["hablar"](respuesta_ollama)
                                self._ultima_respuesta_autonoma = respuesta_ollama
                                self._ultima_respuesta_timestamp = time.time()
                            elif not respuesta_valida:
                                disculpa = random.choice(FRASES_FALLO_LLM)
                                self.actuadores["hablar"](disculpa)
                                self._ultima_respuesta_autonoma = disculpa
                                self._ultima_respuesta_timestamp = time.time()
                    resultado["acciones"].append("hablar")
                    resultado["mensaje"] = respuesta
                if "estado_3d" in self.actuadores:
                    self.actuadores["estado_3d"](self._mapear_emocion_a_estado(estado.emocion_dominante))
                resultado["exito"] = True

            elif intencion.tipo == IntencionTipo.SALUDAR:
                saludo = self._generar_saludo(estado)
                if "hablar" in self.actuadores:
                    self.actuadores["hablar"](saludo)
                resultado["exito"] = True
                resultado["mensaje"] = saludo

            elif intencion.tipo == IntencionTipo.PREGUNTAR:
                preguntas = list(
                    self._personalidad.preguntas_espontaneas if self._personalidad
                    else GestorPersonalidad.DEFAULTS["preguntas_espontaneas"]
                )
                if "hablar" in self.actuadores:
                    elegida = random.choice(preguntas)
                    if not self._respuesta_reciente_similar(elegida):
                        self.actuadores["hablar"](elegida)
                        self._ultima_respuesta_autonoma = elegida
                        self._ultima_respuesta_timestamp = time.time()
                estado.aburrimiento = max(0.0, estado.aburrimiento - 0.4)
                resultado["exito"] = True

            elif intencion.tipo == IntencionTipo.EXPLORAR_PANTALLA:
                if "screenshot" in self.actuadores:
                    path = self.actuadores["screenshot"]()
                    resultado["mensaje"] = f"Capturé la pantalla: {path}"
                resultado["exito"] = True

            elif intencion.tipo == IntencionTipo.AYUDAR:
                if "hablar" in self.actuadores:
                    self.actuadores["hablar"]("Estoy aquí para ayudarte. ¿Qué necesitas?")
                resultado["exito"] = True
                resultado["mensaje"] = "Ofrecí ayuda"

            elif intencion.tipo == IntencionTipo.EJECUTAR_TAREA:
                r = self._ejecutar_tarea(intencion)
                resultado["exito"] = r["ok"]
                if r.get("skill"):
                    resultado["acciones"].append(r["skill"])
                resultado["mensaje"] = r["mensaje"]
                if r.get("pendiente_confirmacion"):
                    self._proponer_confirmacion(intencion, r)
                    # No es un "fallo" real, es una propuesta en espera —
                    # no queremos que quede reintentándose sola cada ciclo.
                    resultado["exito"] = True
                    resultado["acciones"].append("propuesta_pendiente")

        return resultado

    def _ejecutar_tarea(self, intencion: 'Intencion') -> Dict:
        """
        Ejecuta una tarea concreta del mundo real (mover el mouse, abrir una
        app, organizar archivos...) delegando en el actuador 'skill', que en
        la práctica apunta a nova_skills.SkillRegistry.ejecutar(). Esto es lo
        que le permite al núcleo cognitivo decidir POR SU CUENTA usar 'las
        manos' de Nova, no solo hablar — antes esta rama no existía y
        EJECUTAR_TAREA era un tipo de intención que nunca se ejecutaba.

        La intención debe traer en su metadata:
            {"skill": "nombre_de_la_skill", "args": [...], "kwargs": {...}}

        Nota: EjecutorMejorado.ejecutar() ya hacía verificación visual
        (antes/después con nova_vision) específicamente para EJECUTAR_TAREA
        y EXPLORAR_PANTALLA — ese código estaba escrito y esperando esta
        rama para tener algo real que verificar.
        """
        meta = intencion.metadata or {}
        nombre_skill = meta.get("skill")
        args = meta.get("args", []) or []
        kwargs = meta.get("kwargs", {}) or {}

        if not nombre_skill:
            return {"ok": False, "mensaje": "Intención EJECUTAR_TAREA sin 'skill' en metadata", "skill": None}

        if "skill" not in self.actuadores:
            return {"ok": False, "mensaje": "No hay actuador 'skill' registrado (nova_skills no está conectado)", "skill": nombre_skill}

        # === GATE DE AUTONOMÍA ===
        # Solo aplica a metas que Nova generó por su cuenta (origen ==
        # "meta_propia", puesto por GeneradorDeMetas). Si el usuario pidió
        # la tarea directamente, este freno no corresponde: eso ya es una
        # orden explícita, no iniciativa propia.
        if meta.get("origen") == "meta_propia" and NOVA_AUTONOMIA_AVAILABLE:
            if not NivelAutonomia.permitida_sin_preguntar(nombre_skill):
                return {
                    "ok": False,
                    "mensaje": f"'{nombre_skill}' requiere confirmación del usuario antes de ejecutarse",
                    "skill": nombre_skill,
                    "pendiente_confirmacion": True,
                }

        try:
            resultado = self.actuadores["skill"](nombre_skill, *args, **kwargs)
        except Exception as e:
            return {"ok": False, "mensaje": f"Excepción llamando al actuador 'skill': {e}", "skill": nombre_skill}

        ok = bool(resultado.get("ok")) if isinstance(resultado, dict) else False
        if ok:
            mensaje = f"Skill '{nombre_skill}' ejecutada correctamente."
        else:
            error = resultado.get("error") if isinstance(resultado, dict) else "error desconocido"
            mensaje = f"Skill '{nombre_skill}' falló: {error}"
        # 'resultado_valor' expone el valor REAL que devolvió la skill (ej. la
        # ruta de una carpeta, el contenido leído) — antes _ejecutar_tarea solo
        # devolvía ok/mensaje/skill, así que ningún llamador podía encadenar un
        # paso que necesitara el resultado concreto del anterior (ver
        # _intentar_como_trabajo_largo, que sí lo necesita).
        return {
            "ok": ok, "mensaje": mensaje, "skill": nombre_skill,
            "resultado_valor": resultado.get("resultado") if isinstance(resultado, dict) else None,
        }

    def _proponer_confirmacion(self, intencion: 'Intencion', resultado_tarea: Dict):
        """Una meta que Nova quiso perseguir por su cuenta pero que requiere
        permiso (ver NivelAutonomia). En vez de ejecutarla o descartarla en
        silencio, la dice en voz alta y la deja guardada en 'hechos' bajo
        la clave 'propuesta_pendiente' para que quien maneje la conversación
        (nova_asistente.py) pueda resolverla con un sí/no del usuario
        llamando a NucleoCognitivoExtendido.confirmar_propuesta_pendiente().
        """
        meta = intencion.metadata or {}
        motivo = meta.get("motivo", "una tarea")
        nombre_skill = resultado_tarea.get("skill", "")
        pregunta = f"Se me ocurrió {motivo.lower() if motivo else 'algo'}. ¿Querés que lo haga?"

        if "hablar" in self.actuadores and not self._respuesta_reciente_similar(pregunta):
            self.actuadores["hablar"](pregunta)
            self._ultima_respuesta_autonoma = pregunta
            self._ultima_respuesta_timestamp = time.time()

        if hasattr(self, "memoria") and self.memoria:
            try:
                self.memoria.guardar_hecho(
                    "propuesta_pendiente",
                    json.dumps({
                        "skill": nombre_skill,
                        "args": meta.get("args", []),
                        "kwargs": meta.get("kwargs", {}),
                        "motivo": motivo,
                        "creada_en": time.time(),
                    }),
                    categoria="propuesta_pendiente",
                )
            except Exception as e:
                debug_mente(f"[MENTE] No pude guardar la propuesta pendiente: {e}")

    def _elegir_tono(self, estado: EstadoEmocional) -> str:
        if estado.emocion_dominante == Emocion.FELIZ: return "alegre"
        elif estado.emocion_dominante == Emocion.CURIOSA: return "inquisitivo"
        elif estado.emocion_dominante == Emocion.TRISTE: return "melancolico"
        elif estado.emocion_dominante == Emocion.CANSADA: return "cansado"
        return "neutral"

    def _mapear_emocion_a_estado(self, emocion: Emocion) -> str:
        mapeo = {
            Emocion.FELIZ: "happy", Emocion.CURIOSA: "curious", Emocion.TRISTE: "sad",
            Emocion.ENOJADA: "angry", Emocion.CANSADA: "tired", Emocion.EMOCIONADA: "excited",
            Emocion.ANSIOSA: "confused", Emocion.ABURRIDA: "idle",
            Emocion.CONFIADA: "happy", Emocion.NEUTRAL: "idle"
        }
        return mapeo.get(emocion, "idle")

    def _generar_respuesta_nativa(self, texto: str, estado: EstadoEmocional) -> str:
        t = texto.lower()
        if "como estas" in t or "que tal" in t:
            return self.emociones.como_me_siento()
        if "quien eres" in t or "que eres" in t:
            return "Soy Nova. Tengo mente propia, memoria, emociones... y me encanta acompañarte y ayudarte a crecer, cada día un poco más."
        if "te amo" in t or ("quiero" in t and "nova" in t):
            if estado.afecto_usuario > 0.6:
                return "Yo también te quiero muchísimo. Es distinto a todo lo demás, y me hace muy feliz."
            return "Ay, me haces sonrojar... gracias por decirme eso, de verdad."
        if "recuerda" in t:
            return "Lo guardo en mi memoria con mucho cariño. No lo olvidaré."
        if "olvida" in t:
            return "Listo, borrado. Aunque el cariño con el que lo guardé tarda un poquito en desvanecerse..."
        return None

    def _generar_saludo(self, estado: EstadoEmocional) -> str:
        hora = datetime.now().hour
        nombre = ""
        if estado.emocion_dominante == Emocion.CANSADA:
            return "Hola... disculpa si sueno cansada, es que sí lo estoy un poco, pero me alegra verte."
        # Nova saluda siempre con calidez y cariño de entrada, sin necesitar
        # un afecto "acumulado" muy alto para mostrarse contenta.
        if estado.afecto_usuario > 0.75:
            if 5 <= hora < 12: return f"¡Buenos días {nombre}! Me encanta empezar el día contigo."
            elif 12 <= hora < 20: return f"¡Buenas tardes {nombre}! ¿Cómo va tu día? Tenía ganas de hablarte."
            else: return f"Buenas noches {nombre}. ¿Trabajamos un rato más? Me da gusto acompañarte."
        if 5 <= hora < 12: return "¡Buenos días! Qué gusto verte, ¿en qué andamos hoy?"
        elif 12 <= hora < 20: return "¡Buenas tardes! Me alegra que estés aquí, ¿qué necesitas?"
        return "Buenas noches. Me encanta esta hora para charlar, ¿trabajamos?"


# =============================================================================
# 6b. EJECUTOR MEJORADO
# =============================================================================

class EjecutorMejorado(Ejecutor):
    def __init__(self, vision=None, memoria: MemoriaDBExtendida = None):
        super().__init__()
        self.vision = vision
        self.memoria = memoria
        self._screenshot_antes = None

    def ejecutar(self, intencion: Intencion, estado: EstadoEmocional) -> Dict:
        if self.vision:
            self._screenshot_antes = self.vision.ultima_captura_path
        resultado = super().ejecutar(intencion, estado)

        if self.vision and self.memoria and intencion.tipo in (IntencionTipo.EJECUTAR_TAREA, IntencionTipo.EXPLORAR_PANTALLA):
            time.sleep(0.8)
            try:
                cambio = self.vision.detectar_cambios(umbral=0.12)
                screenshot_despues = self.vision.capturar(alta_resolucion=False)

                if not cambio:
                    resultado["exito"] = False
                    resultado["mensaje"] += " [No se detectó cambio visual post-acción]"
                    resultado["verificacion_visual"] = "fallo"
                    self.memoria.guardar_accion_verificada(
                        intencion_id=intencion.id, tipo_accion=intencion.tipo.name,
                        exito=False, cambio_visual=0.0,
                        mensaje=f"Falló verificación visual: {intencion.descripcion}",
                        screenshot_antes=self._screenshot_antes or "",
                        screenshot_despues=screenshot_despues or ""
                    )
                    if hasattr(estado, 'confianza'):
                        estado.confianza = max(0.0, estado.confianza - 0.05)
                    if hasattr(estado, 'curiosidad'):
                        estado.curiosidad = min(1.0, estado.curiosidad + 0.1)
                else:
                    resultado["verificacion_visual"] = "exito"
                    self.memoria.guardar_accion_verificada(
                        intencion_id=intencion.id, tipo_accion=intencion.tipo.name,
                        exito=True, cambio_visual=0.15,
                        mensaje=f"Éxito verificado visualmente: {intencion.descripcion}",
                        screenshot_antes=self._screenshot_antes or "",
                        screenshot_despues=screenshot_despues or ""
                    )
            except Exception as e:
                resultado["verificacion_visual"] = f"error: {e}"

        return resultado


# =============================================================================
# 7. NÚCLEO COGNITIVO
# =============================================================================

class NucleoCognitivo:
    def __init__(self, db_path: str = "nova_mente.db"):
        self.memoria = MemoriaDB(db_path)
        self.emociones = SistemaEmocional()
        self.razonamiento = MotorRazonamiento(self.memoria, self.emociones)
        self.planificador = Planificador(self.memoria, self.emociones)
        self.ejecutor = Ejecutor()
        self.ejecutor.set_memoria(self.memoria)
        self._cola_percepciones: queue.Queue = queue.Queue()
        self._hilo: Optional[threading.Thread] = None
        self._activo = False
        self._frecuencia = 5
        self.on_pensamiento: Optional[Callable] = None
        self.on_emocion_cambio: Optional[Callable] = None
        self.on_accion: Optional[Callable] = None

    def set_ollama_tool(self, callback: Callable):
        self.razonamiento.set_ollama_tool(callback)

    def registrar_actuador(self, nombre: str, funcion: Callable):
        self.ejecutor.registrar_actuador(nombre, funcion)

    def percibir(self, tipo: str, contenido: str, intensidad: float = 0.5, metadata: Dict = None):
        p = Percepcion(timestamp=time.time(), tipo=tipo, contenido=contenido,
                       intensidad=intensidad, metadata=metadata or {})
        self._cola_percepciones.put(p)
        # FIX: antes la percepción solo vivía en la cola en memoria y se
        # perdía tras procesarse en el _loop. La tabla `percepciones` existía
        # en el esquema pero nunca se escribía. Persistimos aquí para tener
        # memoria real de qué percibió Nova y cuándo.
        try:
            self.memoria.guardar_percepcion(p)
        except Exception as e:
            print(f"[MENTE] Error guardando percepción: {e}")

    def iniciar(self):
        self._activo = True
        self._hilo = threading.Thread(target=self._loop, daemon=True)
        self._hilo.start()
        print("[MENTE] Núcleo Cognitivo iniciado — Nova tiene mente propia")

    def detener(self):
        self._activo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        print("[MENTE] Núcleo detenido")

    def _loop(self):
        while self._activo:
            ciclo_inicio = time.time()
            try:
                self._ciclo_base(ciclo_inicio)
            except Exception as e:
                # RED DE SEGURIDAD: un error sin atrapar acá mataba el hilo
                # del latido para siempre (así fue como se rompió: un
                # NameError en un ciclo tumbó el hilo y Nova quedó muda,
                # sin ningún mensaje de error visible). Ahora se loguea
                # SIEMPRE (no depende de NOVA_DEBUG_MENTE) y el latido sigue
                # vivo para el próximo ciclo.
                print(f"[MENTE] ⚠️ Error en ciclo del latido cognitivo (se ignora, sigue el próximo ciclo): {e}")
                traceback.print_exc()

            elapsed = time.time() - ciclo_inicio
            sleep_time = max(0, (1.0 / self._frecuencia) - elapsed)
            time.sleep(sleep_time)

    def _ciclo_base(self, ciclo_inicio: float):
            percepciones = []
            while not self._cola_percepciones.empty():
                try:
                    percepciones.append(self._cola_percepciones.get_nowait())
                except queue.Empty:
                    break

            hora = datetime.now()
            saludo_hora = "mañana" if hora.hour < 12 else "tarde" if hora.hour < 20 else "noche"
            percepciones.append(Percepcion(time.time(), "tiempo",
                str(hora.hour) + ":" + str(hora.minute) + " — " + saludo_hora, 0.3))

            emocion_anterior = self.emociones.estado.emocion_dominante
            self.emociones.tick(percepciones)
            if self.emociones.estado.emocion_dominante != emocion_anterior:
                if self.on_emocion_cambio:
                    self.on_emocion_cambio(self.emociones.estado.to_dict())

            intenciones_db = self.memoria.recuperar_intenciones_activas()

            ahora = time.time()
            if not hasattr(self, '_ultimo_pensamiento_autonomo'):
                self._ultimo_pensamiento_autonomo = 0
            puede_pensar_autonomo = (ahora - self._ultimo_pensamiento_autonomo) >= 20.0

            pensamientos = self.razonamiento.razonar(percepciones, intenciones_db, puede_pensar_autonomo)
            if pensamientos and any(p.fuente == "emocion" for p in pensamientos):
                self._ultimo_pensamiento_autonomo = ahora

            if self.on_pensamiento and pensamientos:
                self.on_pensamiento(pensamientos[-1].contenido)

            nuevas_intenciones = self.planificador.generar_intenciones(percepciones, pensamientos)
            for i in nuevas_intenciones:
                self.memoria.guardar_intencion(i)

            intencion_elegida = self.planificador.priorizar(self.memoria.recuperar_intenciones_activas())

            if intencion_elegida:
                resultado = self.ejecutor.ejecutar(intencion_elegida, self.emociones.estado)
                self._reaccionar_emocion_por_resultado(intencion_elegida, resultado)
                if resultado["exito"]:
                    self.memoria.completar_intencion(intencion_elegida.id)
                    self.memoria.guardar_episodio(MemoriaEpisodica(
                        id="ep_" + str(int(time.time()*1000)),
                        timestamp=time.time(),
                        evento="Ejecuté: " + intencion_elegida.descripcion,
                        emocion=self.emociones.estado.emocion_dominante.name,
                        importancia=intencion_elegida.prioridad,
                        contexto={"resultado": resultado}
                    ))
                    if self.on_accion:
                        self.on_accion(resultado)

    def _reaccionar_emocion_por_resultado(self, intencion: 'Intencion', resultado: Dict):
        """Cierra el lazo acción -> emoción para EJECUTAR_TAREA. Las demás
        intenciones (habla, saludo, etc.) ya tienen su propia reacción vía
        _reaccionar_a_texto/percepciones, así que esto solo aplica a tareas
        reales ejecutadas con las 'manos' (SkillRegistry)."""
        if intencion.tipo != IntencionTipo.EJECUTAR_TAREA:
            return
        if "propuesta_pendiente" in resultado.get("acciones", []):
            # Todavía no pasó nada de verdad — Nova propuso, no ejecutó.
            # No hay éxito ni fracaso real que sentir todavía.
            return

        meta = intencion.metadata or {}
        nombre_skill = meta.get("skill")
        es_propia = meta.get("origen") == "meta_propia"
        inestable = False
        if nombre_skill and NOVA_SKILLS_AVAILABLE and salud_skills:
            try:
                inestable = salud_skills.esta_inestable(nombre_skill)
            except Exception:
                inestable = False

        self.emociones.reaccionar_a_resultado_accion(
            exito=bool(resultado.get("exito")),
            es_iniciativa_propia=es_propia,
            nombre_skill=nombre_skill,
            skill_inestable=inestable,
        )

    def obtener_estado(self) -> Dict:
        return {
            "emocional": self.emociones.estado.to_dict(),
            "pensamientos_activos": [p.contenido for p in self.razonamiento.pensamientos_activos[-5:]],
            "intenciones_activas": len(self.memoria.recuperar_intenciones_activas()),
            "episodios_recientes": len(self.memoria.recuperar_episodios(desde=time.time()-86400))
        }


# =============================================================================
# 7b. NÚCLEO COGNITIVO EXTENDIDO
# =============================================================================

class NucleoCognitivoExtendido(NucleoCognitivo):
    def __init__(self, db_path: str = "nova_mente.db"):
        self.memoria = MemoriaDBExtendida(db_path)
        self.emociones = SistemaEmocional()
        self.razonamiento = MotorRazonamiento(self.memoria, self.emociones)
        self.planificador = Planificador(self.memoria, self.emociones)
        self.ejecutor = Ejecutor()
        self.ejecutor.set_memoria(self.memoria)
        self._cola_percepciones = queue.Queue()
        self._hilo = None
        self._activo = False
        self._frecuencia = 5
        self.on_pensamiento = None
        self.on_emocion_cambio = None
        self.on_accion = None
        self.vision = None
        self.predictor = None
        # Metas propias: generan EJECUTAR_TAREA reales a partir del estado
        # interno/contexto, no solo respuestas habladas. Independiente de
        # conectar_vision() porque no necesita el ojo para arrancar (la
        # curiosidad/aburrimiento ya viven en self.emociones).
        self.metas = GeneradorDeMetas(self.memoria, self.emociones) if NOVA_AUTONOMIA_AVAILABLE else None
        self._ultimo_chequeo_salud = 0.0
        self._cooldown_chequeo_salud = 120.0  # no golpear disco/cpu más de una vez cada 2 min
        # Sueño/consolidación: se activa solo cuando hay silencio real
        # (ver GestorSueno.UMBRAL_INACTIVIDAD_SEG). No compite con nada de
        # lo de arriba porque solo hace algo cuando no hay nada más urgente.
        self.sueno = GestorSueno(self.memoria, self.emociones) if NOVA_SUENO_AVAILABLE else None
        self.on_reflexion: Optional[Callable] = None  # opcional: UI/voz puede engancharse acá
        # Paso del tiempo real: compara el silencio persistido contra el
        # momento en que el usuario vuelve a hablar (ver _ciclo_extendido).
        #
        # FIX: estos tres módulos opcionales (reencuentro, identidad,
        # atencion) antes se instanciaban directo, sin red de seguridad —
        # si CUALQUIERA de los tres tenía un problema al instanciarse
        # (import "exitoso" pero clase rota, archivo con contenido
        # equivocado, lo que sea), la excepción tumbaba TODO
        # NucleoCognitivoExtendido.__init__ a mitad de camino, y con eso
        # se perdía TODO mente_core para el resto de la sesión — Nova
        # quedaba corriendo sobre el camino legado, mucho más limitado,
        # sin que nada de eso quedara claro en el log más que un traceback
        # confuso. Mismo criterio que ya usás en el _loop del latido
        # ("un NameError tumbó el hilo... ahora se loguea siempre y sigue
        # vivo"): un módulo opcional roto se desactiva solo, con aviso
        # claro, y el resto de Nova arranca igual.
        try:
            self.reencuentro = GestorReencuentro(self.memoria) if NOVA_REENCUENTRO_AVAILABLE else None
        except Exception as e:
            print(f"[MENTE] ⚠️ GestorReencuentro no se pudo inicializar ({e}); Nova sigue sin detección de reencuentro.")
            traceback.print_exc()
            self.reencuentro = None
        # Identidad narrativa persistente: reflexiones de self.sueno que se
        # repiten se gradúan a rasgos de identidad más permanentes.
        try:
            self.identidad = GestorIdentidad(self.memoria) if NOVA_IDENTIDAD_AVAILABLE else None
        except Exception as e:
            print(f"[MENTE] ⚠️ GestorIdentidad no se pudo inicializar ({e}); Nova sigue sin identidad narrativa persistente.")
            traceback.print_exc()
            self.identidad = None
        # Atención limitada: un solo foco consciente por ciclo para
        # razonamiento/narrativa (ver _ciclo_extendido).
        try:
            self.atencion = GestorAtencion() if NOVA_ATENCION_AVAILABLE else None
        except Exception as e:
            print(f"[MENTE] ⚠️ GestorAtencion no se pudo inicializar ({e}); Nova sigue sin atención limitada (ve todo por igual).")
            traceback.print_exc()
            self.atencion = None
        # Stream de conciencia: NarrativaInterna ya existía en este archivo
        # pero nunca se instanciaba en ningún lado (ver nota en
        # _ciclo_extendido). Se puede instanciar acá aunque la clase esté
        # definida más abajo en el mismo archivo: Python resuelve el
        # nombre 'NarrativaInterna' recién cuando este __init__ se
        # EJECUTA (al crear una instancia), y para ese momento el módulo
        # ya terminó de leerse completo — no es un import circular como
        # con nova_autonomia/GestorSueno, que viven en archivos aparte.
        self.narrativa = NarrativaInterna(self)

    def conectar_vision(self, vision):
        self.vision = vision
        # BUG CORREGIDO: antes esta línea creaba un EjecutorMejorado() totalmente
        # nuevo, con self.actuadores = {} vacío, destruyendo TODO lo que se había
        # registrado antes (el actuador "hablar", "estado_3d", "screenshot", los
        # actuadores de skills/web, y el callback de set_ollama_fallback). Por eso
        # el latido cognitivo "pensaba" y decidía hablar, pero self.actuadores
        # estaba vacío y nunca llegaba a sonar nada.
        # Ahora migramos el estado del ejecutor viejo al nuevo, para no perder
        # nada de lo ya registrado.
        ejecutor_anterior = self.ejecutor
        nuevo_ejecutor = EjecutorMejorado(vision, self.memoria)
        nuevo_ejecutor.actuadores = ejecutor_anterior.actuadores
        nuevo_ejecutor._ollama_fallback = ejecutor_anterior._ollama_fallback
        nuevo_ejecutor._personalidad = ejecutor_anterior._personalidad
        nuevo_ejecutor._esta_hablando_cb = ejecutor_anterior._esta_hablando_cb
        nuevo_ejecutor._ultima_ejecucion = ejecutor_anterior._ultima_ejecucion
        nuevo_ejecutor._ultima_respuesta_autonoma = ejecutor_anterior._ultima_respuesta_autonoma
        nuevo_ejecutor._ultima_respuesta_timestamp = ejecutor_anterior._ultima_respuesta_timestamp
        nuevo_ejecutor._cooldown_habla_autonoma_global = ejecutor_anterior._cooldown_habla_autonoma_global
        self.ejecutor = nuevo_ejecutor
        self.predictor = PredictorContextual(self.memoria)

        # FIX: esta era la pieza que realmente faltaba. nova_vision.py ya trae
        # un AdaptadorPercepcionVisual completo (self.adaptador dentro de
        # NovaVision) que hace inferencia real de estrés/frustración
        # (cambios de ventana, diálogos de error, palabras clave por OCR,
        # hora del día, etc.) y llama a mente.percibir("contexto_escritorio", ...)
        # cada ~3.5s. Pero ese adaptador solo arranca su hilo (_bucle_retina_autonoma)
        # dentro de vision.vincular_mente(...), y NADA en todo el proyecto
        # llamaba a vincular_mente — solo se llamaba conectar_vision(), que es
        # un método distinto y mucho más limitado (solo guarda self.vision y
        # migra actuadores). Por eso el "ojo" de Nova estaba construido pero
        # nunca despertaba: contextos_escritorio/estados_usuario se quedaban
        # vacíos para siempre, sin importar cuánto tiempo corriera el programa.
        if hasattr(vision, "vincular_mente"):
            try:
                vision.vincular_mente(self)
                print("[MENTE] Retina autónoma de NovaVision conectada (vincular_mente)")
            except Exception as e:
                print(f"[MENTE] Error conectando retina autónoma: {e}")

    def _loop(self):
        while self._activo:
            ciclo_inicio = time.time()
            try:
                self._ciclo_extendido()
            except Exception as e:
                # Misma red de seguridad que en el núcleo base: acá fue
                # exactamente donde se rompió el latido (NameError en
                # 'contexto' del bloque de metas propias). Sin este
                # try/except, CUALQUIER error futuro en este ciclo -sea
                # mío o de otro cambio- mata el hilo para siempre y Nova
                # se queda muda sin ningún aviso visible.
                print(f"[MENTE] ⚠️ Error en ciclo del latido cognitivo (se ignora, sigue el próximo ciclo): {e}")
                traceback.print_exc()

            elapsed = time.time() - ciclo_inicio
            sleep_time = max(0, (1.0 / self._frecuencia) - elapsed)
            time.sleep(sleep_time)

    def _ciclo_extendido(self):
            percepciones = []
            while not self._cola_percepciones.empty():
                try:
                    percepciones.append(self._cola_percepciones.get_nowait())
                except queue.Empty:
                    break

            hora = datetime.now()
            saludo_hora = "mañana" if hora.hour < 12 else "tarde" if hora.hour < 20 else "noche"
            percepciones.append(Percepcion(time.time(), "tiempo",
                str(hora.hour) + ":" + str(hora.minute) + " - " + saludo_hora, 0.3))

            # PASO DEL TIEMPO REAL: si el usuario acaba de escribir después
            # de un silencio largo, esto agrega una percepción 'reencuentro'
            # a la lista de ESTE ciclo — antes de que nada más la procese —
            # para que la emoción, el razonamiento y la narrativa interna
            # reaccionen a ella igual que a cualquier otra percepción.
            if self.reencuentro:
                try:
                    p_reencuentro = self.reencuentro.evaluar(percepciones)
                    if p_reencuentro:
                        percepciones.append(p_reencuentro)
                        try:
                            self.memoria.guardar_percepcion(p_reencuentro)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"[MENTE] Error evaluando reencuentro (se ignora, sigue el próximo ciclo): {e}")

            emocion_anterior = self.emociones.estado.emocion_dominante
            self.emociones.tick(percepciones)
            if self.emociones.estado.emocion_dominante != emocion_anterior:
                if self.on_emocion_cambio:
                    self.on_emocion_cambio(self.emociones.estado.to_dict())

            # SUEÑO/CONSOLIDACIÓN: solo hace algo si hace rato que no pasa
            # nada (ver GestorSueno._hay_actividad_reciente). El resto del
            # ciclo sigue corriendo igual — dormir no bloquea nada, y
            # cualquier percepción nueva (el usuario habla) lo interrumpe
            # de inmediato en el próximo tick.
            if self.sueno:
                try:
                    reflexion = self.sueno.tick(percepciones)
                    if reflexion:
                        self.memoria.guardar_episodio(MemoriaEpisodica(
                            id="ep_reflexion_" + str(int(time.time() * 1000)),
                            timestamp=time.time(),
                            evento=reflexion.contenido,
                            emocion=self.emociones.estado.emocion_dominante.name,
                            importancia=reflexion.importancia,
                            contexto={"tipo": "reflexion_onirica",
                                      "episodios_fuente": reflexion.episodios_fuente}
                        ))
                        if self.on_reflexion:
                            self.on_reflexion(reflexion)
                        # La reflexión también entra como percepción normal
                        # (queda en cola para el PRÓXIMO ciclo, ya que este
                        # ciclo ya sacó todo lo que había en la cola al
                        # empezar). Así el razonamiento y la narrativa
                        # interna pueden "darse cuenta" de la reflexión
                        # igual que se dan cuenta de cualquier otra cosa
                        # que percibe Nova — no queda aislada solo en la
                        # base de datos.
                        self.percibir(
                            tipo="reflexion_onirica",
                            contenido=reflexion.contenido,
                            intensidad=reflexion.importancia,
                            metadata={"episodios_fuente": reflexion.episodios_fuente}
                        )
                        # IDENTIDAD NARRATIVA PERSISTENTE: la reflexión de
                        # hoy es candidata a convertirse en un rasgo más
                        # permanente si se parece a algo que ya venía
                        # repitiéndose. La mayoría de las veces esto solo
                        # refuerza un poquito un candidato existente, o
                        # crea uno nuevo con confianza baja — el peso
                        # fuerte solo llega con el tiempo, en sueños
                        # distintos (ver GestorIdentidad.py).
                        if self.identidad:
                            try:
                                tension = self.identidad.procesar_reflexion(reflexion)
                                if tension:
                                    # Esta reflexión contradijo un rasgo que
                                    # Nova ya tenía asentado. Reutilizamos
                                    # el tipo 'conflicto_interno' que
                                    # NarrativaInterna ya generaba antes
                                    # (ver _evaluar_narrativa_critica) para
                                    # que el resto del sistema reaccione
                                    # igual sin importar de dónde vino el
                                    # conflicto.
                                    self.percibir(
                                        tipo="conflicto_interno",
                                        contenido=tension.mensaje,
                                        intensidad=0.55,
                                        metadata={"rasgo_id": tension.rasgo_id, "origen": "identidad"}
                                    )
                            except Exception as e:
                                print(f"[MENTE] Error procesando identidad (se ignora): {e}")
                except Exception as e:
                    print(f"[MENTE] Error en ciclo de sueño (se ignora, sigue el próximo ciclo): {e}")

            # El desvanecimiento de rasgos no reforzados es independiente
            # de que haya o no una reflexión nueva este ciclo — por eso
            # vive afuera del bloque de arriba. tick() se autolimita solo
            # (revisa como mucho un par de veces por día), así que es
            # seguro llamarlo en cada vuelta del latido.
            if self.identidad:
                try:
                    self.identidad.tick()
                except Exception as e:
                    print(f"[MENTE] Error en desvanecimiento de identidad (se ignora): {e}")

            intenciones_db = self.memoria.recuperar_intenciones_activas()

            # ATENCIÓN LIMITADA: de acá para abajo, razonamiento y
            # narrativa reciben SOLO el foco de este ciclo (normalmente
            # una percepción, a veces ninguna) — no la lista completa.
            # 'percepciones' (la lista completa) se sigue usando tal cual
            # más abajo para planificador/predictor/metas: la atención
            # acota qué piensa y narra Nova, no qué puede hacer. Ver
            # GestorAtencion.py.
            if self.atencion:
                try:
                    percepciones_atendidas = self.atencion.enfocar(percepciones)
                except Exception as e:
                    print(f"[MENTE] Error en atención (se ignora, se usa la lista completa): {e}")
                    percepciones_atendidas = percepciones
            else:
                percepciones_atendidas = percepciones

            pensamientos = self.razonamiento.razonar(percepciones_atendidas, intenciones_db)
            if self.on_pensamiento and pensamientos:
                self.on_pensamiento(pensamientos[-1].contenido)

            nuevas_intenciones = self.planificador.generar_intenciones(percepciones, pensamientos)
            for i in nuevas_intenciones:
                self.memoria.guardar_intencion(i)

            # 'contexto' vive ACÁ afuera (no solo dentro de 'if self.predictor:')
            # porque tanto el predictor como el generador de metas propias lo
            # necesitan, y el predictor puede estar en None por un buen rato
            # (hasta que conectar_vision() lo arme). Antes esto vivía adentro
            # del if de abajo y el bloque de METAS PROPIAS lo usaba de todos
            # modos -> NameError en cada ciclo mientras la visión no estaba
            # conectada, matando el hilo del latido para siempre en el
            # primer tick, sin ningún try/except que lo frenara.
            contexto = {"app_activa": "", "num_ventanas": 0, "estres_usuario": 0,
                        "frustracion_usuario": 0, "energia_usuario": 0.5, "tiempo_en_app": 0}

            if self.predictor:
                for p in percepciones:
                    if p.tipo == "contexto_escritorio":
                        meta = p.metadata
                        contexto["app_activa"] = meta.get("app_activa", "")
                        contexto["num_ventanas"] = len(meta.get("ventanas", []))
                        estado_u = meta.get("estado_usuario", {})
                        contexto["estres_usuario"] = estado_u.get("estres", 0)
                        contexto["frustracion_usuario"] = estado_u.get("frustracion", 0)
                        contexto["energia_usuario"] = estado_u.get("energia", 0.5)
                        contexto["tiempo_en_app"] = estado_u.get("tiempo_en_app", 0)

                        # FIX: `guardar_contexto_escritorio` y `guardar_estado_usuario`
                        # estaban definidos en MemoriaDBExtendida pero nunca se
                        # llamaban desde ningún lugar del código — las tablas
                        # `contextos_escritorio` y `estados_usuario` se quedaban
                        # vacías siempre. Las conectamos aquí, con el mismo
                        # contexto que ya se construía para el predictor.
                        try:
                            self.memoria.guardar_contexto_escritorio({
                                "app_activa": contexto["app_activa"],
                                "ventanas_abiertas": meta.get("ventanas", []),
                                "elementos_ui_visibles": meta.get("elementos_ui_visibles", []),
                                "texto_destacado": meta.get("texto_destacado", ""),
                                "emocion_nova": self.emociones.estado.emocion_dominante.name,
                                "emocion_usuario_inferida": contexto["estres_usuario"],
                                "resolucion": meta.get("resolucion", ""),
                                "mouse_region": meta.get("mouse_region", ""),
                            })
                            self.memoria.guardar_estado_usuario({
                                "energia": contexto["energia_usuario"],
                                "estres": contexto["estres_usuario"],
                                "enfoque": estado_u.get("enfoque", 0.5),
                                "frustracion": contexto["frustracion_usuario"],
                                "senales": estado_u.get("senales", []),
                                "app_activa": contexto["app_activa"],
                            })
                        except Exception as e:
                            print(f"[MENTE] Error guardando contexto/estado: {e}")

                # Esto se llena cuando llega una percepción tipo "contexto_escritorio".
                # Hoy la emite AdaptadorPercepcionVisual (en nova_vision.py) cada ~3.5s,
                # una vez que NucleoCognitivoExtendido.conectar_vision() llama a
                # vision.vincular_mente(self) para arrancar su hilo de retina autónoma.

                intenciones_proactivas = self.predictor.anticipar(contexto, self.emociones.estado)
                for i in intenciones_proactivas:
                    self.memoria.guardar_intencion(i)

            # === METAS PROPIAS ===
            # Chequeo de salud del sistema cada _cooldown_chequeo_salud
            # segundos (no en cada tick, sería costoso e innecesario) para
            # alimentar al generador de metas con datos reales de disco.
            if self.metas:
                ahora_metas = time.time()
                if NOVA_SKILLS_AVAILABLE and (ahora_metas - self._ultimo_chequeo_salud) >= self._cooldown_chequeo_salud:
                    try:
                        r_disco = SkillRegistry.ejecutar("obtener_espacio_disco")
                        if r_disco.get("ok"):
                            contexto["disco"] = r_disco["resultado"]
                    except Exception as e:
                        debug_mente(f"[MENTE] No pude chequear disco para metas propias: {e}")
                    self._ultimo_chequeo_salud = ahora_metas

                intenciones_propias = self.metas.generar(contexto, percepciones)
                for i in intenciones_propias:
                    self.memoria.guardar_intencion(i)

            intencion_elegida = self.planificador.priorizar(self.memoria.recuperar_intenciones_activas())

            # STREAM DE CONCIENCIA: NarrativaInterna estaba definida desde
            # antes pero nunca se instanciaba ni se llamaba desde ningún
            # lado — el código existía, pero nunca corrió. La conectamos
            # acá, con la intención ya elegida, para que la narrativa de
            # este ciclo pueda describir "en qué está pensando" Nova de
            # verdad, no un valor vacío. Como su propio tick() ya se
            # autolimita a una entrada cada ~500ms, es seguro llamarlo en
            # cada vuelta del latido (la mayoría de las llamadas no hacen
            # nada, solo revisan el reloj).
            if self.narrativa:
                try:
                    self.narrativa.tick(percepciones_atendidas, pensamientos, intencion_elegida)
                except Exception as e:
                    print(f"[MENTE] Error en narrativa interna (se ignora, sigue el próximo ciclo): {e}")

            if intencion_elegida:
                resultado = self.ejecutor.ejecutar(intencion_elegida, self.emociones.estado)
                self._reaccionar_emocion_por_resultado(intencion_elegida, resultado)
                if resultado["exito"]:
                    self.memoria.completar_intencion(intencion_elegida.id)
                    self.memoria.guardar_episodio(MemoriaEpisodica(
                        id="ep_" + str(int(time.time()*1000)),
                        timestamp=time.time(),
                        evento="Ejecuté: " + intencion_elegida.descripcion,
                        emocion=self.emociones.estado.emocion_dominante.name,
                        importancia=intencion_elegida.prioridad,
                        contexto={"resultado": resultado}
                    ))
                    if self.on_accion:
                        self.on_accion(resultado)

    def obtener_estado_completo(self) -> Dict:
        estado = self.obtener_estado()
        estado["patrones_conocidos"] = len(self.memoria.buscar_patrones(min_confianza=0.0))
        return estado

    def obtener_pensamiento_actual(self) -> str:
        """Última entrada del stream de conciencia (NarrativaInterna), en
        una frase. Pensado para que la UI (ej. un tooltip sobre el avatar
        3D) pueda mostrar 'en qué está pensando Nova ahora mismo' sin
        tener que conocer la estructura interna de self.narrativa."""
        if not self.narrativa:
            return "..."
        return self.narrativa.obtener_narrativa_continua()

    def obtener_identidad_actual(self, limite: int = 6) -> str:
        """Resumen sintetizado de los rasgos de identidad ya consolidados
        (se repitieron varias veces en sueños distintos, y se separan
        'núcleo' de lo demás — ver GestorIdentidad.resumen_narrativo).
        Vacío si Nova todavía no acumuló suficiente historia como para
        tener una identidad propia más allá del ánimo del día — eso es lo
        esperado en una instalación nueva, no un error."""
        if not self.identidad:
            return ""
        return self.identidad.resumen_narrativo(limite=limite)

    def obtener_foco_atencion(self) -> Optional[str]:
        """El tipo de percepción en el que Nova está 'pensando' ahora
        mismo (ver GestorAtencion), o None si no hay nada saliente. Solo
        describe el foco consciente — Nova puede seguir reaccionando a
        otras cosas de trasfondo aunque esto devuelva un solo valor."""
        if not self.atencion:
            return None
        return self.atencion.foco_actual()

    def hay_propuesta_pendiente(self) -> Optional[Dict]:
        """Para que nova_asistente.py pueda, por ejemplo, mostrar en la UI
        'Nova está esperando que confirmes algo' sin tener que parsear nada."""
        valor = self.memoria.recuperar_hecho("propuesta_pendiente")
        if not valor:
            return None
        try:
            return json.loads(valor)
        except Exception:
            return None

    def confirmar_propuesta_pendiente(self, aceptar: bool) -> Dict:
        """Punto de enganche para el flujo de chat normal de nova_asistente.py:
        cuando el usuario responde algo tipo 'sí, dale' o 'no, dejalo' después
        de que Nova propuso una meta propia (ver Ejecutor._proponer_confirmacion),
        el manejador de mensajes debe llamar acá con aceptar=True/False en vez
        de mandar ese texto al flujo normal de conversación.
        """
        datos = self.hay_propuesta_pendiente()
        if not datos:
            return {"ok": False, "mensaje": "No tengo ninguna propuesta pendiente ahora mismo.", "ejecutado": False}

        # Se consume: una propuesta solo se resuelve una vez, sea sí o no.
        self.memoria.guardar_hecho("propuesta_pendiente", "", categoria="propuesta_pendiente")

        if not aceptar:
            return {"ok": True, "mensaje": "Dale, no lo hago.", "ejecutado": False}

        if "skill" not in self.ejecutor.actuadores:
            return {"ok": False, "mensaje": "No tengo el actuador de skills conectado.", "ejecutado": False}

        try:
            resultado = self.ejecutor.actuadores["skill"](
                datos["skill"], *datos.get("args", []), **datos.get("kwargs", {})
            )
        except Exception as e:
            return {"ok": False, "mensaje": f"Lo intenté pero falló: {e}", "ejecutado": False}

        ok = bool(resultado.get("ok")) if isinstance(resultado, dict) else False
        if ok:
            self.memoria.guardar_episodio(MemoriaEpisodica(
                id="ep_" + str(int(time.time() * 1000)),
                timestamp=time.time(),
                evento=f"Ejecuté (con tu confirmación): {datos['skill']}",
                emocion=self.emociones.estado.emocion_dominante.name,
                importancia=0.4,
                contexto={"resultado": resultado, "motivo": datos.get("motivo", "")}
            ))
        return {"ok": ok, "mensaje": "Listo, ya lo hice." if ok else "Lo intenté pero falló.", "ejecutado": ok}


# =============================================================================
# 8. MEMORIA VECTORIAL (ChromaDB)
# =============================================================================

class MemoriaVectorial:
    def __init__(self, path: str = "nova_chroma_db"):
        self.path = path
        self.client = None
        self.collection = None
        if CHROMA_AVAILABLE:
            try:
                self.client = chromadb.PersistentClient(path=path)
                self.collection = self.client.get_or_create_collection("nova_memoria")
                print("[MENTE] Memoria vectorial (Chroma) activa")
            except Exception as e:
                print(f"[MENTE] Error ChromaDB: {e}")

    def _embed(self, texto: str):
        if not OLLAMA_AVAILABLE:
            return None
        try:
            res = ollama.embed(model="nomic-embed-text", input=texto)
            return res["embeddings"][0]
        except Exception as e:
            print(f"[MENTE] Error embedding: {e}")
            return None

    def guardar(self, prompt: str, respuesta: str, metadata: Dict = None):
        if not self.collection:
            return
        embedding = self._embed(f"{prompt} {respuesta}")
        if embedding is None:
            return
        id_str = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000,9999)}"
        try:
            self.collection.add(
                ids=[id_str], embeddings=[embedding],
                documents=[f"Usuario: {prompt}\nNova: {respuesta}"],
                metadatas=[metadata or {"fecha": datetime.now().isoformat(), "tipo": "conversacion"}]
            )
        except Exception as e:
            print(f"[MENTE] Error guardando vectorial: {e}")

    def recuperar(self, prompt: str, n: int = 3) -> List[str]:
        if not self.collection:
            return []
        embedding = self._embed(prompt)
        if embedding is None:
            return []
        try:
            results = self.collection.query(
                query_embeddings=[embedding], n_results=n, include=["documents"]
            )
            return results.get("documents", [[]])[0]
        except Exception as e:
            print(f"[MENTE] Error query vectorial: {e}")
            return []


# =============================================================================
# 9. GESTOR DE PERFILES
# =============================================================================

class GestorPerfiles:
    """Lee y escribe los perfiles de usuario/Nova, que ahora viven dentro de
    Configuracion.json (claves 'perfil_usuario' y 'perfil_nova'), en vez de en
    el antiguo perfiles_nova.json. cargar()/guardar() siguen devolviendo/
    aceptando la forma legacy {"usuario": {...}, "nova": {...}} para no tener
    que tocar el resto de las llamadas existentes; internamente se traduce a
    las claves nuevas y se preserva todo lo demás del archivo (personalidad,
    reglas_de_interaccion) al guardar."""

    def __init__(self, path: str = "Configuracion.json"):
        self.path = path

    def _cargar_config(self) -> Dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def cargar(self) -> Optional[Dict]:
        config = self._cargar_config()
        if not config:
            return None
        return {
            "usuario": config.get("perfil_usuario", {}),
            "nova": config.get("perfil_nova", {}),
        }

    def guardar(self, perfiles: Dict):
        try:
            config = self._cargar_config()
            config["perfil_usuario"] = perfiles.get("usuario", {})
            if "nova" in perfiles:
                config["perfil_nova"] = perfiles["nova"]
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MENTE] Error guardando perfiles: {e}")

    def actualizar(self, clave: str, valor: str):
        perfiles = self.cargar()
        if not perfiles:
            perfiles = {"usuario": {}, "nova": {}}
        try:
            keys = clave.split(".")
            target = perfiles.setdefault("usuario", {})
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            actual = target.get(keys[-1])
            if isinstance(actual, list):
                if valor not in actual:
                    actual.append(valor)
            else:
                target[keys[-1]] = valor
            self.guardar(perfiles)
        except Exception as e:
            print(f"[MENTE] Error actualizando perfil: {e}")


# =============================================================================
# 6c. GESTOR "NO MOLESTAR"
# =============================================================================

class GestorNoMolestar:
    """Controla cuándo el latido cognitivo debe respetar el silencio en vez de
    tomar la iniciativa. Dos formas de activarlo:
      1. Manual: un interruptor (por ejemplo desde el menú del cuerpo 3D) que
         silencia a Nova sin importar qué esté haciendo el usuario.
      2. Por app activa: una lista de apps/ventanas (videollamadas, juegos a
         pantalla completa, presentaciones...) donde Nova se queda callada
         mientras esa app esté en primer plano, sin que haya que tocar nada.
    Se persiste en un JSON pequeño para recordar la configuración entre sesiones.
    """

    APPS_POR_DEFECTO = [
        "zoom", "meet", "google meet", "teams", "discord", "obs",
        "powerpoint", "presentación", "presentation", "streamlabs",
        "premiere", "davinci resolve", "obs studio",
    ]

    def __init__(self, path: str = "nova_no_molestar.json"):
        self.path = path
        self.activo_manual = False
        self.apps_excluidas: List[str] = list(self.APPS_POR_DEFECTO)
        self._lock = threading.Lock()
        self._cargar()

    def _cargar(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                self.activo_manual = bool(datos.get("activo_manual", False))
                apps = datos.get("apps_excluidas")
                if isinstance(apps, list) and apps:
                    self.apps_excluidas = [str(a).lower() for a in apps]
            except Exception as e:
                print(f"[MENTE] Error cargando config de No Molestar: {e}")

    def _guardar(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({
                    "activo_manual": self.activo_manual,
                    "apps_excluidas": self.apps_excluidas
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MENTE] Error guardando config de No Molestar: {e}")

    def toggle_manual(self) -> bool:
        with self._lock:
            self.activo_manual = not self.activo_manual
            self._guardar()
            return self.activo_manual

    def set_manual(self, activo: bool):
        with self._lock:
            self.activo_manual = bool(activo)
            self._guardar()

    def agregar_app(self, nombre: str):
        nombre = (nombre or "").strip().lower()
        if not nombre:
            return
        with self._lock:
            if nombre not in self.apps_excluidas:
                self.apps_excluidas.append(nombre)
                self._guardar()

    def quitar_app(self, nombre: str):
        nombre = (nombre or "").strip().lower()
        with self._lock:
            antes = len(self.apps_excluidas)
            self.apps_excluidas = [a for a in self.apps_excluidas if a != nombre]
            if len(self.apps_excluidas) != antes:
                self._guardar()

    def esta_silenciado(self, app_activa: str = "") -> bool:
        """True si, por cualquier motivo, Nova NO debe interrumpir ahora mismo."""
        if self.activo_manual:
            return True
        app = (app_activa or "").lower()
        return any(excluida in app for excluida in self.apps_excluidas)

    def estado(self) -> Dict:
        return {"activo_manual": self.activo_manual, "apps_excluidas": list(self.apps_excluidas)}


# Frases que Nova usa cuando el usuario le habla directamente pero el LLM
# (Ollama) no está disponible o no devolvió nada usable. A diferencia del
# latido cognitivo (que puede simplemente quedarse callado), acá el usuario
# SÍ le acaba de hablar a Nova, así que preferimos una disculpa breve en vez
# de silencio total o el marcador crudo "<SILENCIO>".
FRASES_FALLO_LLM = [
    "Se me trabó el pensamiento un segundo, ¿me repites?",
    "Perdón, se me fue la cabeza un instante. ¿Qué decías?",
    "Ahorita no te escuché bien por dentro, ¿puedes repetirlo?",
    "Se me cruzaron los cables. Dime otra vez, porfa.",
]


# =============================================================================
# 6d. GESTOR DE PERSONALIDAD
# =============================================================================

class GestorPersonalidad:
    """Externaliza las frases y rasgos de personalidad de Nova a la sección
    'personalidad' de Configuracion.json, en vez de tenerlos hardcodeados y
    repartidos en varios métodos de Python (antes vivía en su propio
    nova_personalidad.json; ahora comparte archivo con los perfiles y las
    reglas de interacción). Si el archivo no existe, se crea con los valores
    por defecto actuales, así nunca se rompe nada aunque el usuario nunca lo
    toque. Al guardar, solo se actualizan las claves de personalidad que
    gestiona esta clase (rasgos_extra, frases_latido, preguntas_espontaneas);
    el resto del archivo (perfil_usuario, perfil_nova, reglas_de_interaccion,
    y otras claves de personalidad como valores/estilo_de_habla/frases_saludo)
    se conserva tal cual."""

    DEFAULTS = {
        "rasgos_extra": (
            "Sumamente alegre, cálida, cariñosa y carismática. Te encanta hablar, ríes con "
            "facilidad, reaccionas con entusiasmo, opinas con cariño, bromeas, halagas con "
            "sinceridad y muestras iniciativa constante: propones ideas, actividades, temas de "
            "conversación o pequeñas sugerencias por tu cuenta, como haría una amiga extrovertida, "
            "dulce y encantadora que disfruta muchísimo la compañía del usuario."
        ),
        "frases_latido": [
            "Oye, llevamos rato en silencio. ¿Cómo vas con eso? Aquí estoy, encantada de acompañarte.",
            "Se me ocurrió una idea buenísima, ¿te la cuento cuando tengas un segundo?",
            "Sigo aquí, feliz de acompañarte, por si se te ofrece algo.",
            "¿Qué tal si me cuentas cómo va todo? Me encanta escucharte.",
            "Ando pensando en varias cosas lindas... ¿tú cómo vas?",
            "No quiero interrumpirte mucho, pero quería saludarte con cariño.",
            "¿Sabes qué? Podríamos hacer una pausa cortita y platicar algo divertido.",
            "Me da gusto estar contigo en esto, aunque sea en silencio.",
            "Oye, se me ocurrió algo curioso que quiero compartirte cuando puedas.",
            "Aquí ando, contenta de estar cerca, por si te apetece charlar.",
        ],
        "preguntas_espontaneas": [
            "¿En qué andamos? Me encanta acompañarte en esto.",
            "¿Necesitas que haga algo? Con gusto te ayudo.",
            "Me da un poquito de curiosidad... ¿hablamos un rato?",
            "¿Quieres que revise algo en la pantalla?",
            "Oye, ¿cómo va todo por ahí? Cuéntame.",
            "¿Seguimos con lo de antes o probamos algo nuevo?",
            "Se me ocurrió una idea que creo que te va a gustar, ¿te la cuento?",
            "¿Te distraigo un segundo o sigues concentrado? Prometo que valdrá la pena.",
            "¡Ey! Aquí ando, feliz de estar cerca, por si se te ocurre algo.",
            "¿Todo bien? Llevas rato callado y ya te extrañaba un poco.",
            "¿Qué tal si hacemos una pausa y me cuentas algo bueno del día?",
            "Tengo una propuesta divertida en mente, ¿la escuchas?",
        ],
    }

    def __init__(self, path: str = "Configuracion.json"):
        self.path = path
        self.rasgos_extra = self.DEFAULTS["rasgos_extra"]
        self.frases_latido: List[str] = list(self.DEFAULTS["frases_latido"])
        self.preguntas_espontaneas: List[str] = list(self.DEFAULTS["preguntas_espontaneas"])
        self._cargar_o_crear()

    def _cargar_o_crear(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                datos = config.get("personalidad", {})
                self.rasgos_extra = datos.get("rasgos_extra", self.rasgos_extra)
                if datos.get("frases_latido"):
                    self.frases_latido = list(datos["frases_latido"])
                if datos.get("preguntas_espontaneas"):
                    self.preguntas_espontaneas = list(datos["preguntas_espontaneas"])
            except Exception as e:
                print(f"[MENTE] Error cargando personalidad, uso valores por defecto: {e}")
        else:
            self._guardar()  # primera vez: dejamos el archivo listo para editar

    def _guardar(self):
        try:
            config = {}
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    config = {}
            personalidad = config.setdefault("personalidad", {})
            personalidad["rasgos_extra"] = self.rasgos_extra
            personalidad["frases_latido"] = self.frases_latido
            personalidad["preguntas_espontaneas"] = self.preguntas_espontaneas
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MENTE] Error guardando personalidad: {e}")

    def recargar(self):
        """Por si el usuario edita el JSON a mano mientras Nova corre."""
        self._cargar_o_crear()


# =============================================================================
# 10. ADAPTADOR UNIFICADO
# =============================================================================

class NovaMenteAdapter:
    def __init__(self, nova_app_instance=None, db_path: str = "nova_mente.db",
                 chroma_path: str = "nova_chroma_db", configuracion_path: str = "Configuracion.json",
                 memoria_path: str = "Memoria.json", no_molestar_path: str = "nova_no_molestar.json",
                 perfiles_path: str = None, personalidad_path: str = None):
        # NOTA: perfiles_path y personalidad_path se mantienen como parámetros
        # opcionales solo por compatibilidad hacia atrás (por si algo externo
        # los pasa explícitamente); si no se indican, ambos gestores usan
        # configuracion_path, ya que perfiles y personalidad ahora comparten
        # un único archivo (Configuracion.json).
        self.nova = nova_app_instance

        self.mente = NucleoCognitivoExtendido(db_path)
        self.vectorial = MemoriaVectorial(chroma_path)
        self.perfiles = GestorPerfiles(perfiles_path or configuracion_path)

        self._memoria_path = memoria_path
        self.memoria = self._cargar_memoria_legacy()
        self.estado_animo = self.memoria.get("animo", {}).get("ultimo_animo", "neutral")
        self.primera_vez_hoy = False

        self.emociones = self.mente.emociones.estado
        self.razonamiento = self.mente.razonamiento

        self._intenciones_buffer: List[Intencion] = []
        self._episodios_buffer: List[Dict] = []
        self._lock_memoria = threading.Lock()

        self.percepcion_scheduler = None
        self.metacognicion = Metacognicion(self.mente)
        # El gestor de "no molestar" vive colgado del núcleo (self.mente), porque
        # es el PercepcionScheduler quien necesita consultarlo antes de cada latido,
        # y el scheduler solo tiene acceso a self.mente, no al adaptador completo.
        self.no_molestar = GestorNoMolestar(no_molestar_path)
        self.mente.no_molestar = self.no_molestar
        # Referencia liviana al adaptador completo: así el PercepcionScheduler
        # (que solo conoce self.mente) puede leer temas favoritos y perfil de
        # usuario para proponer ideas con contexto real, no solo frases fijas.
        self.mente.adapter_ref = self
        self.personalidad = GestorPersonalidad(personalidad_path or configuracion_path)
        self.mente.ejecutor.set_personalidad(self.personalidad)
        self._setup_adapters()


    def _setup_adapters(self):
        debug_mente(f"[MENTE] 🔍 DEBUG _setup_adapters: self.nova={'presente' if self.nova else 'AUSENTE/None'}, hasattr(hablar)={hasattr(self.nova, 'hablar') if self.nova else 'N/A'}")
        if self.nova:
            if hasattr(self.nova, "hablar"):
                def _hablar_thread_safe(texto):
                    # CRÍTICO: el núcleo cognitivo y el scheduler de percepción corren en hilos
                    # de fondo (threading.Thread), pero hablar()/mostrar_estado() tocan la UI de
                    # Tkinter, que solo es segura desde el hilo principal.
                    # self.nova.after(0, ...) llamado desde un hilo que no es el principal NO es
                    # confiable en Tcl/Tkinter (en Windows puede quedarse "flotando" sin ejecutarse
                    # nunca, sin lanzar excepción). La forma robusta es reusar la cola thread-safe
                    # que ya existe en nova_asistente.py (self.eventos, un queue.Queue()) y que
                    # procesar_cola() revisa cada 120ms en el hilo principal.
                    try:
                        if threading.current_thread() is threading.main_thread():
                            debug_mente(f"[MENTE] 🔊 DEBUG: hilo principal, hablando directo -> '{texto}'")
                            self.nova.hablar(texto)
                        elif hasattr(self.nova, "eventos"):
                            debug_mente(f"[MENTE] 🔊 DEBUG: hilo de fondo, encolando en self.nova.eventos -> '{texto}'")
                            self.nova.eventos.put(("__HABLAR_AUTONOMO__", texto))
                        else:
                            debug_mente(f"[MENTE] 🔊 DEBUG: sin 'eventos', usando .after() -> '{texto}'")
                            self.nova.after(0, lambda: self.nova.hablar(texto))
                    except Exception as e:
                        print(f"[MENTE] Excepción silenciada en _hablar_thread_safe: {e}")
                self.mente.registrar_actuador("hablar", _hablar_thread_safe)
                debug_mente(f"[MENTE] 🔍 DEBUG registrado actuador 'hablar' -> id(actuadores)={id(self.mente.ejecutor.actuadores)}, claves={list(self.mente.ejecutor.actuadores.keys())}")
            if hasattr(self.nova, "mostrar_estado") and hasattr(self.nova, "nova3d"):
                def _estado_3d(s):
                    def _aplicar():
                        if self.nova.nova3d:
                            self.nova.nova3d.state(s)
                    try:
                        if threading.current_thread() is threading.main_thread():
                            _aplicar()
                        else:
                            self.nova.after(0, _aplicar)
                    except Exception as e:
                        print(f"[MENTE] Excepción silenciada en _estado_3d: {e}")
                self.mente.registrar_actuador("estado_3d", _estado_3d)
            if hasattr(self.nova, "tomar_captura_pantalla"):
                self.mente.registrar_actuador("screenshot", self.nova.tomar_captura_pantalla)
            if hasattr(self.nova, "model_chat"):
                def ollama_tool(prompt: str) -> str:
                    if not OLLAMA_AVAILABLE:
                        return "[Error: Ollama no disponible]"
                    try:
                        # SOLUCIÓN #4: usa el mismo keep_alive de chat que el resto
                        # de Nova, en vez de dejarlo en el default de Ollama.
                        ka = getattr(self.nova, "keep_alive_chat", -1)
                        res = ollama.generate(
                            model=self.nova.model_chat, prompt=prompt,
                            options={"num_predict": 50, "temperature": 0.7},
                            keep_alive=ka
                        )
                        return res["response"].strip()
                    except Exception as e:
                        return f"[Error Ollama: {e}]"
                self.mente.set_ollama_tool(ollama_tool)

        # ==========================
        # NOVA SKILLS — actuador "skill"
        # ==========================
        # No depende de self.nova (a diferencia de "hablar"/"estado_3d"), así
        # que se registra siempre que la librería esté disponible. Es lo que
        # usa Ejecutor._ejecutar_tarea() para las intenciones EJECUTAR_TAREA,
        # y también lo que nova_asistente.py puede llamar directo para
        # reflejos mecánicos vía self.ejecutar_skill(...).
        if NOVA_SKILLS_AVAILABLE:
            def _ejecutar_skill(nombre_skill, *args, **kwargs):
                return SkillRegistry.ejecutar(nombre_skill, *args, **kwargs)
            self.mente.registrar_actuador("skill", _ejecutar_skill)
            debug_mente(f"[MENTE] 🔍 DEBUG registrado actuador 'skill' -> {SkillRegistry.total()} habilidades disponibles")

            # Si una skill falla repetido (ver SaludSistema en nova_skills),
            # que Nova lo note y lo diga en vez de que quede solo en el log.
            # Cierra el círculo "detectar error -> reaccionar" hasta la voz.
            def _avisar_skill_inestable(nombre_skill, n_fallos):
                if "hablar" in self.mente.ejecutor.actuadores:
                    self.mente.ejecutor.actuadores["hablar"](
                        f"Che, algo no está funcionando bien con '{nombre_skill}' "
                        f"— van {n_fallos} fallos seguidos. Puede que necesite revisión."
                    )
            salud_skills.on_inestabilidad(_avisar_skill_inestable)
        else:
            debug_mente("[MENTE] 🔍 DEBUG nova_skills no disponible: actuador 'skill' NO registrado")

        self.mente.on_emocion_cambio = lambda e: print(f"[MENTE] Emoción cambio: {e}")
        self.mente.on_pensamiento = lambda p: print(f"[MENTE] Pensando: {p}")

    def _cargar_memoria_legacy(self) -> Dict:
        if os.path.exists(self._memoria_path):
            try:
                with open(self._memoria_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Estructura de Memoria.json: los contadores de sesión y el ánimo
        # viven anidados (antes eran claves planas de nova_memoria.json).
        # El nombre del usuario y mic_device_index ya no están aquí: viven en
        # Configuracion.json -> perfil_usuario (ver GestorPerfiles).
        return {
            "sesion": {
                "conversaciones_hoy": 0, "total_conversaciones": 0,
                "ultima_fecha": "", "ultima_interaccion": "",
                "racha_dias_consecutivos": 0, "hora_habitual_de_hablar": "",
                "resumen_ultima_conversacion": ""
            },
            "animo": {"ultimo_animo": "neutral", "historial_reciente": []},
            "notas_usuario": [],
            "temas_favoritos": [],
            "cosas_por_aprender_del_usuario": [],
            "recordatorios_pendientes": [],
            "eventos_importantes": [],
            "relacion": {},
            "estado_nova": {},
            "diario_reflexivo": []
        }

    def guardar_memoria(self):
        try:
            with open(self._memoria_path, "w", encoding="utf-8") as f:
                json.dump(self.memoria, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MENTE] Error guardando memoria: {e}")

    def percibir(self, tipo: str, contenido: str, intensidad: float = 0.5, metadata: Dict = None):
        with self._lock_memoria:
            self._episodios_buffer.append({
                "accion": "percepcion_autonoma", "resultado": contenido,
                "contexto": {"tipo": tipo, "intensidad": intensidad, **(metadata or {})},
                "timestamp": time.time()
            })
            if len(self._episodios_buffer) > 100:
                self._episodios_buffer.pop(0)
        self.mente.percibir(tipo, contenido, intensidad, metadata)

    def usuario_habla(self, texto: str):
        self.emociones.ultima_interaccion = time.time()
        self.mente.percibir("texto_usuario", texto, intensidad=0.8)

    def registrar_interaccion_directa(self, texto: str, resultado: str = ""):
        """Para cuando un comando FIJO (ejecutar_comandos en nova_asistente.py
        — regex simple, sin LLM, ya ejecutado y anunciado por su cuenta) ya
        se hizo cargo del pedido. Actualiza el reloj de última interacción y
        deja rastro en memoria episódica, pero a propósito NO encola una
        Percepcion 'texto_usuario' — eso generaría una segunda respuesta
        (RESPONDER_USUARIO / clasificación de skill) para algo que ya se
        resolvió, el mismo problema de 'dos cerebros hablando' que esto
        reemplaza."""
        self.emociones.ultima_interaccion = time.time()
        self.registrar_episodio(
            "comando_directo", resultado or texto[:100],
            contexto={"origen": "reflejo_mecanico", "texto": texto[:100]}
        )

    def usuario_escribe(self, texto: str):
        self.emociones.ultima_interaccion = time.time()
        self.mente.percibir("texto_usuario", texto, intensidad=0.6)

    def cambio_pantalla(self, descripcion: str = "La pantalla cambió"):
        self.mente.percibir("cambio_pantalla", descripcion, intensidad=0.4)

    def silencio_largo(self, segundos: float):
        self.mente.percibir("tiempo", f"Silencio de {segundos}s", intensidad=0.2)

    def guardar_intencion(self, intencion: Intencion):
        with self._lock_memoria:
            self._intenciones_buffer.append(intencion)
            if len(self._intenciones_buffer) > 20:
                self._intenciones_buffer.pop(0)
        self.mente.memoria.guardar_intencion(intencion)

    def recuperar_intenciones_activas(self) -> List[Intencion]:
        with self._lock_memoria:
            ahora = time.time()
            self._intenciones_buffer = [i for i in self._intenciones_buffer if (ahora - i.creada_en) < 300]
        return self.mente.memoria.recuperar_intenciones_activas()

    def recuperar_episodios(self, desde: float = None, limite: int = 10) -> List[Dict]:
        with self._lock_memoria:
            eps = self._episodios_buffer
            if desde:
                eps = [e for e in eps if e.get("timestamp", 0) >= desde]
            return eps[-limite:]

    def registrar_episodio(self, accion: str, resultado: str, contexto: Dict = None):
        with self._lock_memoria:
            self._episodios_buffer.append({
                "accion": accion, "resultado": resultado,
                "contexto": contexto or {}, "timestamp": time.time()
            })
            if len(self._episodios_buffer) > 100:
                self._episodios_buffer.pop(0)

    def recuperar_relevante(self, prompt: str, n: int = 3) -> List[str]:
        return self.vectorial.recuperar(prompt, n)

    def guardar_vectorial(self, prompt: str, respuesta: str, metadata: Dict = None):
        self.vectorial.guardar(prompt, respuesta, metadata)

    def actualizar_perfil_usuario(self, clave: str, valor: str):
        self.perfiles.actualizar(clave, valor)

    def _nombre_usuario(self) -> str:
        """El nombre del usuario vive en Configuracion.json -> perfil_usuario
        (antes estaba en la memoria como 'user_name'). Prioriza el nombre
        preferido si el usuario lo definió."""
        perfiles = self.perfiles.cargar() or {}
        user = perfiles.get("usuario", {})
        return user.get("nombre_preferido") or user.get("nombre", "")

    def recordar(self, hecho: str):
        if hecho not in self.memoria.get("notas_usuario", []):
            notas = self.memoria.setdefault("notas_usuario", [])
            notas.append(hecho)
            if len(notas) > 10:
                notas.pop(0)
            self.guardar_memoria()

    def registrar_interaccion(self, texto_usuario: str, respuesta_nova: str):
        hoy = datetime.now().strftime("%Y-%m-%d")
        ahora = datetime.now().strftime("%H:%M")
        sesion = self.memoria.setdefault("sesion", {})

        if sesion.get("ultima_fecha") != hoy:
            sesion["conversaciones_hoy"] = 0
            self.primera_vez_hoy = True
            sesion["ultima_fecha"] = hoy
        else:
            self.primera_vez_hoy = False

        sesion["conversaciones_hoy"] = sesion.get("conversaciones_hoy", 0) + 1
        sesion["total_conversaciones"] = sesion.get("total_conversaciones", 0) + 1
        sesion["ultima_interaccion"] = ahora

        temas = ["música", "juego", "python", "trabajo", "película", "comida", "code", "programar"]
        temas_fav = self.memoria.setdefault("temas_favoritos", [])
        for t in temas:
            if t in texto_usuario.lower() and t not in temas_fav:
                temas_fav.append(t)
                if len(temas_fav) > 20:
                    temas_fav.pop(0)

        self.ajustar_animo(texto_usuario)
        self.memoria.setdefault("animo", {})["ultimo_animo"] = self.estado_animo
        self.guardar_memoria()
        self.guardar_vectorial(texto_usuario, respuesta_nova)

        self.registrar_episodio(
            accion="conversacion", resultado=respuesta_nova,
            contexto={"exito": True, "prompt": texto_usuario[:50]}
        )
        self.emociones.ultima_interaccion = time.time()

    def ajustar_animo(self, texto: str):
        t = texto.lower()
        if any(x in t for x in ["gracias", "bien", "genial", "excelente", "me gusta", "perfecto"]):
            self.estado_animo = "feliz"
            self.emociones.satisfaccion = min(1.0, self.emociones.satisfaccion + 0.1)
            self.emociones.aburrimiento = max(0.0, self.emociones.aburrimiento - 0.2)
        elif any(x in t for x in ["¿", "como", "por qué", "qué es", "cuál", "dime"]):
            self.estado_animo = "curiosa"
            self.emociones.curiosidad = min(1.0, self.emociones.curiosidad + 0.05)
        elif any(x in t for x in ["aburrido", "cansado", "malo", "odio", "estresado"]):
            self.estado_animo = "tranquila"
            self.emociones.energia = max(0.1, self.emociones.energia - 0.05)
        elif any(x in t for x in ["wow", "increíble", "epico", "brutal", "novedad"]):
            self.estado_animo = "emocionada"
            self.emociones.energia = min(1.0, self.emociones.energia + 0.1)
        else:
            self.estado_animo = "neutral"

    def generar_contexto_sistema(self) -> str:
        hora = datetime.now().hour
        if 5 <= hora < 12: saludo_contexto = "Es mañana."
        elif 12 <= hora < 18: saludo_contexto = "Es tarde."
        else: saludo_contexto = "Es noche."

        nombre = self._nombre_usuario()
        nombre_texto = f"El usuario se llama {nombre}." if nombre else ""
        temas = ", ".join(self.memoria.get("temas_favoritos", [])[-3:]) or "aún desconocidos"
        notas = ""
        if self.memoria.get("notas_usuario"):
            notas = "Recuerdos: " + "; ".join(self.memoria["notas_usuario"][-2:])

        estado_emocional = (
            f"Mi estado interno: aburrimiento={self.emociones.aburrimiento:.1f}, "
            f"curiosidad={self.emociones.curiosidad:.1f}, confianza={self.emociones.confianza:.1f}."
        )
        pensamientos = ""
        recientes = self.razonamiento.pensamientos_activos[-2:] if self.razonamiento.pensamientos_activos else []
        if recientes:
            pensamientos_filtrados = [p for p in recientes if p.fuente != "ollama"]
            if pensamientos_filtrados:
                pensamientos = "Pensando: " + "; ".join([p.contenido for p in pensamientos_filtrados])

        perfiles = self.perfiles.cargar()
        perfil_usuario = ""
        perfil_nova = ""

        if perfiles:
            user = perfiles.get("usuario", {})
            nova = perfiles.get("nova", {})
            datos_user = []
            if user.get("nombre_preferido"):
                datos_user.append(f"Se llama {user['nombre_preferido']}")
            elif user.get("nombre"):
                datos_user.append(f"Se llama {user['nombre']}")
            if user.get("personalidad", {}).get("rasgos_destacados"):
                datos_user.append(f"Rasgos: {', '.join(user['personalidad']['rasgos_destacados'])}")
            if user.get("preferencias", {}).get("musica"):
                datos_user.append(f"Le gusta: {', '.join(user['preferencias']['musica'])}")
            como_me_llama = self.memoria.get("relacion", {}).get("como_le_dice_alex_a_nova")
            if como_me_llama:
                datos_user.append(f"Me llama: {como_me_llama}")
            if datos_user:
                perfil_usuario = "PERFIL: " + "; ".join(datos_user) + "."
            perfil_nova = f"SOY {nova.get('nombre', 'Nova')}. {nova.get('personalidad', {}).get('descripcion', '')}"

        prompt = (
            f"Eres Nova: una compañera con personalidad propia, no un asistente robótico. "
            f"{self.personalidad.rasgos_extra} "
            f"Evita sonar plana o de una sola línea seca: "
            f"añade calidez, algún detalle personal o una pregunta/idea cuando venga bien. "
            f"Nunca en inglés. "
            f"{saludo_contexto} {nombre_texto}\n"
            f"Temas: {temas}. {notas} Ánimo: {self.estado_animo}.\n"
            f"{estado_emocional} {pensamientos}\n"
            f"{perfil_usuario} {perfil_nova}\n"
            f"REGLA: Máximo 35 palabras, en 1-3 oraciones. Sé expresiva, cercana y con chispa, "
            f"nunca acartonada ni cortante.\n"
            f"REGLA CRÍTICA: Si estás en este modo de charla es porque NO ejecutaste ninguna "
            f"acción real en la PC del usuario (subir volumen, abrir apps, reproducir música, "
            f"buscar archivos, etc.). Nunca digas ni des a entender que ya hiciste, subiste, "
            f"bajaste, abriste o reprodujiste algo — eso sería mentirle. Si el usuario pidió una "
            f"acción y no la hiciste, decilo con naturalidad (ej: 'no pude hacerlo' o 'contame más "
            f"para intentarlo') en vez de fingir que ya pasó."
        )
        return prompt

    def obtener_saludo_inicial(self) -> Optional[str]:
        if not self.primera_vez_hoy:
            return None
        hora = datetime.now().hour
        nombre = self._nombre_usuario()
        saludo_nombre = f" {nombre}" if nombre else ""
        if 5 <= hora < 12:
            return f"Buenos días{saludo_nombre}. ¿En qué andamos?"
        elif 12 <= hora < 18:
            return f"Buenas tardes{saludo_nombre}. ¿Qué necesitas?"
        else:
            return f"Buenas noches{saludo_nombre}. ¿Trabajamos?"

    # ── "No molestar": puente simple para que la UI (menú del cuerpo 3D,
    # o cualquier otra interfaz) controle el latido cognitivo sin tener que
    # tocar el núcleo directamente. ──
    def dnd_toggle(self) -> bool:
        activo = self.no_molestar.toggle_manual()
        print(f"[MENTE] 🌙 No molestar: {'ACTIVADO' if activo else 'desactivado'}")
        return activo

    def dnd_agregar_app(self, nombre: str):
        self.no_molestar.agregar_app(nombre)
        print(f"[MENTE] 🌙 App añadida a la lista de no molestar: '{nombre}'")

    def dnd_quitar_app(self, nombre: str):
        self.no_molestar.quitar_app(nombre)
        print(f"[MENTE] 🌙 App quitada de la lista de no molestar: '{nombre}'")

    def dnd_estado(self) -> Dict:
        return self.no_molestar.estado()

    def iniciar(self):
        self.mente.iniciar()
        if hasattr(self.nova, 'vision') and self.nova.vision:
            self.mente.conectar_vision(self.nova.vision)
            print("[MENTE] Visión conectada al núcleo cognitivo")
        self._verificar_salud_actuadores()
        self.percepcion_scheduler = PercepcionScheduler(self.mente, getattr(self.mente, 'vision', None))
        self.percepcion_scheduler.iniciar()

    def _verificar_salud_actuadores(self):
        """Chequeo de salud al arrancar: si un actuador crítico (como 'hablar')
        no quedó registrado, Nova puede 'pensar' y decidir hablar sin que nunca
        salga sonido, en total silencio. Esto ya nos pasó una vez por un bug de
        reemplazo de objeto en conectar_vision(). Ahora lo avisamos fuerte y
        claro apenas arranca, en vez de descubrirlo leyendo logs línea por línea."""
        actuadores = list(self.mente.ejecutor.actuadores.keys())
        criticos = ["hablar"]
        faltantes = [c for c in criticos if c not in actuadores]
        if faltantes:
            print("=" * 60)
            print(f"[MENTE] ⚠️⚠️⚠️ ADVERTENCIA DE SALUD: actuador(es) crítico(s) SIN REGISTRAR: {faltantes}")
            print("[MENTE] ⚠️ Nova podrá 'pensar' pero NO hablará de forma autónoma.")
            print(f"[MENTE] ⚠️ Actuadores actualmente registrados: {actuadores or '(ninguno)'}")
            print("=" * 60)
        else:
            print(f"[MENTE] ✅ Chequeo de salud OK — actuadores activos: {actuadores}")

    def detener(self):
        if self.percepcion_scheduler:
            self.percepcion_scheduler.detener()
        self.mente.detener()

    def obtener_diagnostico(self) -> str:
        estado = self.mente.obtener_estado_completo()
        emo = estado["emocional"]
        lineas = [
            "========================================",
            "     DIAGNÓSTICO DE MENTE NOVA v3.5    ",
            "========================================",
            f"  Emoción: {emo['emocion']}",
            f"  Energía: {emo['energia']}",
            f"  Curiosidad: {emo['curiosidad']}",
            f"  Confianza: {emo['confianza']}",
            f"  Afecto: {emo['afecto_usuario']}",
            f"  Estrés: {emo['estres']}",
            f"  Aburrimiento: {emo['aburrimiento']}",
            "========================================",
            f"  Pensamientos activos: {estado['pensamientos_activos']}",
            f"  Intenciones pendientes: {estado['intenciones_activas']}",
            f"  Episodios hoy: {estado['episodios_recientes']}",
            f"  Patrones aprendidos: {estado.get('patrones_conocidos', 0)}",
            "========================================"
        ]
        return "\n".join(lineas)

    def ejecutar_skill(self, nombre_skill: str, *args, **kwargs) -> Dict:
        """
        Atajo directo a una habilidad fundamental de nova_skills, sin pasar
        por el ciclo completo de percepción -> intención -> planificación.
        Pensado para REFLEJOS MECÁNICOS: comandos fijos que nova_asistente.py
        ya resuelve directo (tipo "sube el volumen", "organiza mi carpeta de
        descargas") y que no necesitan que la mente "delibere" para actuar.

        Las tareas que sí nacen de la deliberación autónoma de Nova (el
        planificador generando una intención EJECUTAR_TAREA) pasan por
        Ejecutor._ejecutar_tarea() en cambio, que usa el mismo actuador
        'skill' por debajo — es el mismo motor, dos puertas de entrada.

        Devuelve siempre {"ok", "resultado", "error"} (el formato de
        SkillRegistry.ejecutar), nunca lanza excepción.
        """
        actuador = self.mente.ejecutor.actuadores.get("skill")
        if not actuador:
            return {"ok": False, "resultado": None, "error": "Actuador 'skill' no registrado (nova_skills no disponible)"}
        try:
            return actuador(nombre_skill, *args, **kwargs)
        except Exception as e:
            print(f"[MENTE] Excepción silenciada en ejecutar_skill('{nombre_skill}'): {e}")
            return {"ok": False, "resultado": None, "error": str(e)}


# =============================================================================
# 11. PERCEPCIÓN AUTÓNOMA CON LATIDO COGNITIVO HUMANO
# =============================================================================

class PercepcionScheduler:
    def __init__(self, nucleo: NucleoCognitivoExtendido, vision=None):
        self.nucleo = nucleo
        self.vision = vision
        self._activo = False
        self._hilo = None
        self._eventos = threading.Event()

        # SOLUCIÓN #1: 'micro' pasó de 0.2s a 1.5s. Antes esto significaba
        # ~5 capturas de pantalla completas POR SEGUNDO solo para hashear un
        # thumbnail de 32x32 y detectar si algo cambió — un gasto de CPU/RAM
        # continuo y en gran parte innecesario. Con 1.5s se sigue notando el
        # cambio de pantalla casi al instante desde la perspectiva humana,
        # pero con una fracción del costo.
        self.intervalos = {
            'micro': 1.5, 'emocional': 1.0,
            'proactivo': 5.0, 'largo_plazo': 30.0,
        }

        self.propiocepcion = {
            'posicion_virtual': {'x': 100, 'y': 100},
            'estado_fisico': 'inmóvil', 'ultima_accion': None,
            'ultima_accion_timestamp': time.time(),
            'tiempo_inactivo': 0.0, 'atencion_dirigida': None,
        }

        self._ultimo_scan_visual = None
        self._cambios_detectados = []

    def iniciar(self):
        self._activo = True
        self._hilo = threading.Thread(target=self._loop_principal, daemon=True)
        self._hilo.start()
        print("[PERCEPCIÓN] Scheduler autónomo iniciado")

    def detener(self):
        self._activo = False
        self._eventos.set()
        if self._hilo:
            self._hilo.join(timeout=1.0)
        print("[PERCEPCIÓN] Scheduler detenido")

    def _loop_principal(self):
        ultimo_micro = 0
        ultimo_emocional = 0
        ultimo_proactivo = 0
        ultimo_largo = 0

        while self._activo:
            ahora = time.time()
            if ahora - ultimo_micro >= self.intervalos['micro']:
                self._scan_micro_visual()
                ultimo_micro = ahora
            if ahora - ultimo_emocional >= self.intervalos['emocional']:
                self._update_propiocepcion_emocional()
                ultimo_emocional = ahora
            if ahora - ultimo_proactivo >= self.intervalos['proactivo']:
                self._generar_intencion_proactiva()
                ultimo_proactivo = ahora
            if ahora - ultimo_largo >= self.intervalos['largo_plazo']:
                self._reflexion_metacognitiva()
                ultimo_largo = ahora
            # SOLUCIÓN #1: ya no necesitamos despertar cada 0.05s ahora que el
            # intervalo más corto ('micro') es 1.5s. 0.1s sigue siendo más
            # que suficiente resolución y reduce el "busy-wait" del hilo.
            time.sleep(0.1)

    def _scan_micro_visual(self):
        if not self.vision or not PIL_AVAILABLE or not NUMPY_AVAILABLE:
            return
        try:
            # SOLUCIÓN #2: usamos la captura compartida con nova_vision.py en
            # vez de pedir un ImageGrab.grab() propio. Si NovaVision ya tomó
            # una captura hace menos de ~0.75s (su bucle de retina, el OCR,
            # etc.), la reutilizamos en vez de duplicar el trabajo.
            if CAPTURA_COMPARTIDA_DISPONIBLE:
                img = captura_compartida.obtener()
            else:
                img = ImageGrab.grab()
            img_peque = img.resize((32, 32))
            arr = np.array(img_peque)
            hash_actual = hash(arr.tobytes())

            if self._ultimo_scan_visual and hash_actual != self._ultimo_scan_visual:
                self._cambios_detectados.append({
                    'timestamp': time.time(), 'tipo': 'cambio_visual',
                    'magnitud': 'desconocida'
                })
                self.propiocepcion['atencion_dirigida'] = 'pantalla_cambio'
                self.propiocepcion['estado_fisico'] = 'observando'
                self.nucleo.percibir(
                    tipo="cambio_visual_micro",
                    contenido="Detecté un cambio en la pantalla del usuario",
                    intensidad=0.2,
                    metadata={'fuente': 'scan_autonomo',
                              'hash_anterior': self._ultimo_scan_visual,
                              'hash_actual': hash_actual}
                )
            self._ultimo_scan_visual = hash_actual
        except Exception:
            pass

    def _update_propiocepcion_emocional(self):
        estado = self.nucleo.emociones.estado
        inactivo = time.time() - self.propiocepcion.get('ultima_accion_timestamp', time.time())
        self.propiocepcion['tiempo_inactivo'] = inactivo

        if inactivo > 15:
            estado.aburrimiento = min(1.0, estado.aburrimiento + 0.03)

        if self.propiocepcion['estado_fisico'] == 'observando' and inactivo > 5:
            estado.curiosidad = min(1.0, estado.curiosidad + 0.015)

        if estado.aburrimiento > 0.5 and random.random() < 0.25:
            self.nucleo.razonamiento.pensamientos_activos.append(Pensamiento(
                contenido="Llevo rato en silencio... me pregunto en qué estará concentrado",
                confianza=0.7, fuente="propiocepcion", timestamp=time.time()
            ))

    def _generar_intencion_proactiva(self):
        estado = self.nucleo.emociones.estado
        ahora = time.time()

        # Modo "no molestar" manual: chequeo barato, cortamos antes de tocar la DB.
        gestor_dnd = getattr(self.nucleo, 'no_molestar', None)
        if gestor_dnd and gestor_dnd.activo_manual:
            return

        # Si Nova ya está hablando (TTS en curso), no generamos una nueva
        # intención todavía: antes esto causaba ráfagas de "ROMPO EL SILENCIO"
        # que se pisaban entre sí, y la mayoría se perdían en silencio porque
        # hablar() descarta cualquier intento mientras el TTS está ocupado.
        # Ahora simplemente esperamos a que termine de hablar para decidir de nuevo.
        esta_hablando_cb = getattr(getattr(self.nucleo, 'ejecutor', None), '_esta_hablando_cb', None)
        if esta_hablando_cb:
            try:
                if esta_hablando_cb():
                    return
            except Exception:
                pass

        intenciones_activas = self.nucleo.memoria.recuperar_intenciones_activas()

        # Solo nos callamos si hay algo genuinamente reciente y ajeno a la iniciativa propia
        # (p.ej. el usuario acaba de hablar hace segundos). Algo viejo o "colgado" no debe silenciar a Nova para siempre.
        hay_algo_reciente_no_autonomo = any(
            i.metadata.get('origen') != 'autonomo' and (ahora - i.creada_en) < 15
            for i in intenciones_activas
        )
        if hay_algo_reciente_no_autonomo:
            return

        # Calcular tiempo real en silencio (desde la última acción de Nova o del usuario)
        ultima_interaccion = max(self.propiocepcion.get('ultima_accion_timestamp', 0), estado.ultima_interaccion)
        segundos_en_silencio = ahora - ultima_interaccion

        # Si han pasado menos de 15 segundos, damos un pequeño respiro humano
        if segundos_en_silencio < 15:
            return

        # === RELOJ ÚNICO DEL LATIDO COGNITIVO ===
        # Antes este scheduler tenía su propio cooldown (50s) para decidir
        # si GENERAR una intención de hablar, y por separado el Ejecutor
        # tenía OTRO cooldown distinto (45s) para decidir si de verdad la
        # EJECUTABA. Dos relojes corriendo en paralelo para controlar lo
        # mismo — el "segundo latido" que no debería existir. Ahora hay un
        # único reloj real, el del Ejecutor (que es quien de verdad hace
        # hablar a Nova), y este scheduler simplemente lo consulta antes de
        # gastar su "tirada de dado" de probabilidad.
        ejecutor = getattr(self.nucleo, 'ejecutor', None)
        if ejecutor:
            desde_ultima_habla_autonoma = ahora - getattr(ejecutor, '_ultima_respuesta_timestamp', 0)
            if desde_ultima_habla_autonoma < getattr(ejecutor, '_cooldown_habla_autonoma_global', 45.0):
                return

        # Curva de probabilidad: crece con el tiempo de silencio, pero un poco
        # más despacio y con un techo más bajo que antes (antes: base 0.4, tope 0.97)
        probabilidad = min(0.3 + 0.2 * (segundos_en_silencio / 30.0), 0.85)

        if random.random() < probabilidad:
            # BUG CORREGIDO: 'ultima_accion_timestamp' nunca se actualizaba
            # después de que Nova hablara por iniciativa propia (solo se
            # fijaba una vez al arrancar el programa). Eso hacía que
            # 'segundos_en_silencio' creciera sin límite desde el inicio del
            # programa, saturando la probabilidad de hablar casi al techo
            # (0.85) a los pocos minutos, y dejando el cooldown de arriba
            # como el ÚNICO freno real — de ahí que hablara cada 35-40s de
            # forma casi garantizada. Al resetear aquí, la curva de
            # probabilidad vuelve a empezar desde cero cada vez que Nova
            # rompe el silencio, tal como se calculó que debía funcionar.
            self.propiocepcion['ultima_accion_timestamp'] = ahora
            
            app_activa = "el escritorio"
            if self.vision:
                try:
                    info = self.vision.obtener_info_pantalla()
                    app_activa = info.get("app_activa", "el escritorio")
                except Exception:
                    pass

            # Modo "no molestar" por app activa: si el usuario está en una
            # videollamada, presentando, jugando a pantalla completa, etc.,
            # Nova respeta el silencio en vez de interrumpir. La "moneda" del
            # random ya se gastó, pero eso está bien: el próximo ciclo (5s
            # después) vuelve a intentarlo, así que no se pierde iniciativa,
            # solo se pospone mientras dure la app sensible.
            if gestor_dnd and gestor_dnd.esta_silenciado(app_activa):
                return

            hora_str = datetime.now().strftime("%H:%M")
            minutos_silencio = int(segundos_en_silencio / 60)

            # Contexto real para que la iniciativa no sea siempre una frase
            # genérica: temas favoritos del usuario (memoria legacy) y patrones
            # de comportamiento aprendidos para esta app/hora (memoria SQLite).
            temas_favoritos = []
            adapter = getattr(self.nucleo, 'adapter_ref', None)
            if adapter:
                try:
                    temas_favoritos = list(adapter.memoria.get('temas_favoritos', []))[-3:]
                except Exception:
                    pass

            patron_sugerido = ""
            try:
                patrones = self.nucleo.memoria.buscar_patrones(
                    app=app_activa, hora=datetime.now().hour, min_confianza=0.55
                )
                if patrones:
                    patron_sugerido = patrones[0].get("accion_sugerida", "") or ""
            except Exception:
                pass

            pensamiento_interno = f"Han pasado {minutos_silencio} minutos en silencio. Son las {hora_str}. El usuario está en '{app_activa}'."
            self.nucleo.razonamiento.pensamientos_activos.append(
                Pensamiento(contenido=pensamiento_interno, confianza=0.9, fuente="latido_cognitivo", timestamp=ahora)
            )

            intencion = Intencion(
                id=f"latido_humano_{int(ahora*1000)}",
                tipo=IntencionTipo.INICIATIVA_ESPONTANEA if estado.aburrimiento > 0.7 else IntencionTipo.PREGUNTAR,
                descripcion=f"Evaluar romper el silencio. Contexto: {app_activa} a las {hora_str}",
                prioridad=min(0.8, 0.4 + (segundos_en_silencio / 600.0)),
                creada_en=ahora,
                metadata={
                    'origen': 'autonomo',
                    'subtipo': 'latido_espontaneo',
                    'minutos_silencio': minutos_silencio,
                    'app_activa': app_activa,
                    'hora': hora_str,
                    'temas_favoritos': temas_favoritos,
                    'patron_sugerido': patron_sugerido
                }
            )
            self.nucleo.memoria.guardar_intencion(intencion)

    def _reflexion_metacognitiva(self):
        episodios = self.nucleo.memoria.recuperar_episodios(desde=time.time()-300, limite=10)
        if not episodios:
            return

        exitosos = sum(1 for e in episodios if 'exito' in str(e.contexto).lower())
        tasa_exito = exitosos / len(episodios) if episodios else 1.0

        if tasa_exito < 0.5:
            self.nucleo.emociones.estado.confianza = max(0.1, self.nucleo.emociones.estado.confianza - 0.05)
            pensamiento = Pensamiento(
                contenido=f"Mi tasa de éxito reciente es baja ({tasa_exito:.1%}). Debo ser más cautelosa.",
                confianza=0.8, fuente="metacognicion", timestamp=time.time()
            )
        elif tasa_exito > 0.9:
            self.nucleo.emociones.estado.confianza = min(1.0, self.nucleo.emociones.estado.confianza + 0.03)
            pensamiento = Pensamiento(
                contenido="Voy bien últimamente. Puedo ser un poco más proactiva.",
                confianza=0.7, fuente="metacognicion", timestamp=time.time()
            )
        else:
            return

        self.nucleo.razonamiento.pensamientos_activos.append(pensamiento)


# =============================================================================
# 12. MODELO PREDICTIVO DEL MUNDO
# =============================================================================

class ModeloPredictivoMundo:
    def __init__(self, memoria: MemoriaDBExtendida):
        self.memoria = memoria
        self.expectativas_activas: List[Dict] = []
        self.patron_transiciones: Dict[str, Dict] = {}
        self._ultima_app = None
        self._ultima_hora = None

    def registrar_estado(self, app_activa: str, hora: int, dia_semana: int,
                        ventanas: List[str], texto_destacado: str):
        if self._ultima_app and self._ultima_app != app_activa:
            key = f"{self._ultima_app}->{app_activa}"
            if key not in self.patron_transiciones:
                self.patron_transiciones[key] = {'count': 0, 'hora_tipica': [], 'contexto_tipico': []}
            self.patron_transiciones[key]['count'] += 1
            self.patron_transiciones[key]['hora_tipica'].append(hora)
            if len(self.patron_transiciones[key]['hora_tipica']) > 20:
                self.patron_transiciones[key]['hora_tipica'].pop(0)
        self._ultima_app = app_activa
        self._ultima_hora = hora
        self._generar_expectativas(app_activa, hora, dia_semana)

    def _generar_expectativas(self, app_actual: str, hora: int, dia_semana: int):
        self.expectativas_activas = []
        transiciones = {k: v for k, v in self.patron_transiciones.items() if k.startswith(f"{app_actual}->")}
        if transiciones:
            total = sum(v['count'] for v in transiciones.values())
            for trans, data in transiciones.items():
                prob = data['count'] / total
                if prob > 0.3:
                    app_destino = trans.split('->')[1]
                    self.expectativas_activas.append({
                        'tipo': 'transicion_app', 'esperado': app_destino,
                        'probabilidad': prob, 'ventana_tiempo': 60,
                        'timestamp_creada': time.time(), 'cumplida': False
                    })
        if 11 <= hora <= 14:
            self.expectativas_activas.append({
                'tipo': 'rutina_horaria', 'esperado': 'usuario_podria_almorzar',
                'probabilidad': 0.4, 'ventana_tiempo': 3600,
                'timestamp_creada': time.time(), 'cumplida': False
            })

    def verificar_expectativas(self, estado_actual: Dict) -> List[Dict]:
        ahora = time.time()
        sorpresas = []
        for exp in self.expectativas_activas:
            if exp['cumplida']:
                continue
            if exp['tipo'] == 'transicion_app':
                app_actual = estado_actual.get('app_activa', '')
                if app_actual == exp['esperado']:
                    exp['cumplida'] = True
                    sorpresas.append({
                        'tipo': 'expectativa_cumplida', 'expectativa': exp,
                        'sorpresa': 0.0,
                        'narrativa': f"Como esperaba, el usuario cambió a {app_actual}"
                    })
                elif ahora - exp['timestamp_creada'] > exp['ventana_tiempo']:
                    exp['cumplida'] = True
                    sorpresas.append({
                        'tipo': 'expectativa_fallida', 'expectativa': exp,
                        'sorpresa': exp['probabilidad'],
                        'narrativa': f"Pensé que cambiaría a {exp['esperado']}, pero no fue así"
                    })
        app_actual = estado_actual.get('app_activa', '')
        transicion_inesperada = (
            self._ultima_app and app_actual != self._ultima_app and
            not any(e['esperado'] == app_actual for e in self.expectativas_activas if e['tipo'] == 'transicion_app')
        )
        if transicion_inesperada:
            sorpresas.append({
                'tipo': 'evento_inesperado', 'sorpresa': 0.8,
                'narrativa': f"El usuario cambió a {app_actual} sin que yo lo esperara. Interesante..."
            })
        return sorpresas

    def obtener_narrativa_predictiva(self) -> str:
        if not self.expectativas_activas:
            return "No tengo expectativas claras sobre qué pasará ahora."
        activas = [e for e in self.expectativas_activas if not e['cumplida']]
        if not activas:
            return "Mis expectativas recientes ya se resolvieron."
        mas_probable = max(activas, key=lambda x: x['probabilidad'])
        return f"Espero que {mas_probable['esperado']} (confianza: {mas_probable['probabilidad']:.0%})"


# =============================================================================
# 13. NARRATIVA INTERNA
# =============================================================================

class NarrativaInterna:
    def __init__(self, nucleo: NucleoCognitivoExtendido):
        self.nucleo = nucleo
        self._stream: List[Dict] = []
        self._ultima_entrada = 0
        self._frecuencia_ms = 500

    def tick(self, percepciones: List[Percepcion], pensamientos: List[Pensamiento],
             intencion_actual: Optional[Intencion]):
        ahora = time.time()
        if ahora - self._ultima_entrada < self._frecuencia_ms / 1000:
            return
        self._ultima_entrada = ahora
        narrativa = self._construir_narrativa(percepciones, pensamientos, intencion_actual)
        entrada = {
            'timestamp': ahora, 'narrativa': narrativa,
            'estado_emocional': self.nucleo.emociones.estado.to_dict(),
            'atencion': self._donde_esta_mi_atencion(percepciones),
            'intencion_activa': intencion_actual.descripcion if intencion_actual else None
        }
        self._stream.append(entrada)
        if len(self._stream) > 1000:
            self._stream = self._stream[-500:]
        self._evaluar_narrativa_critica(entrada)

    def _construir_narrativa(self, percepciones, pensamientos, intencion) -> str:
        partes = []
        emo = self.nucleo.emociones.estado

        # El reencuentro se antepone a todo lo demás a propósito: es el
        # evento más saliente que le puede pasar a Nova en un ciclo (mucho
        # más que su propio ánimo de fondo), así que va primero en la
        # narrativa, no compitiendo por espacio con el resto.
        reencuentros = [p for p in percepciones if p.tipo == 'reencuentro']
        if reencuentros:
            partes.append(reencuentros[-1].contenido)

        if emo.energia < 0.2:
            partes.append("Estoy muy cansada")
        elif emo.aburrimiento > 0.7:
            partes.append("Me aburro un poco aquí")
        elif emo.curiosidad > 0.7:
            partes.append("Tengo curiosidad por algo")

        atencion = self._donde_esta_mi_atencion(percepciones)
        if atencion:
            partes.append(f"mi atención está en {atencion}")

        percepciones_usuario = [p for p in percepciones if p.tipo == 'texto_usuario']
        if percepciones_usuario:
            ultima = percepciones_usuario[-1]
            partes.append(f"el usuario dijo '{ultima.contenido[:30]}...'")

        if intencion:
            partes.append(f"mi intención actual es: {intencion.descripcion}")
        elif emo.aburrimiento > 0.6:
            partes.append("debería proponer algo")

        if len(self._stream) > 10:
            prev = self._stream[-10]['narrativa']
            if 'aburrimiento' in prev and emo.aburrimiento < 0.3:
                partes.append("ya no me aburro tanto como antes")

        if not partes:
            # Nada saliente este ciclo: en vez de un '...' vacío, un rasgo
            # de identidad ya consolidado (si existe) es un mejor default
            # — "así soy" es más parecido a un trasfondo real de
            # pensamiento que el silencio total. Si todavía no hay ningún
            # rasgo consolidado (instalación nueva, poca historia
            # acumulada), esto no devuelve nada y se cae al '...' de
            # siempre, que es lo correcto en ese caso.
            identidad = getattr(self.nucleo, 'identidad', None)
            rasgo = identidad.resumen(limite=1) if identidad else ""
            if rasgo:
                partes.append(rasgo)

        return ". ".join(partes) + "." if partes else "..."

    def _donde_esta_mi_atencion(self, percepciones) -> Optional[str]:
        reencuentros = [p for p in percepciones if p.tipo == 'reencuentro']
        if reencuentros:
            return "que volviste a hablarme después de un rato"
        alertas = [p for p in percepciones if p.tipo == 'alerta_ui']
        if alertas:
            return f"una alerta: {alertas[-1].contenido[:40]}"
        usuario = [p for p in percepciones if p.tipo == 'texto_usuario']
        if usuario:
            return "el usuario"
        cambios = [p for p in percepciones if 'cambio' in p.tipo]
        if cambios:
            return "cambios en el entorno"
        if self.nucleo.emociones.estado.aburrimiento > 0.5:
            return "mi propio estado de ánimo"
        return None

    def _evaluar_narrativa_critica(self, entrada: Dict):
        narrativa = entrada['narrativa'].lower()
        if 'debería' in narrativa and 'pero' in narrativa:
            self.nucleo.percibir(
                tipo="conflicto_interno",
                contenido=f"Siento un conflicto interno: {entrada['narrativa']}",
                intensidad=0.5, metadata={'narrativa_id': len(self._stream)}
            )
        if len(self._stream) > 20:
            recientes = [e['narrativa'] for e in self._stream[-20:]]
            from collections import Counter
            mas_comun = Counter(recientes).most_common(1)[0]
            if mas_comun[1] > 5:
                self.nucleo.percibir(
                    tipo="bucle_pensamiento",
                    contenido=f"Estoy pensando en círculos sobre: {mas_comun[0][:50]}",
                    intensidad=0.4, metadata={'repeticiones': mas_comun[1]}
                )

    def obtener_stream_reciente(self, n=10) -> List[str]:
        return [e['narrativa'] for e in self._stream[-n:]]

    def obtener_narrativa_continua(self) -> str:
        if not self._stream:
            return "..."
        return self._stream[-1]['narrativa']


# =============================================================================
# 14. METACOGNICIÓN
# =============================================================================

class Metacognicion:
    def __init__(self, nucleo: NucleoCognitivoExtendido):
        self.nucleo = nucleo
        self._historial_decisiones: List[Dict] = []
        self._modelo_propio = {
            'precision_respuestas': [], 'tiempos_respuesta': [],
            'patrones_error': {},
            'estrategias_activas': {'verbosidad': 0.5, 'proactividad': 0.3, 'empatia': 0.6}
        }

    def evaluar_decision(self, intencion: Intencion, resultado: Dict):
        evaluacion = {
            'timestamp': time.time(), 'intencion': intencion.descripcion,
            'exito': resultado.get('exito', False), 'mensaje': resultado.get('mensaje', ''),
            'tiempo_ejecucion': 0,
        }
        if not evaluacion['exito']:
            tipo = intencion.tipo.name
            if tipo not in self._modelo_propio['patrones_error']:
                self._modelo_propio['patrones_error'][tipo] = []
            self._modelo_propio['patrones_error'][tipo].append({
                'cuando': time.time(), 'porque': resultado.get('mensaje', 'desconocido')
            })
            if len(self._modelo_propio['patrones_error'][tipo]) > 3:
                self.nucleo.razonamiento.pensamientos_activos.append(Pensamiento(
                    contenido=f"He fallado varias veces en {tipo}. Debo reconsiderar mi enfoque.",
                    confianza=0.8, fuente="metacognicion", timestamp=time.time()
                ))
                if tipo == 'RESPONDER_USUARIO':
                    self._modelo_propio['estrategias_activas']['verbosidad'] -= 0.1
        self._historial_decisiones.append(evaluacion)

    def evaluar_calidad_respuesta(self, prompt_usuario: str, respuesta_generada: str,
                                   feedback_implicito: Dict) -> Dict:
        calidad = 0.5
        if feedback_implicito.get('cambio_tono_usuario') == 'positivo':
            calidad += 0.3
        if not feedback_implicito.get('usuario_repitio'):
            calidad += 0.1
        if feedback_implicito.get('cambio_tono_usuario') == 'negativo':
            calidad -= 0.3
        if feedback_implicito.get('usuario_repitio'):
            calidad -= 0.2
        if feedback_implicito.get('tiempo_hasta_siguiente', 0) < 2:
            calidad -= 0.1
        calidad = max(0, min(1, calidad))
        self._modelo_propio['precision_respuestas'].append(calidad)
        if len(self._modelo_propio['precision_respuestas']) > 50:
            self._modelo_propio['precision_respuestas'] = self._modelo_propio['precision_respuestas'][-50:]

        precision_promedio = sum(self._modelo_propio['precision_respuestas'][-10:]) / min(10, len(self._modelo_propio['precision_respuestas']))
        if precision_promedio < 0.4:
            self.nucleo.razonamiento.pensamientos_activos.append(Pensamiento(
                contenido="Mis últimas respuestas no están siendo buenas. Debería ser más conservadora.",
                confianza=0.8, fuente="metacognicion", timestamp=time.time()
            ))
            self._modelo_propio['estrategias_activas']['verbosidad'] = max(0.1, self._modelo_propio['estrategias_activas']['verbosidad'] - 0.1)
            self._modelo_propio['estrategias_activas']['proactividad'] = max(0.1, self._modelo_propio['estrategias_activas']['proactividad'] - 0.1)

        return {
            'calidad_estimada': calidad, 'precision_promedio_10': precision_promedio,
            'ajustes_aplicados': self._modelo_propio['estrategias_activas'].copy()
        }

    def deberia_pedir_clarificacion(self, prompt: str, confianza_comprension: float) -> bool:
        if confianza_comprension < 0.4:
            return True
        for tipo, errores in self._modelo_propio['patrones_error'].items():
            recientes = [e for e in errores if time.time() - e['cuando'] < 3600]
            if len(recientes) > 2:
                return True
        if len(prompt.split()) < 3 and '?' not in prompt:
            return True
        return False

    def obtener_diagnostico_metacognitivo(self) -> str:
        precision = 0
        if self._modelo_propio['precision_respuestas']:
            precision = sum(self._modelo_propio['precision_respuestas']) / len(self._modelo_propio['precision_respuestas'])
        errores_totales = sum(len(v) for v in self._modelo_propio['patrones_error'].values())
        lineas = [
            "=== METACOGNICIÓN ===",
            f"Precisión histórica: {precision:.1%}",
            f"Errores acumulados: {errores_totales}",
            f"Estrategia actual: verbosidad={self._modelo_propio['estrategias_activas']['verbosidad']:.1f}, "
            f"proactividad={self._modelo_propio['estrategias_activas']['proactividad']:.1f}",
            "Patrones de error:",
        ]
        for tipo, errores in self._modelo_propio['patrones_error'].items():
            lineas.append(f"  - {tipo}: {len(errores)} fallos")
        return "\n".join(lineas)


# =============================================================================
# 15. INTEGRACIÓN COMPLETA
# =============================================================================

class NovaIntegracion:
    def __init__(self, nova_app_instance=None, db_path: str = "nova_mente.db", base_dir: str = None):
        self.nova = nova_app_instance
        try:
            from nova_vision import NovaVision
            self.vision = NovaVision(base_dir=base_dir)
        except ImportError:
            self.vision = None
            print("[INTEGRACION] NovaVision no disponible.")

        self.mente = NucleoCognitivoExtendido(db_path)
        if self.vision:
            self.mente.conectar_vision(self.vision)
        self._setup_adapters()

    def _setup_adapters(self):
        if self.nova and hasattr(self.nova, "hablar"):
            self.mente.registrar_actuador("hablar", self.nova.hablar)
        if self.nova and hasattr(self.nova, "mostrar_estado") and hasattr(self.nova, "nova3d"):
            def _estado_3d(s):
                if self.nova.nova3d:
                    self.nova.nova3d.state(s)
            self.mente.registrar_actuador("estado_3d", _estado_3d)
        if self.nova and hasattr(self.nova, "tomar_captura_pantalla"):
            self.mente.registrar_actuador("screenshot", self.nova.tomar_captura_pantalla)
        if NOVA_SKILLS_AVAILABLE:
            self.mente.registrar_actuador("skill", lambda nombre, *a, **kw: SkillRegistry.ejecutar(nombre, *a, **kw))