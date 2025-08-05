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
import pytgpt.yepchat as yepchat
from itertools import repeat
from PIL import Image, ImageEnhance, UnidentifiedImageError
from io import BytesIO
from selectolax.parser import HTMLParser
from tqdm import tqdm
from datetime import datetime


# GLOBAL FUNCTIONS
def loadconfig(configpath):
    try:
        with open(configpath, "r") as configfile:
            config = json.load(configfile)
            return config
    except FileExistsError:
        print("ERROR: Config not found")
        return False
    except json.JSONDecodeError:
        print("ERROR: Config corrupted")
        return False

def loadblacklist():
        try:
            with open("blacklist.txt","r") as blacklistfile:
                bl = blacklistfile.read().splitlines()
        except FileNotFoundError:
            return False
        return bl

def createinseratfolder(path):
    inseratepath = "inserate/" + path


    if not os.path.exists(inseratepath):
        os.makedirs(inseratepath + "/Pics")
        return inseratepath

def editimage(image,mirrorimage,changebrightness,clearexif,brightnessrate,file_path):
    image = image

    if changebrightness:
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(brightnessrate)
    if mirrorimage:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    if clearexif:
        exif_dict = {"0th": {}, "Exif": {}}

        # Kameramodell
        exif_dict["0th"][piexif.ImageIFD.Model] = "iPhone 14 Pro"

        # Aufnahmedatum
        now = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        exif_dict["0th"][piexif.ImageIFD.DateTime] = now

        # Kameraeinstellungen
        exif_dict["Exif"][piexif.ExifIFD.FNumber] = (178, 100)  # f/1.78
        exif_dict["Exif"][piexif.ExifIFD.ExposureTime] = (1, 125)  # 1/125 Sekunde
        exif_dict["Exif"][piexif.ExifIFD.ISOSpeedRatings] = 100
        exif_dict["Exif"][piexif.ExifIFD.FocalLength] = (686, 100)  # 6.86 mm

        exif_bytes = piexif.dump(exif_dict)

        data = list(image.getdata())
        image_without_exif = Image.new(image.mode, image.size)
        image_without_exif.putdata(data)

        image = image_without_exif

    image.save(file_path, "jpeg", exif=exif_bytes)


def download_image(url, file_path, config):
    try:
        response = requests.get(url)
        image = Image.open(BytesIO(response.content))
        newimage = editimage(
        image,
        config['MISC']['IMAGES']['mirrorimages'],
        config['MISC']['IMAGES']['changebrightness'],
        config['MISC']['IMAGES']['clearexif'],
        config['MISC']['IMAGES']['brightnessrate'],
        file_path
        )
    
    except requests.RequestException as e:
        print(f"Fehler beim Herunterladen des Bildes: {e}")

def gptrewrite(gptobj,gptpromt,gpttext):
    return gptobj.chat(f"{gptpromt} {gpttext}")
# TERMINAL UI 
class UI:
    def __init__(self):
        self.banner = r'''
                                       ______
                    |\_______________ (_____\\______________
            HH======#H###############H#######################    NISCHENGRABBER v1.00
                    ' ~""""""""""""""`##(_))#H\"""""Y########       CNW: xqi 
                                      ))    \#H\       `"Y###
                                      "      }#H)

        '''
        self.clear = lambda: os.system("cls") if sys.platform == "win32" else os.system("clear")
        self.title = lambda title: os.system("title " + title) if sys.platform == "win32" else ""

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
        self.menupoint = lambda id,text: print(
            f" {self.colors['accent']}{id}{self.colors['reset']} > " + self.colors['main'] + text)

    def printbanner(self):
        self.clear()
        print(self.colors["main"] + self.banner)



