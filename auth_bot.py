import json
import time
from playwright.sync_api import sync_playwright
from decouple import config

# Carrega credenciais do .env
VIPER_USER = config('VIPER_USER', default='')
VIPER_PASS = config('VIPER_PASS', default='')

def refresh_viper_tokens():
    print("🤖 Iniciando robô de autenticação...")
    
    if not VIPER_USER or not VIPER_PASS:
        print("❌ Erro: VIPER_USER ou VIPER_PASS não configurados no .env")
        return

    with sync_playwright() as p:
        # headless=False para você ver ele trabalhando na primeira vez
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context()
        page = context.new_page()

        print("🌍 Acessando Viper...")
        page.goto("https://sistemas.vipersolucoes.com.br/")

        # SELETORES CORRIGIDOS AQUI:
        print("✍️  Preenchendo credenciais...")
        try:
            page.fill('#name', VIPER_USER)      # Corrigido: id="name"
            page.fill('#password', VIPER_PASS)  # Corrigido: id="password"
            
            # Clica no botão de entrar (procura por texto ou tipo submit)
            print("🔑 Clicando em Entrar...")
            page.click('button[type="submit"], button:has-text("Entrar"), button:has-text("Login")')
        except Exception as e:
            print(f"❌ Erro ao preencher login: {e}")
            browser.close()
            return

        # Espera o login acontecer (aguarda a URL mudar ou o token aparecer)
        print("⏳ Aguardando autenticação...")
        try:
            # Espera até 15s para a URL sair da página de login
            page.wait_for_url("**/dashboard**", timeout=15000) 
            print("✅ Login detectado!")
        except:
            print("⚠️ URL não mudou para dashboard, tentando capturar tokens mesmo assim...")

        # Tenta pegar o token de vários lugares possíveis
        token = page.evaluate("() => localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token')")
        
        # Pega os cookies
        cookies = context.cookies()
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        if token:
            print(f"🎉 SUCESSO! Token Capturado: {token[:15]}...")
            
            # Limpa o token se vier com 'Bearer ' duplicado
            clean_token = token.replace('Bearer ', '')
            
            data = {
                "Authorization": f"Bearer {clean_token}",
                "Cookie": cookie_string,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            with open("viper_tokens.json", "w") as f:
                json.dump(data, f)
            
            print("💾 Tokens salvos em viper_tokens.json")
        else:
            print("❌ Falha: Não encontrei o token no LocalStorage/SessionStorage.")
            # Tira print para debug
            page.screenshot(path="erro_auth.png")

        time.sleep(2) # Dá um tempinho pra fechar bonito
        browser.close()

if __name__ == "__main__":
    refresh_viper_tokens()