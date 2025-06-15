# poshmark_scraper.py
# Author: Makari Green
# Hybrid scraper: tries requests first, falls back to browser automation

import os
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote_plus

# For browser fallback
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not available. Install with: pip install selenium")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://poshmark.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

def inspect_poshmark_html(soup, query):
    """Inspect HTML and try to find the actual listing containers"""
    print(f"\n🔍 ANALYZING POSHMARK HTML FOR: {query}")
    
    # Check title
    title = soup.find('title')
    if title:
        print(f"Page title: {title.get_text()}")
    
    # Look for React root or main content areas
    main_containers = [
        "#__next",
        "#root", 
        ".main",
        "[role='main']",
        ".search-results",
        ".listings",
        ".products"
    ]
    
    for container in main_containers:
        elements = soup.select(container)
        if elements:
            print(f"Found {container}: {len(elements)} elements")
    
    # Look for div elements with promising class names
    all_divs = soup.find_all('div')
    interesting_classes = []
    
    for div in all_divs[:50]:  # Check first 50 divs
        classes = div.get('class', [])
        if classes:
            class_str = ' '.join(classes)
            if any(keyword in class_str.lower() for keyword in ['tile', 'card', 'item', 'listing', 'product', 'search']):
                if class_str not in interesting_classes:
                    interesting_classes.append(class_str)
    
    print(f"Interesting classes found: {len(interesting_classes)}")
    for cls in interesting_classes[:10]:  # Show first 10
        print(f"  - {cls}")
    
    # Look for data attributes
    data_attrs = []
    for element in soup.find_all(attrs={"data-testid": True})[:10]:
        data_attrs.append(element.get('data-testid'))
    
    if data_attrs:
        print(f"Data-testid attributes: {data_attrs}")
    
    # Count images
    all_imgs = soup.find_all('img')
    poshmark_imgs = [img for img in all_imgs if img.get('src') and 'poshmark' in img.get('src', '')]
    print(f"Total images: {len(all_imgs)}, Poshmark images: {len(poshmark_imgs)}")
    
    print("=" * 60)
    return interesting_classes

def try_requests_method(query, max_results, output_folder):
    """Try the simple requests method first"""
    print("🔄 Trying requests method...")
    
    encoded_query = quote_plus(query)
    urls = [
        f"https://poshmark.com/search?query={encoded_query}&type=listings",
        f"https://poshmark.com/search?q={encoded_query}",
    ]
    
    for url in urls:
        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            interesting_classes = inspect_poshmark_html(soup, query)
            
            # Try the classes we found
            listings = []
            for class_name in interesting_classes:
                potential_listings = soup.select(f".{class_name.replace(' ', '.')}")
                if potential_listings and len(potential_listings) > 1:  # More than 1 suggests listings
                    print(f"✅ Found {len(potential_listings)} listings with class: {class_name}")
                    listings = potential_listings
                    break
            
            if not listings:
                # Try generic selectors as fallback
                fallback_selectors = [
                    "div[class*='tile']",
                    "div[class*='card']", 
                    "div[class*='item']",
                    "div[class*='listing']",
                    "a[href*='/listing/']"
                ]
                
                for selector in fallback_selectors:
                    potential = soup.select(selector)
                    if potential:
                        print(f"Found {len(potential)} elements with selector: {selector}")
                        if len(potential) > 5:  # Likely listings
                            listings = potential
                            break
            
            if listings:
                return process_listings_from_soup(listings, session, query, max_results, output_folder)
            
        except Exception as e:
            print(f"❌ Requests method failed: {e}")
            continue
    
    return None

