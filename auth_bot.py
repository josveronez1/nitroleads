#!/usr/bin/env python
"""
Robô de autenticação do Viper.
Usa Playwright para fazer login e capturar tokens de sessão.

IMPORTANTE: Este script usa caminhos absolutos para garantir
que funcione corretamente quando chamado via subprocess do Supervisor.
"""
import json
import sys
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from decouple import config

# Diretório base do projeto (onde este arquivo está)
BASE_DIR = Path(__file__).resolve().parent

# Caminho ABSOLUTO para o arquivo de tokens
# Usar diretório 'secure' fora de STATIC_ROOT para evitar exposição via web
SECURE_DIR = BASE_DIR / "secure"
SECURE_DIR.mkdir(exist_ok=True, mode=0o700)  # Criar diretório com permissões restritas (700)
TOKENS_FILE = SECURE_DIR / "viper_tokens.json"

# Carrega credenciais do .env
VIPER_USER = config('VIPER_USER', default='')
VIPER_PASS = config('VIPER_PASS', default='')


def save_tokens_atomic(data: dict) -> bool:
    """
    Salva tokens de forma atômica para evitar race conditions.
    Escreve em arquivo temporário e depois renomeia.
    
    Args:
        data: Dicionário com os tokens
        
    Returns:
        bool: True se salvou com sucesso, False caso contrário
    """
    try:
        # Criar arquivo temporário no mesmo diretório (para garantir mesmo filesystem)
        fd, temp_path = tempfile.mkstemp(
            suffix='.json.tmp',
            prefix='viper_tokens_',
            dir=str(SECURE_DIR)
        )
        
        try:
            # Escrever no arquivo temporário
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Garante que dados foram escritos no disco
            
            # Renomear atomicamente (operação atômica no mesmo filesystem)
            os.rename(temp_path, str(TOKENS_FILE))
            return True
            
        except Exception as e:
            # Limpar arquivo temporário em caso de erro
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e
            
    except Exception as e:
        print(f"[ERRO] Falha ao salvar tokens: {e}")
        return False


def refresh_viper_tokens() -> bool:
    """
    Faz login no Viper e captura tokens de autenticação.
    
    Returns:
        bool: True se capturou tokens com sucesso, False caso contrário
    """
    print("[INFO] Iniciando robô de autenticação Viper...")
    print(f"[INFO] Arquivo de tokens: {TOKENS_FILE}")
    
    if not VIPER_USER or not VIPER_PASS:
        print("[ERRO] VIPER_USER ou VIPER_PASS não configurados no .env")
        return False

    browser = None
    try:
        with sync_playwright() as p:
            print("[INFO] Iniciando navegador Chromium...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            print("[INFO] Acessando Viper...")
            page.goto("https://sistemas.vipersolucoes.com.br/", timeout=30000)

            print("[INFO] Preenchendo credenciais...")
            try:
                # Aguardar campos de login aparecerem
                page.wait_for_selector('#name', timeout=10000)
                page.fill('#name', VIPER_USER)
                page.fill('#password', VIPER_PASS)
                
                print("[INFO] Clicando em Entrar...")
                page.click('button[type="submit"], button:has-text("Entrar"), button:has-text("Login")')
                
            except Exception as e:
                print(f"[ERRO] Falha ao preencher login: {e}")
                # Salvar screenshot para debug
                screenshot_path = BASE_DIR / "erro_auth_login.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[INFO] Screenshot salvo em: {screenshot_path}")
                return False

            print("[INFO] Aguardando autenticação...")
            try:
                # Aguardar qualquer redirecionamento após login
                # Pode ser /dashboard, /escolha-sistema, ou outro
                page.wait_for_function(
                    """() => {
                        const url = window.location.href;
                        return !url.includes('/login') && !url.includes('/acesso');
                    }""",
                    timeout=20000
                )
                print(f"[INFO] Login detectado - URL: {page.url}")
            except Exception:
                print("[AVISO] URL não mudou, tentando capturar tokens mesmo assim...")

            # Aguardar um pouco para garantir que o token foi armazenado
            time.sleep(2)

            # Tentar pegar o token de vários lugares possíveis
            token = page.evaluate("""() => {
                return localStorage.getItem('token') || 
                       localStorage.getItem('access_token') || 
                       sessionStorage.getItem('token') ||
                       localStorage.getItem('authToken');
            }""")
            
            # Pegar os cookies
            cookies = context.cookies()
            cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

            if token:
                print(f"[INFO] Token capturado: {token[:20]}...")
                
                # Limpar o token se vier com 'Bearer ' duplicado
                clean_token = token.replace('Bearer ', '')
                
                data = {
                    "Authorization": f"Bearer {clean_token}",
                    "Cookie": cookie_string,
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "captured_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                if save_tokens_atomic(data):
                    print(f"[SUCESSO] Tokens salvos em {TOKENS_FILE}")
                    return True
                else:
                    print("[ERRO] Falha ao salvar tokens no arquivo")
                    return False
            else:
                print("[ERRO] Não foi possível capturar o token do LocalStorage/SessionStorage")
                # Salvar screenshot para debug
                screenshot_path = BASE_DIR / "erro_auth_token.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[INFO] Screenshot salvo em: {screenshot_path}")
                return False

    except Exception as e:
        print(f"[ERRO] Exceção durante autenticação: {e}")
        return False
        
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass


def main():
    """
    Função principal com código de saída apropriado.
    """
    success = refresh_viper_tokens()
    
    if success:
        print("[INFO] Autenticação concluída com sucesso")
        sys.exit(0)  # Sucesso
    else:
        print("[ERRO] Autenticação falhou")
        sys.exit(1)  # Falha


if __name__ == "__main__":
    main()
