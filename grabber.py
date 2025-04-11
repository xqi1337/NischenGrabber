import json
import sys
import colorama
import os
import time
import re
import random
import requests
import piexif
import concurrent.futures
from itertools import repeat
from PIL import Image, ImageEnhance, UnidentifiedImageError
from io import BytesIO
from selectolax.parser import HTMLParser
from tqdm import tqdm
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc


# GLOBAL FUNCTIONS
def loadconfig(configpath):
    try:
        with open(configpath, "r") as configfile:
            config = json.load(configfile)
            return config
    except FileNotFoundError:
        print("ERROR: Config not found")
        return False
    except json.JSONDecodeError:
        print("ERROR: Config corrupted")
        return False


def loadblacklist():
    try:
        with open("blacklist.txt", "r") as blacklistfile:
            bl = blacklistfile.read().splitlines()
    except FileNotFoundError:
        return []
    return bl


def createinseratfolder(path):
    inseratepath = "inserate/" + path
    if not os.path.exists(inseratepath):
        os.makedirs(inseratepath + "/Pics")
    return inseratepath


def editimage(image, mirrorimage, changebrightness, clearexif, brightnessrate, file_path):
    exif_bytes = None
    if changebrightness:
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(brightnessrate)
    if mirrorimage:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    if clearexif:
        exif_dict = {"0th": {}, "Exif": {}}
        exif_dict["0th"][piexif.ImageIFD.Model] = "iPhone 14 Pro"
        now = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["0th"][piexif.ImageIFD.DateTime] = now
        exif_dict["Exif"][piexif.ExifIFD.FNumber] = (178, 100)
        exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, 125)
        exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = 100
        exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (686, 100)
        exif_bytes = piexif.dump(exif_dict)
        data = list(image.getdata())
        image_without_exif = Image.new(image.mode, image.size)
        image_without_exif.putdata(data)
        image = image_without_exif
    image.save(file_path, "jpeg", exif=exif_bytes if exif_bytes else image.info.get('exif'))


def download_image(url, file_path, config):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        editimage(
            image,
            config['MISC']['IMAGES']['mirrorimages'],
            config['MISC']['IMAGES']['changebrightness'],
            config['MISC']['IMAGES']['clearexif'],
            config['MISC']['IMAGES']['brightnessrate'],
            file_path
        )
    except (requests.RequestException, UnidentifiedImageError, OSError) as e:
        print(f"Fehler beim Herunterladen des Bildes: {e}")


# TERMINAL UI
class UI:
    def __init__(self):
        self.banner = r'''
                                       ______
                    |\_______________ (_____\\______________
            HH======#H###############H#######################    NISCHENGRABBER 
                    ' ~""""""""""""""`##(_))#H\"""""Y########      xqi
                                      ))    \#H\       `"Y### 
                                      "      }#H)
        '''
        self.clear = lambda: os.system("cls") if sys.platform == "win32" else os.system("clear")
        self.title = lambda title: os.system("title " + title) if sys.platform == "win32" else None
        self.colors = {
            "reset": colorama.Fore.RESET,
            "main": colorama.Fore.LIGHTCYAN_EX,
            "maindark": colorama.Fore.CYAN,
            "accent": colorama.Fore.LIGHTMAGENTA_EX
        }
        self.cinput = lambda text: input(
            f"[{self.colors['accent']}${self.colors['reset']}] {self.colors['maindark']}{text}{self.colors['reset']} > ")
        self.success = lambda text: print(
            f"[{colorama.Fore.LIGHTGREEN_EX}+{self.colors['reset']}] " + colorama.Fore.LIGHTGREEN_EX + text)
        self.error = lambda text: print(
            f"[{colorama.Fore.LIGHTRED_EX}!{self.colors['reset']}] " + colorama.Fore.LIGHTRED_EX + text)
        self.status = lambda text: print(
            f"[{colorama.Fore.LIGHTYELLOW_EX}i{self.colors['reset']}] " + colorama.Fore.LIGHTYELLOW_EX + text)
        self.menupoint = lambda id, text: print(
            f" {self.colors['accent']}{id}{self.colors['reset']} > " + self.colors['main'] + text)

    def printbanner(self):
        self.clear()
        print(self.colors["main"] + self.banner)


