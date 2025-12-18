from playwright.sync_api import sync_playwright
import time

def inspect_page():
    print("🕵️‍♂️ Iniciando modo detetive...")
    
    with sync_playwright() as p:
        # headless=False para VOCÊ ver o navegador abrindo
        browser = p.chromium.launch(headless=False) 
        page = browser.new_page()

        print("🌍 Acessando página de login...")
        page.goto("https://sistemas.vipersolucoes.com.br/")
        
        # Espera 5 segundos para garantir que tudo carregou
        print("⏳ Aguardando carregamento (5s)...")
        time.sleep(5)
        
        print("\n" + "="*40)
        print("🔍 LISTA DE INPUTS ENCONTRADOS:")
        print("="*40)
        
        # Busca todos os campos de input na página
        inputs = page.locator("input").all()
        
        if not inputs:
            print("❌ Nenhum input encontrado! A página pode estar num iframe ou shadow DOM.")
        
        for i in inputs:
            try:
                # Imprime o HTML exato do campo (ex: <input name="usuario" ...>)
                html = i.evaluate("el => el.outerHTML")
                print(f"👉 {html}")
            except:
                pass
                
        print("\n" + "="*40)
        print("👀 Olhe o navegador aberto. A página carregou?")
        print("Se não carregou, pode ter Cloudflare ou bloqueio.")
        print("="*40)
        
        # Segura a tela aberta por 30 segundos pra você olhar
        time.sleep(30)
        browser.close()

if __name__ == "__main__":
    inspect_page()