# KLAZ GRABBER
class KlazGrabber:
    def __init__(self,config,ui):
        self.session = requests.session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'})
        self.config = config
        self.ui = ui
        if self.config['INSERAT']['blacklist']:
            self.blacklist = loadblacklist()
            if self.blacklist:
                self.ui.success(f"Loaded Blacklist with {len(self.blacklist)} Keywords")
                time.sleep(1)
        else:
            self.blacklist = False
        if self.config['INSERAT']['gptrewrite']:
            self.ai = yepchat.YEPCHAT()

    
    def harvestcategories(self):
        categories = [] 

        req = self.session.get("https://www.kleinanzeigen.de/s-kategorien.html")
        parser = HTMLParser(req.text)

        tags = parser.css(".treelist-headline a")

        for tag in tags:
            href = tag.attributes.get('href', '')
            text = tag.text()

            categories.append((text.replace(" ","").replace("&","/").replace(",","/"),f'/{href.split("/")[1]}',href.split("/")[2]))
        
        return categories

    
    def harvestsubcategories(self,categoryname,categoryurl,categoryid):
        categories = [] 

        categories.append((categoryname,categoryurl,categoryid))

        req = self.session.get(f"https://www.kleinanzeigen.de/{categoryurl}/{categoryid}")
        parser = HTMLParser(req.text)

        tags = parser.css(".browsebox-itemlist")[2].css(".text-link-subdued")

        for tag in tags:
            href = tag.attributes.get('href', '')
            text = tag.text()

            categories.append((text.replace(" ","").replace("&","/").replace(",","/"),f'/{href.split("/")[1]}',href.split("/")[2]))
        
        return categories


    def grabad(self, adlink,catname):
        req = self.session.get(adlink)

        parser = HTMLParser(req.text)

        try:
            title = parser.css_first('#viewad-title').text().replace("/","+").replace("\\","+").strip()

            if any(blkey in title for blkey in self.blacklist):
                return

            price = int(re.sub(r"\D", "", parser.css_first('#viewad-price').text()))
            newprice = round(price * self.config["INSERAT"]["pricereduction"])
            description = parser.css_first('#viewad-description-text').text().lstrip()
            addate = parser.css_first('#viewad-extra-info > div:nth-child(1) > span:nth-child(2)').text().strip()
            grabdate = datetime.now()
            adid = parser.css_first('.text-light-800 > li:nth-child(2)').text().strip()
            adurl = adlink
            images = parser.css('#viewad-image')

            req = self.session.get(f"https://www.kleinanzeigen.de/s-vac-inc-get.json?adId={adid}")
            views = req.json()["numVisits"]
                
        
            if views >= self.config['INSERAT']['minviews']:
                path = f"Kleinanzeigen/{catname.replace('/','')}/{price}€ {title}"

                path = createinseratfolder(path)

                if self.config['INSERAT']['gptrewrite']:
                    description = gptrewrite(self.ai,self.config['INSERAT']['gptprompt'],description)

                if path:
                    for image in images:
                        imageurl = image.attributes.get('src', '')
                        download_image(imageurl, path + "/Pics/" + f"pic{images.index(image)}.jpg",self.config)

                    with open(path + "/text.txt", "w") as textfile:
                        textfile.write(f"URL: {adurl}\nID: {adid}\nVIEWS: {views}\nCATEGORY: {catname}\nTITLE: {title}\nPRICE: {newprice}€\nADDATE: {addate}\nGRABDATE: {grabdate}\nDESCRIPTION: {description}")
                        
                    # self.ui.success(f"Successfully grabbed ad: {title} ({price})")
        except AttributeError:
            pass
        except json.JSONDecodeError:
            pass
        except UnidentifiedImageError:
            pass
        except ValueError:
            pass


    def harvestads(self,category,categoryid,categoryname):
        self.ui.printbanner()
        links = set()
        
        for pageindex in tqdm(range(1,51),desc=f"{self.ui.colors['main']}Collecting Links",unit="pages"):
            req = self.session.get(f"{category}/preis:{self.config['INSERAT']['minprice']}:{self.config['INSERAT']['maxprice']}/seite:{pageindex}/{categoryid}")

            if req.status_code == 302:  # ALLE SEITEN DURCH
                return
            
            if req.ok:
                parser = HTMLParser(req.text)

                adlinktags = parser.css('.aditem a')

                links.update(set(["https://www.kleinanzeigen.de" + adlinktag.attributes.get('href', '') for adlinktag in adlinktags]))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config['MISC']['GRABBER']['maxthreads']) as executor:
            results = list(tqdm(executor.map(self.grabad, links, repeat(categoryname)),unit="ads",desc=f"{self.ui.colors['main']}Grabbing Ads",total=len(links)))
    

    def klaz_slct_cat(self,categories):
        self.ui.printbanner()
        print("")
        self.ui.status("Select Category")
        print("")
        id = 0
        for cat in categories:
            index = categories.index(cat)
            if index < 10:
                self.ui.menupoint(id=f"{index} ",text=cat[0])
            else:
                self.ui.menupoint(id=f"{index}",text=cat[0])
        #self.ui.menupoint(id="C ",text="Custom Category")

        try:
            command = self.ui.cinput("Select Category: ").lower()

            #if command != "c":
            command = int(command)

            cat = categories[command]
            #else:
            #    catname = self.ui.cinput("Category name (Will be the folder in which the ads are saved)")
            #    caturl = self.ui.cinput("Category rawurl (Example: '/s-audio-hifi')")
            #    catid = self.ui.cinput("Category ID / Found in Url at the end (Example: 'c172')")
            #    return (catname,caturl,catid)
        except ValueError or IndexError:
            self.ui.error("Not a valid Category")
            time.sleep(2)
            return
        return cat


