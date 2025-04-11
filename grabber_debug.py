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
import traceback
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
import undetected_chromedriver as uc


# Setup Logging
def setup_logging(debug_mode=False):
    log_level = logging.DEBUG if debug_mode else logging.INFO
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, f"grabber_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("grabber")


# GLOBAL FUNCTIONS
def loadconfig(configpath):
    try:
        with open(configpath, "r") as configfile:
            config = json.load(configfile)
            # Check for required fields
            required_fields = ["INSERAT", "MISC"]
            for field in required_fields:
                if field not in config:
                    print(f"ERROR: Config missing required field '{field}'")
                    return False
            return config
    except FileNotFoundError:
        print("ERROR: Config not found")
        return False
    except json.JSONDecodeError:
        print("ERROR: Config corrupted")
        return False


def loadblacklist():
    try:
        with open("blacklist.txt", "r", encoding="utf-8") as blacklistfile:
            bl = blacklistfile.read().splitlines()
            # Remove empty lines and strip whitespace
            bl = [line.strip() for line in bl if line.strip()]
    except FileNotFoundError:
        return []
    return bl


def createinseratfolder(path):
    inseratepath = "inserate/" + path
    try:
        if not os.path.exists(inseratepath):
            os.makedirs(inseratepath + "/Pics")
        return inseratepath
    except Exception as e:
        logger.error(f"Failed to create directory {inseratepath}: {str(e)}")
        return None


def editimage(image, mirrorimage, changebrightness, clearexif, brightnessrate, file_path):
    try:
        exif_bytes = None
        if changebrightness:
            logger.debug(f"Adjusting brightness of image to {brightnessrate}")
            enhancer = ImageEnhance.Brightness(image)
            image = enhancer.enhance(brightnessrate)
        if mirrorimage:
            logger.debug("Mirroring image")
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
        if clearexif:
            logger.debug("Clearing EXIF data and setting custom data")
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
        logger.debug(f"Saving image to {file_path}")
        image.save(file_path, "jpeg", exif=exif_bytes if exif_bytes else image.info.get('exif'))
        return True
    except Exception as e:
        logger.error(f"Error editing image: {str(e)}")
        return False


def download_image(url, file_path, config):
    try:
        logger.debug(f"Downloading image from {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        result = editimage(
            image,
            config['MISC']['IMAGES']['mirrorimages'],
            config['MISC']['IMAGES']['changebrightness'],
            config['MISC']['IMAGES']['clearexif'],
            config['MISC']['IMAGES']['brightnessrate'],
            file_path
        )
        return result
    except (requests.RequestException, UnidentifiedImageError, OSError) as e:
        logger.error(f"Error downloading image: {str(e)}")
        return False