# KLAZ GRABBER
class KlazGrabber:
    def __init__(self, config, ui):
        self.session = requests.session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        })
        self.config = config
        self.ui = ui
        self.driver = None
        self.init_webdriver()

        if self.config['INSERAT']['blacklist']:
            self.blacklist = loadblacklist()
            if self.blacklist:
                self.ui.success(f"Loaded Blacklist with {len(self.blacklist)} Keywords")
                time.sleep(1)
        else:
            self.blacklist = []

    def init_webdriver(self):
        options = uc.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--disable-blink-features=AutomationControlled')
        self.driver = uc.Chrome(options=options)
        self.driver.implicitly_wait(10)

    def close_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                # Fehler beim Schließen explizit abfangen und unterdrücken
                print("Fehler beim Schließen des Drivers:", e)
            finally:
                self.driver = None

    def harvestcategories(self):
        categories = []
        try:
            self.driver.get("https://www.kleinanzeigen.de/s-kategorien.html")
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".treelist-headline"))
            )

            parser = HTMLParser(self.driver.page_source)
            tags = parser.css(".treelist-headline a")

            for tag in tags:
                href = tag.attrs.get('href', '')
                if '/s-' in href:
                    category_id = href.split('/')[-1]
                    categories.append((
                        tag.text().strip().replace(" ", ""),
                        href,
                        category_id
                    ))
            return categories
        except Exception as e:
            self.ui.error(f"Kategorien konnte nicht geladen werden: {str(e)[:70]}")
            return []

    def harvestsubcategories(self, categoryname, categoryurl, categoryid):
        categories = [(categoryname, categoryurl, categoryid)]

        try:
            full_url = f"https://www.kleinanzeigen.de{categoryurl}"
            self.ui.status(f"Fetching from: {full_url}")

            self.driver.get(full_url)

            if "cf-chl-bypass" in self.driver.current_url or "sorry" in self.driver.current_url:
                self.ui.error("Cloudflare-Blockierung erkannt! Manuelle Lösung benötigt.")
                input("Drücken Sie ENTER nachdem Sie das CAPTCHA gelöst haben...")
                self.driver.refresh()

            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".browsebox-sorting"))
            )

            parser = HTMLParser(self.driver.page_source)
            subcat_links = parser.css('.browsebox-sorting a.text-link-subdued')

            for link in subcat_links:
                raw_href = link.attrs.get('href', '')
                link_text = link.text(strip=True).replace(" ", "")

                if raw_href.startswith('/s-'):
                    cat_id = raw_href.split('/')[-1]
                    categories.append((
                        link_text,
                        raw_href,
                        cat_id
                    ))
            return categories

        except Exception as e:
            self.ui.error(f"Critical error: {str(e)[:70]}")
            return categories

    def grabad(self, adlink, catname):
        try:
            req = self.session.get(adlink, timeout=10)
            req.raise_for_status()
            parser = HTMLParser(req.text)

            title_element = parser.css_first('#viewad-title')
            if not title_element:
                return
            title = title_element.text().replace("/", "+").replace("\\", "+").strip()

            if self.blacklist and any(blkey.lower() in title.lower() for blkey in self.blacklist):
                return

            price_element = parser.css_first('#viewad-price')
            price_text = price_element.text() if price_element else ""
            price = int(re.sub(r"\D", "", price_text)) if price_text else 0
            newprice = round(price * self.config["INSERAT"]["pricereduction"])

            description_element = parser.css_first('#viewad-description-text')
            description = description_element.text().lstrip() if description_element else ""

            addate_element = parser.css_first('#viewad-extra-info > div:nth-child(1) > span:nth-child(2)')
            addate = addate_element.text().strip() if addate_element else ""

            grabdate = datetime.now()

            adid_element = parser.css_first('.text-light-800 > li:nth-child(2)')
            if not adid_element:
                return
            adid = adid_element.text().strip()

            req = self.session.get(f"https://www.kleinanzeigen.de/s-vac-inc-get.json?adId={adid}", timeout=10)
            views = req.json().get("numVisits", 0) if req.status_code == 200 else 0

            if views >= self.config['INSERAT']['minviews']:
                path = f"Kleinanzeigen/{catname.replace('/', '')}/{price}€ {title}"
                path = createinseratfolder(path)

                if path:
                    images = parser.css('#viewad-image')
                    for image in images:
                        imageurl = image.attributes.get('src', '')
                        if imageurl:
                            download_image(
                                imageurl,
                                os.path.join(path, "Pics", f"pic{images.index(image)}.jpg"),
                                self.config
                            )

                    with open(os.path.join(path, "text.txt"), "w", encoding='utf-8') as textfile:
                        textfile.write(f"URL: {adlink}\nID: {adid}\nVIEWS: {views}\nCATEGORY: {catname}\n"
                                       f"TITLE: {title}\nPRICE: {newprice}€\nADDATE: {addate}\n"
                                       f"GRABDATE: {grabdate}\nDESCRIPTION: {description}")

        except Exception as e:
            # Fehler beim Greifen einer Anzeige unterdrücken
            pass

    def harvestads(self, category, categoryid, categoryname):
        self.ui.printbanner()
        links = set()

        for pageindex in tqdm(range(1, 51),
                              desc=f"{self.ui.colors['main']}Collecting Links",
                              unit="pages",
                              colour="CYAN"):
            try:
                url = f"https://www.kleinanzeigen.de{category}/preis:{self.config['INSERAT']['minprice']}:" \
                      f"{self.config['INSERAT']['maxprice']}/seite:{pageindex}"
                self.driver.get(url)

                if "captcha" in self.driver.page_source.lower():
                    self.ui.error("CAPTCHA detected! Manual solution required.")
                    input("Press ENTER after you have solved the CAPTCHA...")
                    self.driver.get(url)

                parser = HTMLParser(self.driver.page_source)
                adlinktags = parser.css('.aditem a')
                links.update(set(["https://www.kleinanzeigen.de" + adlinktag.attributes.get('href', '')
                                    for adlinktag in adlinktags if adlinktag.attributes.get('href')]))

            except Exception as e:
                self.ui.error(f"Error on page {pageindex}: {str(e)}")
                continue

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.config['MISC']['GRABBER']['maxthreads']) as executor:
            list(tqdm(executor.map(self.grabad, links, repeat(categoryname)),
                      unit="ads",
                      desc=f"{self.ui.colors['main']}Grabbing Ads",
                      colour="CYAN",
                      total=len(links)))

    def klaz_slct_cat(self, categories):
        self.ui.printbanner()
        print("")
        self.ui.status("Select Category")
        print("")
        id = 0
        for cat in categories:
            index = categories.index(cat)
            if index < 10:
                self.ui.menupoint(id=f"{index} ", text=cat[0])
            else:
                self.ui.menupoint(id=f"{index}", text=cat[0])
        self.ui.menupoint(id="C ", text="Custom Category")

        try:
            command = self.ui.cinput("Select Category: ").lower()

            if command != "c":
                command = int(command)
                cat = categories[command]
            else:
                catname = self.ui.cinput("Category name (Will be the folder in which the ads are saved)")
                caturl = self.ui.cinput("Category rawurl (Example: '/s-audio-hifi')")
                catid = self.ui.cinput("Category ID / Found in Url at the end (Example: 'c172')")
                return (catname, caturl, catid)
        except (ValueError, IndexError):
            self.ui.error("Not a valid Category")
            time.sleep(2)
            return
        return cat

    def __del__(self):
        # Falls close_driver() nicht explizit aufgerufen wurde, versuchen wir hier den Driver zu schließen
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass


