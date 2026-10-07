import os
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread
import google.generativeai as genai

# Flask Web Server (UptimeRobot & Render Sağlık Kontrolü)
app = Flask(__name__)

@app.route('/')
def home():
    return "Sandefjord AI Search Assistant is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# API Anahtarları
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHAT_ID = os.environ.get("CHAT_ID")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram mesaj gönderme hatası: {e}")

def parse_request_with_gemini(user_message):
    prompt = f"""
    Aşağıdaki kullanıcı isteğini Finn.no arama parametrelerine dönüştür:
    İstek: "{user_message}"
    
    Çıktı sadece şu formatta olsun (aralarında virgül olsun, ekstra açıklama yazma):
    Arama_Kelimesi, Maksimum_Fiyat
    Örnek: sykkel, 1000
    Eğer fiyat yoksa Maksimum_Fiyat yerine None yaz.
    """
    try:
        response = model.generate_content(prompt)
        parts = response.text.strip().split(',')
        query = parts[0].strip()
        max_price = parts[1].strip() if len(parts) > 1 and parts[1].strip() != 'None' else None
        return query, max_price
    except Exception as e:
        print(f"Gemini hatası: {e}")
        return user_message, None

def search_finn(query, max_price):
    # Sandefjord konumu: 1.20001.20011
    url = f"https://www.finn.no/bap/forsale/search.html?location=1.20001.20011&q={query}"
    if max_price:
        url += f"&price_to={max_price}"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    articles = soup.find_all('article', limit=5)
    results = []

    for art in articles:
        title_elem = art.find('a', class_='sf-search-ad-link')
        price_elem = art.find('div', class_='aria-text') or art.find('span', class_='text-caption')
        
        if title_elem:
            title = title_elem.text.strip()
            link = title_elem.get('href', '')
            if not link.startswith('http'):
                link = f"https://www.finn.no{link}"
            price = price_elem.text.strip() if price_elem else "Fiyat Belirtilmemiş"
            results.append((title, price, link))
            
    return results

def process_telegram_updates():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            res = requests.get(url).json()
            if res.get("ok") and res.get("result"):
                for update in res["result"]:
                    last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "")
                    from_id = str(message.get("chat", {}).get("id", ""))

                    if text and from_id == str(CHAT_ID):
                        if text == "/start":
                            send_telegram_message(from_id, "🤖 **Sandefjord AI Arama Asistanı Aktif!**\n\nBana ne aramak istediğinizi yazın (Örn: '1000 NOK altı bisiklet' veya 'Lego setleri').")
                            continue
                        
                        send_telegram_message(from_id, f"🔍 **'{text}'** için Finn.no taranıyor...")
                        query, max_price = parse_request_with_gemini(text)
                        items = search_finn(query, max_price)

                        if items:
                            msg = f"<b>Found Results for '{query}':</b>\n\n"
                            for title, price, link in items:
                                msg += f"• <b>{title}</b>\n💰 {price}\n🔗 <a href='{link}'>İlanı Aç</a>\n\n"
                            send_telegram_message(from_id, msg)
                        else:
                            send_telegram_message(from_id, "❌ Maalesef uygun kriterde ilan bulunamadı.")
        except Exception as e:
            print(f"Polling hatası: {e}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    process_telegram_updates()
