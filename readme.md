
# NischenGrabber

🕵️‍♂️ **NischenGrabber** ist ein automatisierter Crawler für Kleinanzeigen.de, der gezielt Anzeigen nach Preis, Kategorie, und Beliebtheit filtert, Bilder optional modifiziert und Daten strukturiert speichert.

---

## 🔧 Features

- ⚙️ Konfigurierbares Crawling über `config.json`
- 📦 Multithreaded Anzeige-Download für maximale Geschwindigkeit
- 🔎 Preisfilter, View-Filter und Blacklist-Support
- ✍️ (Optional) GPT-gestütztes Rewriting von Anzeigentexten
- 🖼️ Bildverarbeitung:
  - Helligkeit anpassen
  - Spiegelung (optional)
  - EXIF-Daten löschen oder ersetzen

---

## 📂 Projektstruktur

```
├── blacklist.txt
├── config.json
├── main.py
├── inserate/
│   └── Kategorie/
│       ├── text.txt
│       └── Pics/
│           ├── pic0.jpg
│           └── ...
```

---

## ⚙️ Konfiguration (`config.json`)

```json
{
  "MISC": {
    "IMAGES": {
      "mirrorimages": false,
      "changebrightness": true,
      "brightnessrate": 0.9,
      "clearexif": true
    },
    "GRABBER": {
      "maxthreads": 20,
      "maxadspercat": 180
    }
  },
  "INSERAT": {
    "minprice": 100,
    "maxprice": 1000,
    "pricereduction": 0.9,
    "minviews": 50,
    "blacklist": true,
    "gptrewrite": false,
    "gptprompt": "Kannst du mir bitte den folgenden Text umschreiben in sachlichen Deutsch ..."
  },
  "chrome_binary": "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "DEBUG_MODE": false
}
```

---

## 🧪 Voraussetzungen

- Python 3.10+
- Google Chrome + [Undetected-Chromedriver](https://pypi.org/project/undetected-chromedriver/)
- Weitere Pakete (installierbar via pip):
  ```
  pip install -r requirements.txt
  ```

**Beispiel für `requirements.txt`:**
```
requests
undetected-chromedriver
pillow
tqdm
colorama
piexif
selectolax
```

---

## 🚀 Start

```bash
python main.py
```

Folge den Anweisungen im Terminal zur Auswahl von Kategorien und Subkategorien.

---

## ✅ ToDo

- [ ] Willhaben.at Modul implementieren
- [ ] Webinterface für Steuerung und Anzeige
- [ ] GPT-Unterstützung optimieren

---

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz veröffentlicht.

---

## 👤 Autor

xqi – [github.com/xqi1337](https://github.com/xqi1337)
