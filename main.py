import os
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread
import google.generativeai as genai

# Flask Web Server (Render & UptimeRobot)
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

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram mesaj gönderme hatası: {e}")

def parse_request_with_gemini(user_message):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Kullanıcının Türkçe cümlesinden Finn.no için Norveççe veya İngilizce arama kelimesini (search_query) ve varsa fiyat limitini (max_price) çıkar.
        Kullanıcı Cümlesi: "{user_message}"

        ÇIKTI FORMATI: Sadece "kelime, fiyat" şeklinde yaz. Ekstra hiçbir metin veya açıklama yazma.
        Örnek 1: bisiklet -> sykkel, None
        Örnek 2: 1000 NOK altı bisiklet -> sykkel, 1000
        Örnek 3: antika saat -> antikk klokke, None
        Örnek 4: lego -> lego, None
        """
        response = model.generate_content(prompt)
        text = response.text.strip()
        parts = text.split(',')
        
        query = parts[0].strip()
        max_price = None
        if len(parts) > 1 and parts[1].strip().lower() != 'none':
            max_price = parts[1].strip()
            
        return query, max_price
    except Exception as e:
        print(f"Gemini Hatası: {e}")
        # Hata durumunda cümleden bilinen basit kelimeleri temizle
        clean_text = user_message.lower().replace("bana", "").replace("sandefjord ta", "").replace("sandefjord'da", "").replace("bul", "").replace("ara", "").strip()
        return clean_text, None

def search_finn(query, max_price):
    # Sandefjord konumu: 1.20001.20011
    url = f"https://www.finn.no/bap/forsale/search.html?location=1.20001.20011&q={query}"
    if max_price:
        url += f"&price_to={max_price}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article', limit=5)
        results = []

        for art in articles:
            # İlan başlığı ve linki
            link_elem = art.find('a', class_='sf-search-ad-link') or art.find('a', href=True)
            if not link_elem:
                continue
                
            title = link_elem.text.strip()
            link = link_elem.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.finn.no{link}"

            # Fiyat
            price_elem = art.find('div', class_='aria-text') or art.find('span', class_='text-caption') or art.find('div', text=lambda t: t and 'kr' in t)
            price = price_elem.text.strip() if price_elem else "Fiyat Belirtilmemiş"

            if title and link:
                results.append((title, price, link))
                
        return results
    except Exception as e:
        print(f"Finn arama hatası: {e}")
        return []

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
                            send_telegram_message(from_id, "🤖 <b>Sandefjord AI Arama Asistanı Aktif!</b>\n\nBana ne aramak istediğinizi yazın (Örn: '1000 NOK altı bisiklet' veya 'antika saat').")
                            continue
                        
                        query, max_price = parse_request_with_gemini(text)
                        
                        status_msg = f"🔍 <b>Arama Kelimesi:</b> '{query}'"
                        if max_price:
                            status_msg += f"\n💰 <b>Maks Fiyat:</b> {max_price} NOK"
                        status_msg += "\n\nFinn.no taranıyor..."
                        
                        send_telegram_message(from_id, status_msg)
                        
                        items = search_finn(query, max_price)

                        if items:
                            msg = f"<b>Sandefjord Sonuçları ('{query}'):</b>\n\n"
                            for title, price, plink in items:
                                msg += f"• <b>{title}</b>\n💰 {price}\n🔗 <a href='{plink}'>İlanı Gör</a>\n\n"
                            send_telegram_message(from_id, msg)
                        else:
                            msg = f"❌ Sandefjord bölgesinde <b>'{query}'</b> için uygun ilan bulunamadı."
                            if max_price:
                                msg += f" (Fiyat limiti: {max_price} NOK)"
                            send_telegram_message(from_id, msg)
        except Exception as e:
            print(f"Polling hatası: {e}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    process_telegram_updates()
