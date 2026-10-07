import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread
import google.generativeai as genai

app = Flask(__name__)

@app.route('/')
def home():
    return "Sandefjord AI Search Assistant is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CHAT_ID = os.environ.get("CHAT_ID")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Türkçe -> Norveççe Temel Sözlük & Kurallar
DICTIONARY = {
    "bisiklet": "sykkel",
    "saat": "klokke",
    "antika": "antikk",
    "lego": "lego",
    "araba": "bil",
    "koltuk": "sofa",
    "masası": "bord",
    "masa": "bord",
    "sandalye": "stol",
    "telefon": "telefon",
    "bilgisayar": "datamaskin",
    "televizyon": "tv"
}

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram gönderme hatası: {e}")

def parse_request_smart(user_message):
    # 1. Fiyat Limitini Ayıkla (Örn: 1000 NOK, 1000kr, 1000 altı vb.)
    max_price = None
    price_match = re.search(r'(\d+)\s*(nok|kr|altı|alti)?', user_message.lower())
    if price_match:
        found_num = price_match.group(1)
        # Eğer bulunan sayı yıl veya konum kodu değilse fiyat kabul et
        if int(found_num) < 100000:
            max_price = found_num

    # 2. Gemini API ile Cümleyi Ayrıştırmayı Dene
    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            prompt = f"Extract search term in Norwegian and max price from: '{user_message}'. Format: query, price"
            response = model.generate_content(prompt)
            text = response.text.strip()
            parts = text.split(',')
            query = parts[0].strip()
            if len(parts) > 1 and parts[1].strip().isdigit():
                max_price = parts[1].strip()
            return query, max_price
        except Exception as e:
            print(f"Gemini API Pasif/Hatalı, Sözlük Modu Devrede: {e}")

    # 3. Yedek (Sözlük & Kural) Modu
    words = user_message.lower().split()
    translated_words = []
    
    for word in words:
        # Fiyat, gereksiz Türkçe kelimeleri temizle
        if word.isdigit() or word in ["bana", "sandefjord'da", "sandefjord", "ta", "de", "da", "altı", "alti", "nok", "kr", "bul", "ara", "için", "icin"]:
            continue
        norwegian_word = DICTIONARY.get(word, word)
        translated_words.append(norwegian_word)

    query = " ".join(translated_words) if translated_words else "sykkel"
    return query, max_price

def search_finn(query, max_price):
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
            link_elem = art.find('a', class_='sf-search-ad-link') or art.find('a', href=True)
            if not link_elem:
                continue
                
            title = link_elem.text.strip()
            link = link_elem.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.finn.no{link}"

            price_elem = art.find('div', class_='aria-text') or art.find('span', class_='text-caption')
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
                            send_telegram_message(from_id, "🤖 <b>Sandefjord Arama Asistanı Aktif!</b>\n\nİstediğiniz ürünü yazın (Örn: '1000 NOK altı bisiklet' veya 'antika saat').")
                            continue
                        
                        query, max_price = parse_request_smart(text)
                        
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
