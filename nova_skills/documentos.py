"""
nova_skills/documentos.py — Creación y edición de documentos Word y Excel.
====================================================================
Mismo criterio que archivos.py: no alcanza con que python-docx/openpyxl
no hayan tirado una excepción — cada skill que MODIFICA un documento
vuelve a abrirlo después de guardar y VERIFICA que el cambio quedó
realmente ahí (un párrafo de más, una fila de más, el valor esperado en
la celda) antes de reportar éxito. Esto es lo que evita que Nova diga
"listo, ya escribí eso" cuando en realidad el archivo quedó vacío o a
medias por algún problema silencioso de la librería.
"""

import os
from typing import List, Optional
from ._core import skill, _requiere, logger

try:
    import docx
    DOCX_AVAILABLE = True
except Exception as e:
    DOCX_AVAILABLE = False
    logger.debug(f"[SKILLS] python-docx no disponible en documentos.py ({e})")

try:
    import openpyxl
    XLSX_AVAILABLE = True
except Exception as e:
    XLSX_AVAILABLE = False
    logger.debug(f"[SKILLS] openpyxl no disponible en documentos.py ({e})")


def _asegurar_extension(ruta: str, ext: str) -> str:
    """Si la ruta no termina en la extensión esperada, se la agrega —
    evita que un documento termine guardado sin extensión por un desliz
    del modelo al elegir el nombre de archivo."""
    if not ruta.lower().endswith(ext):
        ruta = ruta + ext
    return ruta


# =====================================================================
# WORD (.docx)
# =====================================================================

@skill("crear_documento_word", "documentos",
       "Crea un documento Word nuevo (.docx) con un título principal opcional. "
       "Si ya existe un archivo en esa ruta, lo sobrescribe.", requiere=["python-docx"])
def crear_documento_word(ruta: str, titulo: str = ""):
    _requiere(DOCX_AVAILABLE, "python-docx")
    ruta = _asegurar_extension(ruta, ".docx")
    doc = docx.Document()
    if titulo:
        doc.add_heading(titulo, level=0)
    doc.save(ruta)
    if not os.path.isfile(ruta):
        raise RuntimeError(f"El documento no quedó guardado: {ruta}")
    return ruta


@skill("agregar_titulo_word", "documentos",
       "Agrega un título/subtítulo a un documento Word existente. nivel=1 es "
       "el título de sección más grande, 2 una subsección, etc.", requiere=["python-docx"])
def agregar_titulo_word(ruta: str, texto: str, nivel: int = 1):
    _requiere(DOCX_AVAILABLE, "python-docx")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el documento: {ruta}")

    doc = docx.Document(ruta)
    parrafos_antes = len(doc.paragraphs)
    doc.add_heading(texto, level=max(1, min(4, nivel)))
    doc.save(ruta)

    verificacion = docx.Document(ruta)
    if len(verificacion.paragraphs) <= parrafos_antes:
        raise RuntimeError(f"El título no quedó agregado en {ruta}")
    return ruta


@skill("agregar_parrafo_word", "documentos",
       "Agrega un párrafo de texto normal al final de un documento Word existente.",
       requiere=["python-docx"])
def agregar_parrafo_word(ruta: str, texto: str):
    _requiere(DOCX_AVAILABLE, "python-docx")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el documento: {ruta}")

    doc = docx.Document(ruta)
    parrafos_antes = len(doc.paragraphs)
    doc.add_paragraph(texto)
    doc.save(ruta)

    verificacion = docx.Document(ruta)
    if len(verificacion.paragraphs) <= parrafos_antes:
        raise RuntimeError(f"El párrafo no quedó agregado en {ruta}")
    return ruta


@skill("agregar_tabla_word", "documentos",
       "Agrega una tabla a un documento Word. 'filas' es una lista de listas "
       "(cada sublista es una fila de celdas); la primera fila se usa como encabezado.",
       requiere=["python-docx"])
def agregar_tabla_word(ruta: str, filas: List[List[str]]):
    _requiere(DOCX_AVAILABLE, "python-docx")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el documento: {ruta}")
    if not filas or not filas[0]:
        raise ValueError("'filas' no puede estar vacío")

    doc = docx.Document(ruta)
    n_cols = len(filas[0])
    tabla_antes = len(doc.tables)
    tabla = doc.add_table(rows=0, cols=n_cols)
    try:
        tabla.style = "Light Grid Accent 1"
    except Exception:
        pass  # si el estilo no existe en esta plantilla, seguimos sin estilo
    for fila in filas:
        celdas = tabla.add_row().cells
        for i, valor in enumerate(fila[:n_cols]):
            celdas[i].text = str(valor)
    doc.save(ruta)

    verificacion = docx.Document(ruta)
    if len(verificacion.tables) <= tabla_antes:
        raise RuntimeError(f"La tabla no quedó agregada en {ruta}")
    if len(verificacion.tables[-1].rows) != len(filas):
        raise RuntimeError(f"La tabla quedó con menos filas de las esperadas en {ruta}")
    return ruta


@skill("leer_texto_word", "documentos",
       "Lee y devuelve todo el texto (párrafo por párrafo) de un documento Word existente.",
       requiere=["python-docx"])
