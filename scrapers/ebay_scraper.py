# ebay_scraper.py
# Author: Makari Green
# Purpose: Scrape eBay listings and download images for watch matching

import os  # Operating system interface for file/folder operations
import requests  # HTTP library for making web requests
from bs4 import BeautifulSoup  # HTML parsing library for extracting data from web pages
from datetime import datetime  # Date and time utilities for timestamps
import json  # JSON serialization for saving structured data
from urllib.parse import quote_plus  # URL encoding to handle special characters in search queries
import time  # Time utilities for adding delays between requests
import random  # Random number generation for randomizing request delays

# Headers to simulate a real browser request and avoid being blocked by eBay
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",  # Accept various content types
    "Accept-Language": "en-US,en;q=0.5",  # Preferred languages for response
    "Accept-Encoding": "gzip, deflate",  # Compression methods we can handle
    "Connection": "keep-alive",  # Keep connection alive for efficiency
    "Upgrade-Insecure-Requests": "1"  # Prefer HTTPS over HTTP
}

def scrape_ebay(query: str, max_results: int = 10, output_folder: str = "test_images/") -> str:
    """
    Scrapes eBay search results and downloads listing images for watch matching.
    
    Args:
        query (str): Search term to look for on eBay
        max_results (int): Maximum number of listings to scrape
        output_folder (str): Folder path where downloaded images will be saved
    
    Returns:
        str: Path to the JSON file containing scraped listing metadata
    """
    # Print status message showing what search query is being processed
    print(f"Scraping eBay for query: {query}")
    
    # Encode the search query for safe inclusion in URL (handles spaces and special characters)
    encoded_query = quote_plus(query)
    
    # Construct the eBay search URL with encoded query and results per page limit
    url = f"https://www.ebay.com/sch/i.html?_nkw={encoded_query}&_ipg={max_results}"
    
    try:
        # Make HTTP request to eBay search page with browser-like headers
        print(f"Fetching search results from: {url}")
        response = requests.get(url, headers=HEADERS, timeout=10)  # 10 second timeout
        
        # Check if the request was successful (status code 200)
        response.raise_for_status()
        
    except requests.RequestException as e:
        # Handle network errors, timeouts, or HTTP errors
        print(f"Error fetching eBay page: {e}")
        return None
    
    # Parse the HTML content using BeautifulSoup for easy data extraction
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Create output directories if they don't exist (exist_ok=True prevents errors if they exist)
    os.makedirs(output_folder, exist_ok=True)  # Folder for downloaded images
    os.makedirs("results", exist_ok=True)      # Folder for JSON metadata files
    
    # Generate filename for JSON output using today's date for organization
    today = datetime.now().strftime("%Y-%m-%d")  # Format: YYYY-MM-DD
    output_json = f"results/ebay_results_{today}.json"
    
    # Initialize list to store all scraped listing data
    results = []
    
    # Find all listing items using CSS selector (eBay's standard listing container class)
    listings = soup.select(".s-item")
    print(f"Found {len(listings)} potential listings on page")
    
    # Initialize counter to track successfully processed listings
    count = 0
    
    # Process each listing item found on the search results page
    for item in listings:
        # Extract key elements from each listing using CSS selectors
        title_tag = item.select_one(".s-item__title")        # Product title
        link_tag = item.select_one(".s-item__link")          # Link to full listing
        img_tag = item.select_one(".s-item__image img")      # Product image
        price_tag = item.select_one(".s-item__price")        # Current price
        
        # Skip this listing if any required elements are missing (incomplete listing)
        if not all([title_tag, link_tag, img_tag, price_tag]):
            print(f"Skipping incomplete listing {count + 1}")
            continue
        
        # Extract text content and clean up whitespace
        title = title_tag.text.strip()  # Remove leading/trailing whitespace
        listing_url = link_tag["href"]  # Get href attribute for the listing URL
        
        # Get image URL, trying both 'src' and 'data-src' attributes (lazy loading fallback)
        img_url = img_tag.get("src") or img_tag.get("data-src")
        
        # Extract price text, with fallback to "N/A" if price element exists but has no text
        price = price_tag.text.strip() if price_tag else "N/A"
        
        # Skip listings without valid image URLs
        if not img_url:
            print(f"No image URL found for listing: {title[:50]}...")
            continue
        
        try:
            # Add random delay between requests to be respectful to eBay's servers
            time.sleep(random.uniform(0.5, 1.5))  # Random delay between 0.5 and 1.5 seconds
            
            # Download the product image with timeout and error handling
            print(f"Downloading image {count + 1}: {title[:50]}...")
            img_response = requests.get(img_url, headers=HEADERS, timeout=15)
            
            # Check if image download was successful
            img_response.raise_for_status()
            
            # Generate unique filename for this image
            filename = f"ebay_{count + 1}_{datetime.now().strftime('%H%M%S')}.jpg"
            file_path = os.path.join(output_folder, filename)
            
            # Save the downloaded image data to file in binary mode
            with open(file_path, 'wb') as f:
                f.write(img_response.content)
            
            # Verify that the file was created and has content
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                print(f"Successfully saved: {filename}")
            else:
                print(f"Warning: Image file appears to be empty: {filename}")
                continue
                
        except requests.RequestException as e:
            # Handle network errors during image download
            print(f"Failed to download image for '{title[:30]}...': {e}")
            continue
        except IOError as e:
            # Handle file system errors during image saving
            print(f"Failed to save image file: {e}")
            continue
        
        # Store all listing information in structured format
        listing_data = {
            "title": title,                              # Product title
            "url": listing_url,                          # Link to full eBay listing
            "image_path": file_path,                     # Local path to downloaded image
            "image_url": img_url,                        # Original image URL from eBay
            "price": price,                              # Listed price
            "scraped_at": datetime.now().isoformat(),    # When this data was scraped
            "search_query": query                        # What search term found this listing
        }
        
        # Add this listing's data to our results collection
        results.append(listing_data)
        
        # Increment counter for successfully processed listings
        count += 1
        
        # Stop processing if we've reached the desired number of results
        if count >= max_results:
            print(f"Reached maximum results limit ({max_results})")
            break
    
    # Save all scraped listing metadata to JSON file for later reference
    try:
        with open(output_json, 'w', encoding='utf-8') as f:  # UTF-8 encoding for international characters
            json.dump(results, f, indent=2, ensure_ascii=False)  # Pretty-printed JSON with Unicode support
        
        # Print summary of scraping operation
        print(f"\n{'='*50}")
        print(f"SCRAPING COMPLETE")
        print(f"{'='*50}")
        print(f"Successfully scraped: {count} listings")
        print(f"Images saved to: {output_folder}")
        print(f"Metadata saved to: {output_json}")
        print(f"Search query was: '{query}'")
        
        # Return the path to the JSON file for potential further processing
        return output_json
        
    except IOError as e:
        # Handle errors when saving the JSON metadata file
        print(f"Error saving results to JSON: {e}")
        return None

