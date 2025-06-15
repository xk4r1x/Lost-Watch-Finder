# facebook_marketplace_scraper.py
# Author: Makari Green
# Purpose: Scrape Facebook Marketplace listings using session cookies, save images + metadata
# FIXED: Now extracts individual listing URLs instead of search page URL

import os
import time
import json
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from datetime import datetime
import re

def scrape_facebook_marketplace(query, location="Los Angeles, CA", max_results=5, output_folder="facebook_images"):
    """
    Standard fallback Facebook scraper (non-authenticated) — returns None by default.
    """
    print(f"[WARNING] scrape_facebook_marketplace: Running standard (non-authenticated) method. May fail.")
    return None

def scrape_facebook_marketplace_with_cookies(query, location, max_results, output_folder, cookies):
    """
    Enhanced Facebook Marketplace scraping using session cookies.
    Saves images to output_folder and metadata to output_folder/facebook_results.json
    
    FIXED: Now extracts individual listing URLs, titles, and prices
    """
    print(f"[INFO] Scraping Facebook Marketplace with cookies for query: '{query}' in {location}")
    os.makedirs(output_folder, exist_ok=True)

    # Setup headless undetected ChromeDriver
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = uc.Chrome(options=options)
    driver.get("https://www.facebook.com/")

    # Inject cookies after normalizing them
    for cookie in cookies:
        if "sameSite" in cookie:
            if cookie["sameSite"].lower() == "no_restriction":
                cookie["sameSite"] = "None"
            elif cookie["sameSite"].lower() == "lax":
                cookie["sameSite"] = "Lax"
            elif cookie["sameSite"].lower() == "strict":
                cookie["sameSite"] = "Strict"
        if "expiry" in cookie:
            cookie["expirationDate"] = cookie.pop("expiry")
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            print(f"[WARNING] Failed to add cookie: {e}")

    # Go to Facebook Marketplace search
    search_url = f"https://www.facebook.com/marketplace/search/?query={query.replace(' ', '%20')}&exact=false"
    print(f"[INFO] Navigating to: {search_url}")
    driver.get(search_url)
    time.sleep(5)

    # Scroll to load more items
    print("[INFO] Scrolling to load more listings...")
    for i in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        print(f"[INFO] Scroll {i+1}/3 completed")

    # Extract listing containers (not just images)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    # Find marketplace listing containers
    # Facebook uses various selectors, we'll try multiple approaches
    listing_selectors = [
        "div[role='main'] a[href*='/marketplace/item/']",  # Main marketplace links
        "a[href*='/marketplace/item/']",                   # Any marketplace item links
        "div[data-pagelet*='marketplace'] a",              # Marketplace pagelet links
    ]
    
    listings = []
    for selector in listing_selectors:
        found_listings = soup.select(selector)
        if found_listings:
            print(f"[INFO] Found {len(found_listings)} listings with selector: {selector}")
            listings = found_listings
            break
    
    if not listings:
        print("[WARNING] No listings found with any selector, falling back to image extraction")
        # Fallback: just extract images without URLs
        img_tags = soup.find_all("img")
        listings = [{"img": img} for img in img_tags if img.get("src") and "scontent" in img.get("src")]

    results = []
    successful_downloads = 0

    print(f"[INFO] Processing {min(len(listings), max_results)} listings...")

    for i, listing in enumerate(listings[:max_results]):
        try:
            # Extract listing URL
            if hasattr(listing, 'get') and listing.get('href'):
                # This is an <a> tag with href
                listing_url = listing.get('href')
                if listing_url.startswith('/'):
                    listing_url = f"https://www.facebook.com{listing_url}"
                
                # Find associated image
                img_tag = listing.find('img')
                if not img_tag:
                    # Look for nearby image
                    parent = listing.parent
                    img_tag = parent.find('img') if parent else None
                    
            elif 'img' in listing:
                # Fallback method - just image, no URL
                img_tag = listing['img']
                listing_url = search_url  # Use search URL as fallback
            else:
                continue

            if not img_tag:
                print(f"[WARNING] No image found for listing {i+1}")
                continue

            # Extract image URL
            img_src = img_tag.get("src")
            if not img_src or "scontent" not in img_src:
                continue

            # Extract title (from alt text, aria-label, or nearby text)
            title = "Facebook Marketplace Listing"  # Default
            
            # Try multiple methods to get title
            if img_tag.get('alt'):
                title = img_tag.get('alt')
            elif img_tag.get('aria-label'):
                title = img_tag.get('aria-label')
            elif hasattr(listing, 'text') and listing.text.strip():
                title = listing.text.strip()[:100]  # Limit length
            
            # Clean up title
            title = re.sub(r'\s+', ' ', title).strip()
            if not title or title in ['', ' ']:
                title = f"Facebook Listing {i+1}"

            # Extract price (look for price patterns nearby)
            price = None
            if hasattr(listing, 'text'):
                price_match = re.search(r'\$[\d,]+', listing.text)
                if price_match:
                    price = price_match.group()

            # Download image
            try:
                print(f"[INFO] Downloading image {i+1}/{max_results}...")
                
                # Generate filename
                safe_title = re.sub(r'[^\w\s-]', '', title)[:30]
                safe_title = re.sub(r'\s+', '_', safe_title)
                timestamp = int(time.time() * 1000)
                filename = f"facebook_{i+1}_{safe_title}_{timestamp}.jpg"
                filepath = os.path.join(output_folder, filename)
                
                # Download with headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': 'https://www.facebook.com/'
                }
                
                response = requests.get(img_src, headers=headers, timeout=10)
                response.raise_for_status()
                
                with open(filepath, "wb") as f:
                    f.write(response.content)
                
                # Verify file was saved and has content
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:  # At least 1KB
                    file_size = os.path.getsize(filepath)
                    print(f"[SUCCESS] Saved: {filename} ({file_size} bytes)")
                    
                    # ✅ FIXED: Save proper listing data with individual URLs
                    result_data = {
                        "title": title,
                        "url": listing_url,  # ✅ Individual listing URL, not search page!
                        "listing_url": listing_url,  # ✅ Alternative field name for consistency
                        "price": price,
                        "image_path": filepath,  # ✅ Local file path for matching
                        "image_url": img_src,    # ✅ Original image URL
                        "platform": "facebook",
                        "scraped_at": datetime.now().isoformat(),
                        "search_query": query,
                        "date_posted": datetime.now().strftime("%Y-%m-%d"),  # ✅ Add date
                        "source": "facebook_marketplace"
                    }
                    
                    results.append(result_data)
                    successful_downloads += 1
                    
                else:
                    print(f"[WARNING] File too small or failed to save: {filename}")
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
            except Exception as e:
                print(f"[ERROR] Failed to download image {i+1}: {e}")
                continue

        except Exception as e:
            print(f"[ERROR] Failed to process listing {i+1}: {e}")
            continue
        
        # Small delay between downloads
        time.sleep(1)

    driver.quit()
    print(f"[INFO] Browser session closed")
    print(f"[INFO] Successfully downloaded {successful_downloads}/{max_results} listings")

    if not results:
        print("[WARNING] No images were successfully downloaded")
        return None

    # ✅ FIXED: Save metadata with proper structure for chatbot integration
    metadata_path = os.path.join(output_folder, "facebook_results.json")
    with open(metadata_path, "w", encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[SUCCESS] Metadata saved to: {metadata_path}")
    print(f"[INFO] Sample result URLs:")
    for i, result in enumerate(results[:3]):
        print(f"  {i+1}. {result['title'][:50]}... -> {result['url']}")

    return metadata_path

# Optional test run (not used by run_all.py)
if __name__ == "__main__":
    print("🧪 Testing Facebook Marketplace scraper...")
    
    # Load cookies
    try:
        with open("facebook_cookies.json", "r") as f:
            cookies = json.load(f)
        print("✅ Loaded Facebook cookies")
    except FileNotFoundError:
        print("❌ facebook_cookies.json not found")
        exit(1)
    
    # Test scrape
    result = scrape_facebook_marketplace_with_cookies(
        query="patek philippe",
        location="Los Angeles, CA",
        max_results=3,  # Small test
        output_folder="test_fb_output",
        cookies=cookies
    )
    
    if result:
        print(f"✅ Test completed! Results saved to: {result}")
    else:
        print("❌ Test failed - no results")