# WILLHABEN GRABBER
class WillhabenGrabber:
    def __init__(self,config,ui):
        self.session = requests.session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'})
        self.ui = ui
        self.config = config

    def harvestcategories(self):
        categories = [] 

        req = self.session.get("https://www.willhaben.at/iad/kaufen-und-verkaufen")
        parser = HTMLParser(req.text)

        cattags = parser.css("a.jZyTjb")

        del cattags[-1]

        for tag in cattags:
            link = tag.attributes.get("href")
            title = tag.css_first("span").text()
            categories.append((title.replace(" ","").replace("/","+"),f'https://www.willhaben.at{link}'))
        
        return categories
    
    def harvestsubcategories(self,categoryurl):
        categories = [] 

        req = self.session.get(categoryurl)
        parser = HTMLParser(req.text)

        tags = parser.css("a.eExgwP")

        for tag in tags:
            link = tag.attributes.get("href")
            title = tag.css_first("span").text()
            categories.append((title.replace(" ","").replace("/","+"),f'https://www.willhaben.at{link}'))

        if len(categories) >= 1:
            categories[0] = ("Ganze Kategorie",categories[0][1])

        return categories

    def grabad(self,url,catname):
        req = self.session.get(url)  
        parser = HTMLParser(req.text)

        try:
            title = parser.css_first('.bNbmvL').text().replace("/","+").replace("\\","+").strip()

            if any(blkey in title for blkey in self.blacklist):
                return

            price = int(re.sub(r"\D", "", parser.css_first('.fhfHOO > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > span:nth-child(1)').text()))
            newprice = round(price * self.config["INSERAT"]["pricereduction"])
            description = parser.css_first('.sc-e43c8c17-1 > p:nth-child(1)').text().lstrip()
            addate = parser.css_first('.gUgppM > span:nth-child(1) > span:nth-child(1)').text().replace("Zuletzt geändert: ","").strip()
            grabdate = datetime.now()
            adid = parser.css_first('.gUgppM > span:nth-child(1) > span:nth-child(2)').text()
            adurl = adlink
            images = parser.css("img.sc-e72c1335-5")
                
        
            
            path = f"Willhaben/{catname.replace('/','')}/{price}€ {title}"

            path = createinseratfolder(path)

            if self.config['INSERAT']['gptrewrite']:
                description = gptrewrite(self.ai,self.config['INSERAT']['gptprompt'],description)

            if path:
                for image in images:
                    imageurl = image.attributes.get('src', '')
                    download_image(imageurl, path + "/Pics/" + f"pic{images.index(image)}.jpg",self.config)

                with open(path + "/text.txt", "w") as textfile:
                    textfile.write(f"URL: {adurl}\nID: {adid}\nCATEGORY: {catname}\nTITLE: {title}\nPRICE: {newprice}€\nADDATE: {addate}\nGRABDATE: {grabdate}\nDESCRIPTION: {description}")
                        
                    # self.ui.success(f"Successfully grabbed ad: {title} ({price})")
        except AttributeError as e:
            print(e)
        except json.JSONDecodeError as e:
            print(e)
        except UnidentifiedImageError as e:
            print(e)
        except ValueError as e:
            print(e)



    def harvestads(self,url,name):
        self.ui.printbanner()
        ads = [] 
        pagenum = 1
        req = self.session.get(url + f"?rows=90&PRICE_FROM={self.config['INSERAT']['minprice']}&PRICE_TO={self.config['INSERAT']['minprice']}")

        parser = HTMLParser(req.text)

        while True:
            if not len(ads) >= self.config['MISC']['GRABBER']['maxadspercat']:
                self.ui.printbanner()
                self.ui.status(f"Grabbing Ads | Page: {pagenum} | Total Ads: {len(ads)}")
                nextpage = parser.css_first(".Pagination__PaginationList-sc-zvrf30-0 > li:nth-child(11) > a:nth-child(1)").attributes.get('href')
                
                try:
                    adtagsjson = json.loads(parser.css_first("#skip-to-content > div:nth-child(1) script").text())
                except AttributeError:
                    break

                for adtag in adtagsjson["itemListElement"]:
                    ads.append("https://willhaben.at" + adtag["url"] + f"&rows=90&PRICE_FROM={self.config['INSERAT']['minprice']}&PRICE_TO={self.config['INSERAT']['minprice']}")

                pagenum += 1

                if not nextpage:
                    break
                else:
                    req = self.session.get("https://willhaben.at" + nextpage)
                    parser = HTMLParser(req.text)
            else:
                break
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config['MISC']['GRABBER']['maxthreads']) as executor:
            results = list(tqdm(executor.map(self.grabad, ads, repeat(name)),unit="ads",desc=f"{self.ui.colors['main']}Grabbing Ads",total=len(ads)))

        


    def wh_slct_cat(self,categories):
        self.ui.printbanner()
        print("")
        self.ui.status("Select Category")
        print("")
        id = 0
        for cat in categories:
            index = categories.index(cat)
            if index < 10:
                self.ui.menupoint(id=f"{index} ",text=cat[0])
            else:
                self.ui.menupoint(id=f"{index}",text=cat[0])

        try:
            command = self.ui.cinput("Select Category: ").lower()
            command = int(command)
            cat = categories[command]
        except ValueError or IndexError:
            self.ui.error("Not a valid Category")
            time.sleep(2)
            return
        return cat