def scrape_multiple_queries(queries: list, max_results_per_query: int = 10, base_folder: str = "scraped_images/"):
    """
    Scrape multiple search queries in sequence.
    
    Args:
        queries (list): List of search terms to scrape
        max_results_per_query (int): Maximum results per search query
        base_folder (str): Base folder for organizing scraped images
    """
    # Process each search query in the provided list
    for i, query in enumerate(queries, 1):
        print(f"\n{'='*60}")
        print(f"Processing query {i}/{len(queries)}: '{query}'")
        print(f"{'='*60}")
        
        # Create separate folder for each query to keep results organized
        query_folder = os.path.join(base_folder, f"query_{i}_{query.replace(' ', '_')}")
        
        # Scrape this query and get results
        result_file = scrape_ebay(query, max_results_per_query, query_folder)
        
        # Add longer delay between different queries to be extra respectful
        if i < len(queries):  # Don't wait after the last query
            print(f"Waiting before next query...")
            time.sleep(random.uniform(2, 4))  # 2-4 second delay between queries

# Main execution block - runs only when script is called directly
if __name__ == "__main__":
    # Example usage: scrape for luxury watch brands
    search_queries = [
        "patek philippe watch",
        "rolex submariner",
        "omega speedmaster",
        "audemars piguet"
    ]
    
    print("Starting eBay scraping operation...")
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Option 1: Scrape single query
    scrape_ebay(query="patek philippe watch", max_results=10, output_folder="test_images/")
    
    # Option 2: Scrape multiple queries (uncomment to use)
    # scrape_multiple_queries(search_queries, max_results_per_query=5, base_folder="multi_query_results/")
    
    print("\nScraping operation completed!")