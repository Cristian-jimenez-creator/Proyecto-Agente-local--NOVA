# NovaIA

NovaIA es un asistente de escritorio para Windows desarrollado en Python. Combina conversación con modelos locales, entrada y salida de voz, análisis visual y un avatar 3D. También incluye funciones de memoria, autonomía y control de aplicaciones del equipo.

## Funciones

- Interfaz de escritorio con `customtkinter`.
- Conversación local mediante Ollama.
- Reconocimiento de voz con Vosk y faster-whisper, y síntesis con Piper.
- Análisis de imágenes y pantalla con modelos de visión.
- Avatar 3D en formato VRM, presentado mediante una interfaz WebGL.
- Memoria semántica con ChromaDB y almacenamiento local.
- Skills para archivos, documentos, ventanas, teclado, ratón, multimedia y sistema.
- Módulos de identidad, atención, reencuentro y sueño.

## Requisitos

- Windows.
- Python 3.10 o posterior.
- Ollama instalado y en ejecución en `http://localhost:11434`.
- Modelos de Ollama requeridos por la configuración. El verificador busca `llama3.2:1b`, `llava:latest` y `moondream:latest`; `Configuracion.json` configura `llama3.2:1b` para chat y `gemma3:4b` para visión, con `moondream:latest` como alternativa.
- Micrófono y altavoces para las funciones de voz.

La aceleración GPU depende del hardware y de los controladores instalados. Las dependencias NVIDIA de `requirements.txt` están pensadas para acelerar faster-whisper con CUDA.

## Instalación

Abre PowerShell en la carpeta del proyecto y crea un entorno virtual:

```powershell
cd C:\NovaIA
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Instala Ollama y descarga los modelos que necesites. Por ejemplo:

```powershell
ollama pull llama3.2:1b
ollama pull gemma3:4b
ollama pull moondream:latest
```

El repositorio incluye archivos de voz Piper, un modelo Vosk y un avatar VRM. Asegúrate de que esos recursos estén presentes antes de iniciar la aplicación.

## Ejecución

Con el entorno virtual activado y Ollama en ejecución:

```powershell
python nova_asistente.py
```

Para comprobar dependencias, recursos y modelos disponibles:

```powershell
python verificar_instalacion.py
```

El verificador puede señalar modelos adicionales que no coincidan con la configuración actual; consulta `Configuracion.json` y ajusta la lista de modelos según el uso previsto.

## Estructura principal

| Archivo o carpeta | Propósito |
| --- | --- |
| `nova_asistente.py` | Aplicación principal e interfaz de escritorio |
| `nova_mente_core.py` | Memoria, conversación y lógica de autonomía |
| `nova_vision.py` | Funciones de visión y captura |
| `nova_3d_controller.py` | Control del avatar 3D |
| `Nova3D/` | Interfaz web y recursos del avatar |
| `nova_skills/` | Skills para interactuar con el equipo y sus archivos |
| `Gestor*.py` | Gestores de identidad, atención, reencuentro y sueño |
| `Configuracion.json` | Personalidad, parámetros y preferencias |
| `Memoria.json` y `nova_mente.db` | Datos de memoria locales |
| `requirements.txt` | Dependencias de Python |
| `verificar_instalacion.py` | Diagnóstico de instalación |

## Datos y privacidad

Nova guarda configuración, memoria, registros y cachés en archivos y carpetas locales del proyecto. El uso de modelos locales requiere que Ollama esté disponible. Revisa `Configuracion.json` y los módulos antes de habilitar funciones que interactúen con ventanas, teclado, ratón o archivos.

## Solución de problemas

- Si Ollama no responde, inicia el servicio y comprueba que esté disponible en `http://localhost:11434`.
- Si falta un modelo, descárgalo con `ollama pull <nombre-del-modelo>` y verifica el nombre configurado.
- Si falla una función de voz, confirma que los dispositivos de audio estén disponibles y que los archivos de modelo Piper/Vosk estén presentes.
- Consulta `logs/nova_asistente.log` para ver errores de ejecución.
- Ejecuta `python verificar_instalacion.py` para obtener un diagnóstico general.