def try_selenium_method(query, max_results, output_folder):
    """Fallback to Selenium browser automation"""
    if not SELENIUM_AVAILABLE:
        print("❌ Selenium not available for browser fallback")
        return None
    
    print("🔄 Trying Selenium browser method...")
    
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"--user-agent={HEADERS['User-Agent']}")
        
        driver = webdriver.Chrome(options=options)
        
        encoded_query = quote_plus(query)
        url = f"https://poshmark.com/search?query={encoded_query}&type=listings"
        
        print(f"Loading: {url}")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(5)
        
        # Try to find listings with multiple strategies
        listing_selectors = [
            "div[data-testid*='tile']",
            "div[class*='tile']",
            "div[class*='card']",
            "div[class*='item']", 
            "a[href*='/listing/']"
        ]
        
        listings = []
        for selector in listing_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and len(elements) > 3:
                    print(f"✅ Found {len(elements)} listings with selector: {selector}")
                    listings = elements
                    break
            except:
                continue
        
        if not listings:
            # Try scrolling to load more content
            print("Scrolling to load more content...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            
            # Try again
            for selector in listing_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        listings = elements
                        break
                except:
                    continue
        
        if listings:
            results = process_listings_from_selenium(listings, driver, query, max_results, output_folder)
            driver.quit()
            return results
        else:
            print("❌ No listings found with Selenium")
            driver.quit()
            return None
            
    except Exception as e:
        print(f"❌ Selenium method failed: {e}")
        return None

def process_listings_from_soup(listings, session, query, max_results, output_folder):
    """Process listings found via requests/BeautifulSoup"""
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs("results", exist_ok=True)
    
    results = []
    count = 0
    
    for i, item in enumerate(listings):
        if count >= max_results:
            break
        
        try:
            # Extract title
            title = None
            for title_sel in ["h3", "h4", ".title", "a"]:
                title_elem = item.select_one(title_sel)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title and len(title) > 3:
                        break
            
            # Extract price
            price = "N/A"
            for price_sel in [".price", "[class*='price']", "span"]:
                price_elem = item.select_one(price_sel)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    if '$' in price_text:
                        price = price_text
                        break
            
            # Extract link
            href = None
            link_elem = item.select_one("a")
            if link_elem:
                href = link_elem.get('href')
            
            if not title and not href:
                continue
            
            listing_url = href if href and href.startswith("http") else f"https://poshmark.com{href}" if href else ""
            
            # Try to find images
            image_urls = []
            for img in item.select("img"):
                src = img.get("src") or img.get("data-src")
                if src and "poshmark" in src:
                    if src.startswith("//"):
                        src = "https:" + src
                    image_urls.append(src)
            
            # Download images
            image_paths = []
            for idx, img_url in enumerate(image_urls[:3]):
                try:
                    time.sleep(random.uniform(0.3, 0.8))
                    img_response = session.get(img_url, timeout=10)
                    img_response.raise_for_status()
                    
                    fname = f"poshmark_{count+1}_{idx+1}.jpg"
                    fpath = os.path.join(output_folder, fname)
                    
                    with open(fpath, "wb") as f:
                        f.write(img_response.content)
                    
                    image_paths.append(fpath)
                    print(f"✅ Downloaded: {fname}")
                    
                except Exception as e:
                    print(f"❌ Image download failed: {e}")
                    continue
            
            result = {
                "title": title or "Unknown Title",
                "price": price,
                "url": listing_url,
                "image_urls": image_urls,
                "image_paths": image_paths,
                "scraped_at": datetime.now().isoformat(),
                "search_query": query,
                "source": "poshmark_requests"
            }
            
            results.append(result)
            count += 1
            print(f"✅ Processed listing {count}: {title[:40] if title else 'Unknown'}...")
            
        except Exception as e:
            print(f"❌ Error processing listing {i+1}: {e}")
            continue
    
    if results:
        output_json = f"results/poshmark_requests_results_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(output_json, "w", encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {len(results)} results to {output_json}")
        return output_json
    
    return None

def process_listings_from_selenium(listings, driver, query, max_results, output_folder):
    """Process listings found via Selenium and download images"""
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs("results", exist_ok=True)
    
    results = []
    count = 0
    
    for i, item in enumerate(listings):
        if count >= max_results:
            break
        
        try:
            # Extract title
            title = None
            try:
                title_elem = item.find_element(By.TAG_NAME, "a")
                title = title_elem.text.strip() if title_elem else None
            except:
                pass
            
            # Extract href
            href = None
            try:
                link_elem = item.find_element(By.TAG_NAME, "a")
                href = link_elem.get_attribute("href")
            except:
                pass
            
            # Extract and download image
            image_paths = []
            try:
                img_elem = item.find_element(By.TAG_NAME, "img")
                img_url = img_elem.get_attribute("src") or img_elem.get_attribute("data-src")
                
                if img_url:
                    try:
                        # Clean up URL
                        if img_url.startswith("//"):
                            img_url = "https:" + img_url
                        
                        print(f"    📸 Downloading image: {img_url}")
                        img_response = requests.get(img_url, timeout=10)
                        img_response.raise_for_status()
                        
                        fname = f"poshmark_{count+1}_{int(time.time()*1000)}.jpg"
                        fpath = os.path.join(output_folder, fname)
                        
                        with open(fpath, "wb") as f:
                            f.write(img_response.content)
                        
                        image_paths.append(fpath)
                        print(f"    ✅ Downloaded: {fname}")
                        
                    except Exception as e:
                        print(f"    ❌ Image download failed: {e}")
            except:
                pass
            
            if not title and not href:
                continue
            
            result = {
                "title": title or "Unknown Title",
                "price": "N/A",  # Could extract this too
                "url": href or "",
                "image_urls": [img_url] if 'img_url' in locals() else [],
                "image_paths": image_paths,
                "scraped_at": datetime.now().isoformat(),
                "search_query": query,
                "source": "poshmark_selenium"
            }
            
            results.append(result)
            count += 1
            print(f"✅ Found listing {count}: {title[:40] if title else 'Unknown'}...")
            
        except Exception as e:
            print(f"❌ Error processing listing {i+1}: {e}")
            continue
    
    if results:
        output_json = f"results/poshmark_selenium_results_{datetime.now().strftime('%Y-%m-%d')}.json"
        with open(output_json, "w", encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {len(results)} results to {output_json}")
        return output_json
    
    return None

def scrape_poshmark(query, max_results=20, output_folder="poshmark_images/"):
    """Main Poshmark scraper - tries multiple methods"""
    print(f"🔍 Starting hybrid Poshmark scraping for: '{query}'")
    print(f"📁 Output folder: {output_folder}")
    
    # Method 1: Try requests first (faster)
    result = try_requests_method(query, max_results, output_folder)
    if result:
        print(f"✅ Requests method successful!")
        return result
    
    # Method 2: Fallback to Selenium
    print("🔄 Requests method failed, trying Selenium...")
    result = try_selenium_method(query, max_results, output_folder)
    if result:
        print(f"✅ Selenium method successful!")
        return result
    
    print("❌ All methods failed")
    return None

if __name__ == "__main__":
    # Test the scraper
    result = scrape_poshmark("watch", max_results=5)
    if result:
        print(f"✅ Test successful: {result}")
    else:
        print("❌ Test failed")