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
import logging
from itertools import repeat
from PIL import Image, ImageEnhance, UnidentifiedImageError
from io import BytesIO
from selectolax.parser import HTMLParser
from tqdm import tqdm
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import undetected_chromedriver as uc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


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
    base_dir = os.path.join("inserate", "Kleinanzeigen")
    full_path = os.path.join(base_dir, path)
    try:
        os.makedirs(os.path.join(full_path, "Pics"), exist_ok=True)
        return full_path
    except Exception as e:
        logger.error(f"Ordnerfehler: {e}")
        return None


def editimage(image, mirrorimage, changebrightness, clearexif, brightnessrate, file_path):
    exif_bytes = None
    try:
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

        # Ensure the directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        image.save(file_path, "jpeg", exif=exif_bytes if exif_bytes else image.info.get('exif'))
        return True
    except Exception as e:
        logger.error(f"Error editing image: {e}")
        return False


def download_image(url, file_path, config):
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        return editimage(
            image,
            config['MISC']['IMAGES']['mirrorimages'],
            config['MISC']['IMAGES']['changebrightness'],
            config['MISC']['IMAGES']['clearexif'],
            config['MISC']['IMAGES']['brightnessrate'],
            file_path
        )
    except (requests.RequestException, UnidentifiedImageError, OSError) as e:
        logger.error(f"Error downloading image {url}: {e}")
        return False


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
        self.session = self._create_session()
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

        # Create base directories if they don't exist
        os.makedirs("inserate/Kleinanzeigen", exist_ok=True)
        os.makedirs("inserate/links", exist_ok=True)

    def _create_session(self):
        # Create session with retry mechanism
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )

        # Increase pool_connections and pool_maxsize
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=20
        )

        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Set headers to mimic a real browser
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        })

        return session

    def init_webdriver(self):
        try:
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')

            # Add more realistic browser fingerprint
            options.add_argument(
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36')

            # Close any existing driver
            self.close_driver()

            # Initialize new driver
            self.driver = uc.Chrome(options=options)
            self.driver.implicitly_wait(15)
        except Exception as e:
            logger.error(f"Error initializing webdriver: {e}")
            # Retry initialization once
            try:
                if self.driver:
                    self.driver.quit()
                time.sleep(2)
                self.driver = uc.Chrome(options=options)
                self.driver.implicitly_wait(15)
            except Exception as e2:
                logger.error(f"Failed to initialize webdriver on retry: {e2}")
                sys.exit(1)

    def close_driver(self):
        if self.driver:
            try:
                # Verbesserte Bereinigung
                self.driver.service.process.kill()
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                self.driver = None

    def harvestcategories(self):
        categories = []
        try:
            # Set cookies to avoid detection
            self.driver.get("https://www.kleinanzeigen.de")
            time.sleep(2)

            # Now get categories
            self.driver.get("https://www.kleinanzeigen.de/s-kategorien.html")

            # Wait for page to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".treelist-headline"))
            )

            # Handle potential CAPTCHA/Cloudflare
            if "captcha" in self.driver.page_source.lower() or "cloudflare" in self.driver.page_source.lower():
                self.ui.error("CAPTCHA/Cloudflare detected! Manual solution required.")
                input("Press ENTER after you have solved the CAPTCHA...")
                self.driver.refresh()
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
            self.ui.error(f"Categories could not be loaded: {str(e)[:70]}")
            return []

    def harvestsubcategories(self, categoryname, categoryurl, categoryid):
        categories = [(categoryname, categoryurl, categoryid)]

        try:
            full_url = f"https://www.kleinanzeigen.de{categoryurl}"
            self.ui.status(f"Fetching from: {full_url}")

            # Reset driver to avoid stale connection
            self.init_webdriver()

            self.driver.get(full_url)
            time.sleep(3)  # Add a longer delay

            # Check for Cloudflare/CAPTCHA
            if "cf-chl-bypass" in self.driver.current_url or "sorry" in self.driver.current_url or "captcha" in self.driver.page_source.lower():
                self.ui.error("Cloudflare/CAPTCHA detected! Manual solution required.")
                input("Press ENTER after you have solved the challenge...")
                self.driver.refresh()
                time.sleep(3)

            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".browsebox-sorting"))
                )
            except Exception:
                self.ui.error("Could not find subcategories on the page")
                # Return the main category if no subcategories found
                return categories

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

    def process_ad(self, ad_info):
        """Process a single ad from saved JSON data and return ad data if successful"""
        try:
            adlink = ad_info["url"]
            catname = ad_info["category"]

            session = self._create_session()
            time.sleep(random.uniform(0.1, 0.5))
            req = session.get(adlink, timeout=15)
            req.raise_for_status()
            parser = HTMLParser(req.text)

            if "captcha" in req.text.lower() or "cloudflare" in req.text.lower() or "403 Forbidden" in req.text:
                logger.warning(f"Access denied for ad: {adlink}")
                return None

            title_element = parser.css_first('#viewad-title')
            if not title_element:
                return None
            title = title_element.text().replace("/", "+").replace("\\", "+").strip()

            if self.blacklist and any(blkey.lower() in title.lower() for blkey in self.blacklist):
                return None

            price_element = parser.css_first('#viewad-price')
            price_text = price_element.text() if price_element else ""
            price = int(re.sub(r"\D", "", price_text)) if price_text and re.sub(r"\D", "", price_text) else 0
            newprice = round(price * self.config["INSERAT"]["pricereduction"])

            description_element = parser.css_first('#viewad-description-text')
            description = description_element.text().lstrip() if description_element else ""

            addate_element = parser.css_first('#viewad-extra-info > div:nth-child(1) > span:nth-child(2)')
            addate = addate_element.text().strip() if addate_element else ""
            grabdate = datetime.now()

            adid_element = parser.css_first('.text-light-800 > li:nth-child(2)') or parser.css_first(
                'li[data-testid="ad-id"]')
            if not adid_element:
                return None
            adid = re.sub(r"\D", "", adid_element.text().strip())

            try:
                views_req = session.get(f"https://www.kleinanzeigen.de/s-vac-inc-get.json?adId={adid}", timeout=10)
                views = views_req.json().get("numVisits", 0) if views_req.status_code == 200 else 0
            except Exception as e:
                logger.warning(f"Failed to get view count: {e}")
                views = 0

            if views >= self.config['INSERAT']['minviews']:
                safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)[:50]
                base_path = f"Kleinanzeigen/{catname.replace('/', '_')}/{price}€ {safe_title}"
                inseratepath = createinseratfolder(base_path)

                if inseratepath:
                    try:
                        images_downloaded = 0
                        image_paths = []
                        try:
                            images = parser.css('img.galleryimage-element') or parser.css('#viewad-image')
                            for i, image in enumerate(images):
                                imageurl = image.attrs.get('src', '')
                                if imageurl.startswith('//'):
                                    imageurl = 'https:' + imageurl
                                elif not imageurl.startswith('http'):
                                    continue

                                success = download_image(
                                    imageurl,
                                    os.path.join(inseratepath, "Pics", f"pic{i}.jpg"),
                                    self.config
                                )
                                if success:
                                    images_downloaded += 1
                                    image_paths.append(f"Pics/pic{i}.jpg")
                                time.sleep(random.uniform(0.2, 0.5))
                        except Exception as e:
                            logger.warning(f"Image download error: {e}")

                        # Erstelle das Ad-Daten-Dictionary
                        ad_data = {
                            "link": adlink,
                            "preis": {
                                "original": price,
                                "berechnet": newprice
                            },
                            "titel": title,
                            "beschreibung": description,
                            "bilder": image_paths,
                            "metadaten": {
                                "kategorie": catname,
                                "erfasst_am": datetime.now().isoformat(),
                                "inserat_id": adid,
                                "aufrufe": views
                            }
                        }

                        # Speichere JSON im Inseratsordner (Einzeldatei)
                        try:
                            json_path = os.path.join(inseratepath, "inserat.json")
                            with open(json_path, 'w', encoding='utf-8') as f:
                                json.dump(ad_data, f, indent=2, ensure_ascii=False)
                            logger.debug(f"JSON gespeichert: {json_path}")
                        except Exception as e:
                            logger.error(f"Fehler beim Speichern einzelner JSON: {e}")
                        # Rückgabe der wesentlichen Inseratsdaten (kann auch metadaten enthalten, falls gewünscht)
                        return ad_data

                    except PermissionError as e:
                        logger.error(f"Ordnerberechtigungsfehler: {e}")
                        return None
                    except OSError as e:
                        logger.error(f"Ordnererstellungsfehler: {e}")
                        return None

            return None

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                logger.warning(f"Rate Limit erreicht für: {adlink}")
            else:
                logger.warning(f"HTTP Fehler {e.response.status_code}: {adlink}")
            return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"Verbindungsfehler: {e}")
            return None

        except Exception as e:
            logger.error(f"Kritischer Verarbeitungsfehler: {str(e)[:100]}")
            return None

    def process_saved_links(self, json_file=None):
        """Process links from a saved JSON file and create a consolidated JSON file in 'inserate/Kleinanzeigen'"""
        self.ui.printbanner()

        if not json_file:
            links_files = [file for file in os.listdir("inserate/links") if file.endswith(".json")]
            if not links_files:
                self.ui.error("Keine gespeicherten Link-Dateien gefunden")
                time.sleep(2)
                return

            self.ui.status("Wähle eine Link-Datei zur Verarbeitung")
            for i, file in enumerate(links_files):
                self.ui.menupoint(f"{i}", file)

            try:
                selection = int(self.ui.cinput("Datei auswählen"))
                json_file = os.path.join("inserate/links", links_files[selection])
            except (ValueError, IndexError):
                self.ui.error("Ungültige Auswahl")
                time.sleep(2)
                return

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                links_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.ui.error(f"Fehler beim Laden der Link-Datei: {e}")
            time.sleep(2)
            return

        unprocessed_links = [link for link in links_data if not link.get("processed", False)]
        if not unprocessed_links:
            self.ui.status("Alle Links in dieser Datei wurden bereits verarbeitet")
            process_again = self.ui.cinput("Alle Links nochmal verarbeiten? (y/n)").lower()
            if process_again == 'y':
                unprocessed_links = links_data
                for link in links_data:
                    link["processed"] = False
            else:
                return

        max_threads = min(self.config['MISC']['GRABBER']['maxthreads'], 20)
        logger.info(f"Verarbeite {len(unprocessed_links)} Inserate mit {max_threads} Threads")

        # Nutze ThreadPoolExecutor und sammle die von process_ad zurückgegebenen Daten
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            ad_results = list(tqdm(executor.map(self.process_ad, unprocessed_links),
                                   unit="ads",
                                   desc=f"{self.ui.colors['main']}Processing Ads",
                                   colour="CYAN",
                                   total=len(unprocessed_links)))

        # Markiere alle Links als verarbeitet
        for link in unprocessed_links:
            link["processed"] = True
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(links_data, f, indent=2)

        # Konsolidiere alle erfolgreichen Ad-Daten in eine Liste (nur wesentliche Infos)
        consolidated_ads = [
            {
                "link": ad["link"],
                "preis": ad["preis"],
                "titel": ad["titel"],
                "beschreibung": ad["beschreibung"],
                "bilder": ad["bilder"]
            }
            for ad in ad_results if ad is not None
        ]

        # Speichern in ein zentrales JSON im Ordner "inserate/Kleinanzeigen"
        if consolidated_ads:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            consolidated_json_path = os.path.join("inserate", "Kleinanzeigen", f"consolidated_{timestamp}.json")
            try:
                with open(consolidated_json_path, 'w', encoding='utf-8') as f:
                    json.dump(consolidated_ads, f, indent=2, ensure_ascii=False)
                self.ui.success(f"JSON-Daten gespeichert in: {consolidated_json_path}")
                logger.info(f"Alle Daten wurden im Kleinanzeigen-Ordner gespeichert")
            except Exception as e:
                self.ui.error(f"Fehler beim Speichern der konsolidierten JSON: {e}")
                logger.error(f"Fehler: {e}")
        else:
            self.ui.status("Keine Inseratsdaten wurden erfolgreich verarbeitet.")
        time.sleep(2)

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
            return None
        return cat

    def __del__(self):
        try:
            self.close_driver()
        except:
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
    time.sleep(random.randint(1, 2))

    config.setdefault('MISC', {})
    config['MISC'].setdefault('GRABBER', {'maxthreads': 10, 'maxpages': 50})
    config['MISC'].setdefault('IMAGES', {
        'mirrorimages': False,
        'changebrightness': False,
        'clearexif': True,
        'brightnessrate': 1.0
    })

    os.makedirs("inserate", exist_ok=True)
    os.makedirs("inserate/links", exist_ok=True)
    os.makedirs("inserate/Kleinanzeigen", exist_ok=True)

    while True:
        ui.printbanner()
        print("")
        ui.status("Main Menu")
        print("")
        ui.menupoint("X", "Exit Grabber")
        ui.menupoint("K", "Kleinanzeigen.de")
        ui.menupoint("L", "Links verarbeiten und JSON erstellen")  # GEÄNDERTE BESCHREIBUNG
        ui.menupoint("W", "Willhaben.at")
        print("")

        command = ui.cinput("Select Module").lower()

        if command == "x":
            # Sauberer Exit
            return
        elif command == "k":
            grabber = None
            try:
                grabber = KlazGrabber(config, ui)
                cats = grabber.harvestcategories()
                if not cats:
                    ui.error("No categories found")
                    time.sleep(2)
                    continue

                cat = grabber.klaz_slct_cat(cats)
                if cat:
                    subcats = grabber.harvestsubcategories(*cat)
                    if subcats:
                        selected_cat = grabber.klaz_slct_cat(subcats)
                        if selected_cat:
                            json_file = grabber.collect_links(selected_cat[1], selected_cat[2], selected_cat[0])
                            if json_file:
                                process_now = ui.cinput("Process the collected links now? (y/n)").lower()
                                if process_now == 'y':
                                    grabber.process_saved_links(json_file)

            except Exception as e:
                logger.error(f"Error in Kleinanzeigen module: {e}", exc_info=True)
                ui.error(f"An error occurred: {str(e)[:70]}")
                time.sleep(2)
            finally:
                if grabber:
                    try:
                        grabber.close_driver()
                    except:
                        pass
        elif command == "l":
            grabber = None
            try:
                grabber = KlazGrabber(config, ui)
                grabber.process_saved_links()
            except Exception as e:
                logger.error(f"Error processing saved links: {e}", exc_info=True)
                ui.error(f"An error occurred: {str(e)[:70]}")
                time.sleep(2)
            finally:
                if grabber:
                    try:
                        grabber.close_driver()
                    except:
                        pass
        elif command == "w":
            ui.error("Module Willhaben.at is not yet implemented.")
            time.sleep(2)
        else:
            ui.error("Invalid option")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        # Make sure all Chrome processes are properly terminated
        try:
            import psutil

            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'chrome' in proc.info['name'].lower():
                    try:
                        proc.terminate()
                    except:
                        pass
        except:
            pass


