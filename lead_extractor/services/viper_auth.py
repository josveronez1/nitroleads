import json
import logging
import os
import sys
import subprocess
import fcntl
from pathlib import Path

logger = logging.getLogger(__name__)

# Diretório base do projeto (services/ -> lead_extractor/ -> projeto)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Caminho ABSOLUTO para o arquivo de tokens
# Usar diretório 'secure' fora de STATIC_ROOT para evitar exposição via web
SECURE_DIR = BASE_DIR / "secure"
TOKENS_FILE = SECURE_DIR / "viper_tokens.json"

# Caminho ABSOLUTO para o auth_bot.py
AUTH_BOT_PATH = BASE_DIR / "auth_bot.py"

# Timeout para execução do auth_bot (em segundos)
AUTH_BOT_TIMEOUT = 90


def get_auth_headers():
    """
    Lê o arquivo 'viper_tokens.json' de forma segura com file locking.
    
    Usa caminho ABSOLUTO para garantir que funcione independente do CWD.
    Usa file locking (fcntl.flock) para evitar race conditions.
    
    Returns:
        dict ou None: Headers de autenticação ou None se falhar
    """
    try:
        if not TOKENS_FILE.exists():
            logger.warning(f"Arquivo de tokens não encontrado: {TOKENS_FILE}")
            return None
        
        # Abrir com lock compartilhado (permite múltiplas leituras simultâneas)
        with open(TOKENS_FILE, "r") as f:
            try:
                # Lock compartilhado (LOCK_SH) - permite outras leituras
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                try:
                    data = json.load(f)
                    # Validar que tem os campos necessários
                    if 'Authorization' in data:
                        return data
                    else:
                        logger.warning("Arquivo de tokens não contém 'Authorization'")
                        return None
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except BlockingIOError:
                # Arquivo está sendo escrito, aguardar um pouco e tentar novamente
                logger.info("Arquivo de tokens está bloqueado, aguardando...")
                import time
                time.sleep(0.5)
                # Tentar novamente sem lock não-bloqueante
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    if 'Authorization' in data:
                        return data
                    return None
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON de tokens: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao ler tokens do Viper: {e}", exc_info=True)
        return None


def run_auth_bot() -> bool:
    """
    Executa o auth_bot.py de forma segura com timeout.
    
    - Usa caminho absoluto para o script
    - Usa o mesmo interpretador Python que está rodando
    - Preserva e adiciona variáveis de ambiente necessárias
    - Tem timeout para evitar travamento indefinido
    
    Returns:
        bool: True se executou com sucesso (exit code 0), False caso contrário
    """
    logger.info(f"Executando auth_bot: {AUTH_BOT_PATH}")
    
    if not AUTH_BOT_PATH.exists():
        logger.error(f"auth_bot.py não encontrado em: {AUTH_BOT_PATH}")
        return False
    
    # Preparar ambiente
    env = os.environ.copy()
    
    # Garantir que LD_LIBRARY_PATH está definido (necessário para Playwright/Chromium)
    ld_path = env.get('LD_LIBRARY_PATH', '')
    if '/usr/lib/x86_64-linux-gnu' not in ld_path:
        if ld_path:
            env['LD_LIBRARY_PATH'] = f"/usr/lib/x86_64-linux-gnu:{ld_path}"
        else:
            env['LD_LIBRARY_PATH'] = '/usr/lib/x86_64-linux-gnu'
    
    # Garantir PLAYWRIGHT_BROWSERS_PATH se não estiver definido
    if 'PLAYWRIGHT_BROWSERS_PATH' not in env:
        # Tentar detectar automaticamente
        home_dir = Path.home()
        playwright_cache = home_dir / '.cache' / 'ms-playwright'
        if playwright_cache.exists():
            env['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_cache)
    
    try:
        result = subprocess.run(
            [sys.executable, str(AUTH_BOT_PATH)],
            env=env,
            cwd=str(BASE_DIR),
            timeout=AUTH_BOT_TIMEOUT,
            capture_output=True,
            text=True
        )
        
        # Logar output do auth_bot
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                logger.info(f"[auth_bot] {line}")
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                logger.warning(f"[auth_bot stderr] {line}")
        
        if result.returncode == 0:
            logger.info("auth_bot executado com sucesso")
            return True
        else:
            logger.error(f"auth_bot falhou com código de saída: {result.returncode}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"auth_bot excedeu o timeout de {AUTH_BOT_TIMEOUT}s")
        return False
    except Exception as e:
        logger.error(f"Erro ao executar auth_bot: {e}", exc_info=True)
        return False