# MAIN PROGRAM
def kleinanzeigen(ui,config):
    grabber = KlazGrabber(config,ui)

    categories = grabber.harvestcategories()


    cat = grabber.klaz_slct_cat(categories=categories)
    
    if cat:
        categories = grabber.harvestsubcategories(cat[0],cat[1],cat[2])
        cat = grabber.klaz_slct_cat(categories=categories)
        try:
            grabber.harvestads(f"https://www.kleinanzeigen.de{cat[1]}",f"{cat[2]}",cat[0])
        except requests.exceptions.ConnectionError:
            ui.error("Connection Error: No Internet or wrong category URL")
    else:
        return


def willhaben(ui,config):
    grabber = WillhabenGrabber(config,ui)
    try:
        cats = grabber.harvestcategories()
        cat = grabber.wh_slct_cat(cats)
    except IndexError:
        ui.printbanner()
        ui.error("Cant connect to Willhaben / No Connection or IP Limited (try again later)")
        time.sleep(3)
        return

    if cat:
        while True:
            categories = grabber.harvestsubcategories(cat[1])
            if len(categories) >= 1:
                cat = grabber.wh_slct_cat(categories)
            else:
                newlink = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/" + cat[0].split("/")[-1]
                cat = (newlink,cat[1])
                break
        try:
            grabber.harvestads(cat[1],cat[0])
        except requests.exceptions.ConnectionError:
            ui.error("Connection Error: No Internet or wrong category URL")
    else:
        return
    

def main():
    colorama.init(autoreset=True)

    ui = UI()
    ui.printbanner()

    configpath = ui.cinput(text="Config Path (ENTER = Default)")
    configpath = "config.json" if not configpath else configpath

    config = loadconfig(configpath)

    if config:
        ui.success(f"Config ({configpath}) loaded successfully")
    time.sleep(random.randint(1, 3))

    while True:
        ui.printbanner()
        print("")
        ui.status("Mainmenu | Select Option")
        print("")
        ui.menupoint("X", "Exit Grabber")
        ui.menupoint("K", "Kleinanzeigen.de")
        ui.menupoint("W", "Willhaben.at (Coming Soon)")

        print("")
        command = ui.cinput("Select Module").lower()

        match command:
            case "x":
                sys.exit()
            case "k":
                kleinanzeigen(ui,config)
            case "w":
                willhaben(ui,config)
            case _:
                pass

if __name__ == "__main__":
    main()