# MAIN FUNCTION
def main():
    colorama.init(autoreset=True)
    ui = UI()
    ui.printbanner()

    configpath = ui.cinput(text="Config Path (ENTER = Default)")
    configpath = "config.json" if not configpath else configpath

    config = loadconfig(configpath)
    if not config:
        ui.error("Failed to load config. Exiting.")
        time.sleep(2)
        return

    ui.success(f"Config ({configpath}) loaded successfully")
    time.sleep(random.randint(1, 3))

    while True:
        ui.printbanner()
        print("")
        ui.status("Mainmenu | Select Option")
        print("")
        ui.menupoint("X", "Exit Grabber")
        ui.menupoint("K", "Kleinanzeigen.de")
        ui.menupoint("W", "Willhaben.at")
        print("")

        command = ui.cinput("Select Module").lower()

        if command == "x":
            # Vor dem Exit den Driver aller Instanzen sauber schließen
            sys.exit()
        elif command == "k":
            grabber = KlazGrabber(config, ui)
            cats = grabber.harvestcategories()
            if not cats:
                ui.error("Keine Kategorien gefunden")
                time.sleep(2)
                grabber.close_driver()
                continue

            cat = grabber.klaz_slct_cat(cats)
            if cat:
                subcats = grabber.harvestsubcategories(*cat)
                if subcats:
                    selected_cat = grabber.klaz_slct_cat(subcats)
                    if selected_cat:
                        grabber.harvestads(selected_cat[1], selected_cat[2], selected_cat[0])
            grabber.close_driver()
        elif command == "w":
            # Placeholder für Willhaben.at
            ui.error("Modul Willhaben.at ist noch nicht implementiert.")
            time.sleep(2)
        else:
            ui.error("Invalid option")
            time.sleep(1)


if __name__ == "__main__":
    main()