# TERMINAL UI
class UI:
    def __init__(self):
        self.banner = r'''
                                       ______
                    |\_______________ (_____\\______________
            HH======#H###############H#######################    NISCHENGRABBER
                    ' ~""""""""""""""`##(_))#H\"""""Y########       xqo
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
        self.debug = lambda text: print(
            f"[{colorama.Fore.LIGHTBLUE_EX}D{self.colors['reset']}] " + colorama.Fore.LIGHTBLUE_EX + text)
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
        logger.info("Initializing KlazGrabber")
        self.init_webdriver()

        if self.config['INSERAT']['blacklist']:
            self.blacklist = loadblacklist()
            if self.blacklist:
                self.ui.success(f"Loaded Blacklist with {len(self.blacklist)} Keywords")
                logger.info(f"Loaded blacklist with {len(self.blacklist)} keywords")
                time.sleep(1)
        else:
            self.blacklist = []
            logger.info("Blacklist feature disabled")

    def init_webdriver(self):
        try:
            logger.info("Initializing webdriver")
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--disable-blink-features=AutomationControlled')
            self.driver = uc.Chrome(options=options)
            self.driver.implicitly_wait(10)
            logger.debug("Webdriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize webdriver: {str(e)}")
            self.ui.error(f"Failed to initialize webdriver: {str(e)}")
            raise

    def harvestcategories(self):
        categories = []
        try:
            logger.info("Harvesting main categories")
            self.ui.status("Fetching main categories...")
            self.driver.get("https://www.kleinanzeigen.de/s-kategorien.html")
            WebDriverWait(self.driver, 40).until(
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
            logger.info(f"Found {len(categories)} main categories")
            return categories
        except Exception as e:
            logger.error(f"Failed to harvest categories: {str(e)}", exc_info=True)
            self.ui.error(f"Kategorien konnte nicht geladen werden: {str(e)[:70]}")
            return []

    def harvestsubcategories(self, categoryname, categoryurl, categoryid):
        categories = [(categoryname, categoryurl, categoryid)]

        try:
            full_url = f"https://www.kleinanzeigen.de{categoryurl}"
            logger.info(f"Harvesting subcategories from: {full_url}")
            self.ui.status(f"Fetching from: {full_url}")

            self.driver.get(full_url)

            # Check for Cloudflare or other protection
            if "cf-chl-bypass" in self.driver.current_url or "sorry" in self.driver.current_url or "captcha" in self.driver.page_source.lower():
                logger.warning("Cloudflare or CAPTCHA protection detected")
                self.ui.error("Cloudflare-Blockierung oder CAPTCHA erkannt! Manuelle Lösung benötigt.")
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

            logger.info(f"Found {len(categories) - 1} subcategories for {categoryname}")
            return categories

        except Exception as e:
            logger.error(f"Error harvesting subcategories: {str(e)}", exc_info=True)
            self.ui.error(f"Critical error: {str(e)[:70]}")
            return categories

    def grabad(self, adlink, catname):
        try:
            logger.debug(f"Processing ad: {adlink}")
            req = self.session.get(adlink, timeout=10)
            req.raise_for_status()
            parser = HTMLParser(req.text)

            title_element = parser.css_first('#viewad-title')
            if not title_element:
                logger.debug(f"No title found for ad: {adlink}")
                return
            title = title_element.text().replace("/", "+").replace("\\", "+").strip()

            # Blacklist check
            if self.blacklist and any(blkey.lower() in title.lower() for blkey in self.blacklist):
                logger.debug(f"Ad '{title}' skipped - blacklisted keyword match")
                return

            price_element = parser.css_first('#viewad-price')
            price_text = price_element.text() if price_element else ""
            try:
                price = int(re.sub(r"\D", "", price_text)) if price_text else 0
                newprice = round(price * self.config["INSERAT"]["pricereduction"])
            except ValueError:
                logger.warning(f"Could not parse price '{price_text}', using 0")
                price = 0
                newprice = 0

            description_element = parser.css_first('#viewad-description-text')
            description = description_element.text().lstrip() if description_element else ""

            addate_element = parser.css_first('#viewad-extra-info > div:nth-child(1) > span:nth-child(2)')
            addate = addate_element.text().strip() if addate_element else ""

            grabdate = datetime.now()

            adid_element = parser.css_first('.text-light-800 > li:nth-child(2)')
            if not adid_element:
                logger.debug(f"No ad ID found for ad: {adlink}")
                return
            adid = adid_element.text().strip()

            try:
                req = self.session.get(f"https://www.kleinanzeigen.de/s-vac-inc-get.json?adId={adid}", timeout=10)
                views = req.json().get("numVisits", 0) if req.status_code == 200 else 0
            except Exception as e:
                logger.warning(f"Error getting view count: {str(e)}")
                views = 0

            if views >= self.config['INSERAT']['minviews']:
                logger.info(f"Processing ad: {title} (ID: {adid}, Views: {views})")

                safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
                path = f"Kleinanzeigen/{catname.replace('/', '')}_{price}€_{safe_title}"
                path = createinseratfolder(path)

                if path:
                    images = parser.css('#viewad-image')
                    logger.info(f"Found {len(images)} images for ad {adid}")

                    for i, image in enumerate(images):
                        imageurl = image.attributes.get('src', '')
                        if imageurl:
                            img_path = os.path.join(path, "Pics", f"pic{i}.jpg")
                            if download_image(imageurl, img_path, self.config):
                                logger.debug(f"Successfully downloaded image {i + 1} for ad {adid}")
                            else:
                                logger.warning(f"Failed to download image {i + 1} for ad {adid}")

                    try:
                        with open(os.path.join(path, "text.txt"), "w", encoding='utf-8') as textfile:
                            textfile.write(f"URL: {adlink}\nID: {adid}\nVIEWS: {views}\nCATEGORY: {catname}\n"
                                           f"TITLE: {title}\nPRICE: {newprice}€\nADDATE: {addate}\n"
                                           f"GRABDATE: {grabdate}\nDESCRIPTION: {description}")
                        logger.debug(f"Successfully saved ad info for {adid}")
                    except Exception as e:
                        logger.error(f"Error saving text file for ad {adid}: {str(e)}")
                else:
                    logger.warning(f"Failed to create folder for ad {adid}")
            else:
                logger.debug(
                    f"Skipping ad {adid} - only {views} views (min required: {self.config['INSERAT']['minviews']})")

        except Exception as e:
            logger.error(f"Error processing ad {adlink}: {str(e)}")
            if self.config.get("DEBUG_MODE", False):
                logger.debug(traceback.format_exc())

    def harvestads(self, category, categoryid, categoryname):
        self.ui.printbanner()
        links = set()

        logger.info(f"Harvesting ads for category: {categoryname}")

        min_price = self.config['INSERAT'].get('minprice', 0)
        max_price = self.config['INSERAT'].get('maxprice', 10000000)

        logger.info(f"Price range: {min_price}€ - {max_price}€")

        for pageindex in tqdm(range(1, 51),
                              desc=f"{self.ui.colors['main']}Collecting Links",
                              unit="pages",
                              colour="CYAN"):
            try:
                url = f"https://www.kleinanzeigen.de{category}/preis:{min_price}:{max_price}/seite:{pageindex}"
                logger.debug(f"Fetching page {pageindex}: {url}")
                self.driver.get(url)

                if "captcha" in self.driver.page_source.lower() or "sorry" in self.driver.current_url:
                    logger.warning("CAPTCHA detected on page fetch")
                    self.ui.error("CAPTCHA detected! Manual solution required.")
                    input("Press ENTER after you have solved the CAPTCHA...")
                    self.driver.get(url)

                parser = HTMLParser(self.driver.page_source)
                adlinktags = parser.css('.aditem a')

                new_links = set(["https://www.kleinanzeigen.de" + adlinktag.attributes.get('href', '')
                                 for adlinktag in adlinktags if adlinktag.attributes.get('href')])

                links.update(new_links)
                logger.debug(
                    f"Found {len(new_links)} links on page {pageindex}. Total unique links so far: {len(links)}")

                # Check if we've reached the last page
                pagination = parser.css_first('.pagination-next')
                if not pagination or "disabled" in pagination.attributes.get('class', ''):
                    logger.info(f"Reached last page at {pageindex}")
                    break

            except Exception as e:
                logger.error(f"Error on page {pageindex}: {str(e)}")
                if self.config.get("DEBUG_MODE", False):
                    logger.debug(traceback.format_exc())
                continue

        logger.info(f"Total links collected: {len(links)}")
        self.ui.success(f"Collected {len(links)} ad links")

        # Check if we have links to process
        if not links:
            self.ui.error("No ad links found!")
            return

        # Process the ads with threads
        max_threads = self.config['MISC']['GRABBER'].get('maxthreads', 10)
        logger.info(f"Processing ads with {max_threads} threads")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            list(tqdm(executor.map(self.grabad, links, repeat(categoryname)),
                      unit="ads",
                      desc=f"{self.ui.colors['main']}Grabbing Ads",
                      colour="CYAN",
                      total=len(links)))

        logger.info(f"Finished processing {len(links)} ads")
        self.ui.success(f"Finished grabbing {len(links)} ads")

    def klaz_slct_cat(self, categories):
        self.ui.printbanner()
        print("")
        self.ui.status("Select Category")
        print("")

        # Display available categories
        for index, cat in enumerate(categories):
            if index < 10:
                self.ui.menupoint(id=f"{index} ", text=cat[0])
            else:
                self.ui.menupoint(id=f"{index}", text=cat[0])
        self.ui.menupoint(id="C ", text="Custom Category")

        try:
            command = self.ui.cinput("Select Category: ").lower()
            logger.debug(f"User selected category option: {command}")

            if command != "c":
                command = int(command)
                if 0 <= command < len(categories):
                    cat = categories[command]
                    logger.info(f"Selected category: {cat[0]}")
                    return cat
                else:
                    raise ValueError("Index out of range")
            else:
                # Custom category input
                catname = self.ui.cinput("Category name (Will be the folder in which the ads are saved)")
                caturl = self.ui.cinput("Category rawurl (Example: '/s-audio-hifi')")
                catid = self.ui.cinput("Category ID / Found in Url at the end (Example: 'c172')")
                logger.info(f"Custom category created: {catname}, URL: {caturl}, ID: {catid}")
                return (catname, caturl, catid)
        except (ValueError, IndexError) as e:
            logger.error(f"Invalid category selection: {str(e)}")
            self.ui.error("Not a valid Category")
            time.sleep(2)
            return None


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

    # Set up logging based on config
    global logger
    logger = setup_logging(config.get("DEBUG_MODE", False))

    logger.info(f"Starting application with config: {configpath}")
    ui.success(f"Config ({configpath}) loaded successfully")

    # Check for missing keys in config and add defaults
    if 'minprice' not in config['INSERAT']:
        config['INSERAT']['minprice'] = 0
        logger.warning("minprice not found in config, using default: 0")

    if 'maxprice' not in config['INSERAT']:
        config['INSERAT']['maxprice'] = 10000000
        logger.warning("maxprice not found in config, using default: 10000000")

    time.sleep(random.randint(1, 3))

    while True:
        ui.printbanner()
        print("")
        ui.status("Mainmenu | Select Option")
        if config.get("DEBUG_MODE", False):
            ui.debug("Debug mode is ENABLED")
        print("")
        ui.menupoint("X", "Exit Grabber")
        ui.menupoint("K", "Kleinanzeigen.de")
        ui.menupoint("W", "Willhaben.at (Coming soon)")
        ui.menupoint("C", "Config settings")
        print("")

        command = ui.cinput("Select Module").lower()
        logger.debug(f"User selected main menu option: {command}")

        if command == "x":
            logger.info("Application exit requested")
            sys.exit()
        elif command == "k":
            try:
                grabber = KlazGrabber(config, ui)
                cats = grabber.harvestcategories()
                if not cats:
                    ui.error("Keine Kategorien gefunden")
                    logger.error("No categories found")
                    time.sleep(2)
                    continue

                cat = grabber.klaz_slct_cat(cats)
                if cat:
                    subcats = grabber.harvestsubcategories(*cat)
                    if subcats:
                        selected_cat = grabber.klaz_slct_cat(subcats)
                        if selected_cat:
                            grabber.harvestads(selected_cat[1], selected_cat[2], selected_cat[0])
            except Exception as e:
                logger.critical(f"Critical error in Kleinanzeigen module: {str(e)}", exc_info=True)
                ui.error(f"Critical error: {str(e)}")
                time.sleep(3)
        elif command == "w":
            ui.status("Willhaben.at module is not implemented yet")
            logger.info("User tried to access unimplemented Willhaben module")
            time.sleep(2)
        elif command == "c":
            # Simple config viewer/editor
            ui.printbanner()
            ui.status("Config Settings:")
            print(json.dumps(config, indent=2))
            print("\nOptions:")
            ui.menupoint("1", "Toggle Debug Mode")
            ui.menupoint("2", "Change Minimum Views")
            ui.menupoint("3", "Change Price Range")
            ui.menupoint("4", "Change Max Threads")
            ui.menupoint("B", "Back to Main Menu")

            option = ui.cinput("Select Option").lower()

            if option == "1":
                config["DEBUG_MODE"] = not config.get("DEBUG_MODE", False)
                logger = setup_logging(config["DEBUG_MODE"])
                ui.success(f"Debug mode {'enabled' if config['DEBUG_MODE'] else 'disabled'}")
                logger.info(f"Debug mode changed to {config['DEBUG_MODE']}")
            elif option == "2":
                try:
                    min_views = int(ui.cinput("Enter minimum views"))
                    config["INSERAT"]["minviews"] = min_views
                    ui.success(f"Minimum views set to {min_views}")
                    logger.info(f"Minimum views changed to {min_views}")
                except ValueError:
                    ui.error("Invalid input")
            elif option == "3":
                try:
                    min_price = int(ui.cinput("Enter minimum price"))
                    max_price = int(ui.cinput("Enter maximum price"))
                    config["INSERAT"]["minprice"] = min_price
                    config["INSERAT"]["maxprice"] = max_price
                    ui.success(f"Price range set to {min_price}€ - {max_price}€")
                    logger.info(f"Price range changed to {min_price}€ - {max_price}€")
                except ValueError:
                    ui.error("Invalid input")
            elif option == "4":
                try:
                    max_threads = int(ui.cinput("Enter maximum threads"))
                    config["MISC"]["GRABBER"]["maxthreads"] = max_threads
                    ui.success(f"Maximum threads set to {max_threads}")
                    logger.info(f"Maximum threads changed to {max_threads}")
                except ValueError:
                    ui.error("Invalid input")

            # Save config changes
            if option in ["1", "2", "3", "4"]:
                try:
                    with open(configpath, "w") as f:
                        json.dump(config, f, indent=2)
                    ui.success("Config saved")
                    logger.info("Config changes saved to file")
                except Exception as e:
                    ui.error(f"Failed to save config: {str(e)}")
                    logger.error(f"Failed to save config: {str(e)}")
                time.sleep(1)
        else:
            ui.error("Invalid option")
            logger.debug(f"Invalid menu option selected: {command}")
            time.sleep(1)


if __name__ == "__main__":
    main()