# craigslist_scraper.py
# Author: Makari Green  
# Quick fix version using the classes we found

import os
import time
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from datetime import datetime

def scrape_craigslist(query, city="losangeles", max_results=5, output_folder="output/craigslist"):
    """
    Quick fix Craigslist scraper using the discovered class names
    """
    print(f"[INFO] 🔍 Craigslist scraping: '{query}' in {city}")
    
    # Create output directory
    os.makedirs(output_folder, exist_ok=True)
    
    # Build search URL
    base_url = f"https://{city}.craigslist.org"
    search_url = f"{base_url}/search/sss?query={quote_plus(query)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1"
    }
    
    try:
        print(f"[INFO] Fetching: {search_url}")
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        print(f"✅ Response: {response.status_code}, Content: {len(response.text)} chars")
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Use the classes we discovered
        listings = soup.select(".cl-static-search-result")
        
        if not listings:
            print("❌ No listings found with .cl-static-search-result")
            
            # Try alternative selectors based on common patterns
            alternative_selectors = [
                "li[data-pid]",
                ".search-result", 
                ".result-row",
                "div[data-post-id]",
                ".posting"
            ]
            
            for selector in alternative_selectors:
                listings = soup.select(selector)
                if listings:
                    print(f"✅ Found {len(listings)} listings with {selector}")
                    break
            
            if not listings:
                # Save HTML for debugging
                debug_file = f"debug_cl_{city}_{query.replace(' ', '_')}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(soup.prettify())
                print(f"❌ No listings found. HTML saved to {debug_file}")
                return []
        
        print(f"✅ Found {len(listings)} listings")
        
        results = []
        processed = 0
        
        for i, listing in enumerate(listings):
            if processed >= max_results:
                break
            
            try:
                # Extract title - try multiple approaches
                title = None
                title_selectors = [
                    "a",
                    ".cl-app-anchor", 
                    ".result-title",
                    ".title",
                    "h3",
                    "h4"
                ]
                
                for sel in title_selectors:
                    title_elem = listing.select_one(sel)
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        if title and len(title) > 3:
                            break
                
                if not title:
                    # Try getting text from the listing directly
                    title = listing.get_text(strip=True)
                    if len(title) > 100:  # Too long, probably not a title
                        title = title[:100] + "..."
                
                # Extract URL
                url = None
                link_elem = listing.select_one("a[href]")
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        url = href if href.startswith('http') else base_url + href
                
                # Extract price
                price = "N/A"
                price_selectors = [".price", ".result-price", "[class*='price']"]
                for sel in price_selectors:
                    price_elem = listing.select_one(sel)
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        if '$' in price_text:
                            price = price_text
                            break
                
                # Extract location
                location = city
                location_selectors = [".result-hood", ".location", "[class*='location']"]
                for sel in location_selectors:
                    loc_elem = listing.select_one(sel)
                    if loc_elem:
                        location = loc_elem.get_text(strip=True)
                        break
                
                # Extract image if available and download it
                img_url = None
                img_filename = None
                img_elem = listing.select_one("img")
                if img_elem:
                    img_url = img_elem.get('src') or img_elem.get('data-src')
                    
                    # Download the image if we have a URL
                    if img_url:
                        try:
                            # Make URL absolute if needed
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            elif img_url.startswith('/'):
                                img_url = base_url + img_url
                            
                            print(f"    📸 Downloading image: {img_url}")
                            img_response = requests.get(img_url, headers=headers, timeout=10)
                            img_response.raise_for_status()
                            
                            img_filename = f"craigslist_{processed+1}_{int(time.time()*1000)}.jpg"
                            img_path = os.path.join(output_folder, img_filename)
                            
                            with open(img_path, "wb") as f:
                                f.write(img_response.content)
                            
                            print(f"    ✅ Saved image: {img_filename}")
                            img_filename = img_path  # Store full path
                            
                        except Exception as e:
                            print(f"    ❌ Image download failed: {e}")
                            img_filename = None
                
                # Skip if we don't have basic info
                if not title:
                    print(f"[WARNING] Skipping listing {i+1}: no title found")
                    continue
                
                # Create result
                result = {
                    'title': title,
                    'price': price,
                    'url': url or "",
                    'location': location,
                    'image_url': img_url,
                    'image_path': img_filename,  # Add the downloaded image path
                    'scraped_at': datetime.now().isoformat(),
                    'search_query': query,
                    'city': city,
                    'source': 'craigslist'
                }
                
                results.append(result)
                processed += 1
                print(f"  ✅ {processed}. {title[:50]}... - {price}")
                
                # Small delay between processing
                time.sleep(0.1)
                
            except Exception as e:
                print(f"[WARNING] Error processing listing {i+1}: {e}")
                continue
        
        if results:
            print(f"✅ Successfully scraped {len(results)} Craigslist listings")
        else:
            print("❌ No valid listings extracted")
        
        return results
        
    except Exception as e:
        print(f"[ERROR] Craigslist scraping failed: {e}")
        return []

if __name__ == "__main__":
    # Test the scraper
    print("🧪 Testing Craigslist scraper...")
    results = scrape_craigslist("watch", "losangeles", 5)
    
    if results:
        print(f"\n📊 SUCCESS! Found {len(results)} listings:")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['title'][:60]} - {result['price']}")
    else:
        print("\n❌ No results found")