def leer_texto_word(ruta: str) -> str:
    _requiere(DOCX_AVAILABLE, "python-docx")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el documento: {ruta}")
    doc = docx.Document(ruta)
    return "\n".join(p.text for p in doc.paragraphs)


@skill("contar_paginas_aproximadas_word", "documentos",
       "Estima cuántas páginas tiene un documento Word, basado en cantidad de "
       "palabras (Word no guarda la paginación real hasta abrirse). Sirve para "
       "que Nova sepa si un trabajo largo 'ya casi llega' a lo pedido.",
       requiere=["python-docx"])
def contar_paginas_aproximadas_word(ruta: str) -> int:
    _requiere(DOCX_AVAILABLE, "python-docx")
    texto = leer_texto_word(ruta)
    palabras = len(texto.split())
    # ~500 palabras por página a interlineado 1.5, fuente 12 — estimado,
    # no una medida exacta (eso depende del render final de Word).
    return max(1, round(palabras / 500))


# =====================================================================
# EXCEL (.xlsx)
# =====================================================================

@skill("crear_libro_excel", "documentos",
       "Crea un libro de Excel nuevo (.xlsx). Si ya existe, lo sobrescribe.",
       requiere=["openpyxl"])
def crear_libro_excel(ruta: str, nombre_hoja: str = "Hoja1"):
    _requiere(XLSX_AVAILABLE, "openpyxl")
    ruta = _asegurar_extension(ruta, ".xlsx")
    libro = openpyxl.Workbook()
    libro.active.title = nombre_hoja
    libro.save(ruta)
    if not os.path.isfile(ruta):
        raise RuntimeError(f"El libro no quedó guardado: {ruta}")
    return ruta


@skill("escribir_celda_excel", "documentos",
       "Escribe un valor en una celda puntual (ej. celda='A1') de una hoja.",
       requiere=["openpyxl"])
def escribir_celda_excel(ruta: str, celda: str, valor, hoja: Optional[str] = None):
    _requiere(XLSX_AVAILABLE, "openpyxl")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el libro: {ruta}")

    libro = openpyxl.load_workbook(ruta)
    ws = libro[hoja] if hoja else libro.active
    ws[celda] = valor
    libro.save(ruta)

    verificacion = openpyxl.load_workbook(ruta)
    ws_verif = verificacion[hoja] if hoja else verificacion.active
    if ws_verif[celda].value != valor:
        raise RuntimeError(f"La celda {celda} no quedó con el valor esperado en {ruta}")
    return {"celda": celda, "valor": valor}


@skill("agregar_fila_excel", "documentos",
       "Agrega una fila de valores al final de los datos existentes en una hoja.",
       requiere=["openpyxl"])
def agregar_fila_excel(ruta: str, valores: list, hoja: Optional[str] = None):
    _requiere(XLSX_AVAILABLE, "openpyxl")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el libro: {ruta}")

    libro = openpyxl.load_workbook(ruta)
    ws = libro[hoja] if hoja else libro.active
    fila_antes = ws.max_row
    ws.append(valores)
    libro.save(ruta)

    verificacion = openpyxl.load_workbook(ruta)
    ws_verif = verificacion[hoja] if hoja else verificacion.active
    if ws_verif.max_row <= fila_antes:
        raise RuntimeError(f"La fila no quedó agregada en {ruta}")
    return ws_verif.max_row


@skill("leer_celda_excel", "documentos",
       "Lee el valor de una celda puntual (ej. 'B3') de una hoja.",
       requiere=["openpyxl"])
def leer_celda_excel(ruta: str, celda: str, hoja: Optional[str] = None):
    _requiere(XLSX_AVAILABLE, "openpyxl")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el libro: {ruta}")
    libro = openpyxl.load_workbook(ruta)
    ws = libro[hoja] if hoja else libro.active
    return ws[celda].value


@skill("listar_hojas_excel", "documentos",
       "Lista los nombres de todas las hojas de un libro de Excel.",
       requiere=["openpyxl"])
def listar_hojas_excel(ruta: str) -> List[str]:
    _requiere(XLSX_AVAILABLE, "openpyxl")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el libro: {ruta}")
    libro = openpyxl.load_workbook(ruta)
    return libro.sheetnames


@skill("crear_hoja_excel", "documentos",
       "Crea una hoja nueva dentro de un libro de Excel existente.",
       requiere=["openpyxl"])
def crear_hoja_excel(ruta: str, nombre_hoja: str):
    _requiere(XLSX_AVAILABLE, "openpyxl")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No existe el libro: {ruta}")

    libro = openpyxl.load_workbook(ruta)
    if nombre_hoja in libro.sheetnames:
        raise ValueError(f"Ya existe una hoja llamada '{nombre_hoja}'")
    libro.create_sheet(nombre_hoja)
    libro.save(ruta)

    verificacion = openpyxl.load_workbook(ruta)
    if nombre_hoja not in verificacion.sheetnames:
        raise RuntimeError(f"La hoja '{nombre_hoja}' no quedó creada en {ruta}")
    return nombre_hoja