"""
nova_skills/red.py — Conectividad de red.
"""

import socket
import subprocess
from ._core import skill, IS_WINDOWS


@skill("verificar_conexion_internet", "red", "Comprueba si hay conexión a internet intentando alcanzar un DNS público.")
def verificar_conexion_internet(timeout: float = 3.0) -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except OSError:
        return False

@skill("obtener_ip_local", "red", "Devuelve la dirección IP local del equipo en la red.")
def obtener_ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

@skill("hacer_ping", "red", "Hace ping a un host y devuelve si respondió correctamente.")
def hacer_ping(host: str, intentos: int = 2) -> bool:
    flag = "-n" if IS_WINDOWS else "-c"
    resultado = subprocess.run(["ping", flag, str(intentos), host],
                                capture_output=True, timeout=intentos * 3 + 5)
    return resultado.returncode == 0
