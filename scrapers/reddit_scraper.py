# reddit_scraper.py
# Author: Makari Green
# Purpose: Scrape Reddit posts from watch-related subreddits and download images for watch matching

import os  # Operating system interface for file/folder operations
import requests  # HTTP library for making web requests to Reddit
from datetime import datetime  # Date and time utilities for timestamps and file naming
import json  # JSON serialization for saving structured post data
import time  # Time utilities for adding delays between requests
import random  # Random number generation for randomizing request delays
import re  # Regular expressions for parsing URLs and cleaning data
from urllib.parse import urljoin, urlparse  # URL utilities for handling relative/absolute URLs

# Enhanced headers to bypass Reddit's image blocking and authentication requirements
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",  # Preferred language for responses
    "Accept-Encoding": "gzip, deflate, br",  # Compression methods we can handle
    "Connection": "keep-alive",  # Keep connection alive for efficiency
    "Upgrade-Insecure-Requests": "1",  # Prefer secure connections
    "Sec-Fetch-Dest": "document",  # Browser security header
    "Sec-Fetch-Mode": "navigate",  # Browser security header
    "Sec-Fetch-Site": "cross-site",  # Browser security header
    "Cache-Control": "no-cache",  # Don't use cached responses
    "Pragma": "no-cache"  # Additional cache control
}

# Enhanced headers specifically for image downloads from Reddit
IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "image",  # Indicates we're fetching images
    "Sec-Fetch-Mode": "no-cors",  # Cross-origin request mode
    "Sec-Fetch-Site": "cross-site",  # Cross-site request
    "Referer": "https://www.reddit.com/",  # Critical: tells Reddit where the request is coming from
    "DNT": "1",  # Do Not Track header
    "Sec-GPC": "1"  # Global Privacy Control
}

# List of watch-related subreddits to search (can be expanded)
WATCH_SUBREDDITS = [
    "Watches", "rolex", "WatchExchange", "PatekPhilippe", 
    "omega", "Tudor", "Seiko", "watchsales", "Watchmarket"
]

def get_reddit_image_url(reddit_url):
    """
    Convert Reddit image URLs to direct downloadable URLs.
    
    Args:
        reddit_url (str): Original Reddit image URL
        
    Returns:
        str: Direct downloadable image URL or None if conversion fails
    """
    if not reddit_url:
        return None
    
    # Handle different Reddit image URL formats
    try:
        # Method 1: Reddit's i.redd.it direct images
        if "i.redd.it" in reddit_url:
            # These are usually direct - just return as-is
            return reddit_url
        
        # Method 2: Reddit preview images (convert to direct)
        elif "preview.redd.it" in reddit_url:
            # Extract the image ID and convert to direct URL
            # Preview URLs look like: https://preview.redd.it/abc123.jpg?auto=webp&s=xyz
            # We want: https://i.redd.it/abc123.jpg
            url_parts = reddit_url.split('/')
            if len(url_parts) >= 4:
                filename = url_parts[-1].split('?')[0]  # Remove query parameters
                return f"https://i.redd.it/{filename}"
        
        # Method 3: Reddit external preview images
        elif "external-preview.redd.it" in reddit_url:
            # These are proxied external images - try to decode the original URL
            # Format: https://external-preview.redd.it/encoded_url?format=pjpg&auto=webp&s=hash
            # We'll try the URL as-is first, then try imgur conversion
            return reddit_url
        
        # Method 4: Imgur URLs (very common on Reddit)
        elif "imgur.com" in reddit_url:
            # Convert imgur page URLs to direct image URLs
            if "/gallery/" in reddit_url or "/a/" in reddit_url:
                # Gallery links - extract ID and try direct link
                imgur_id = reddit_url.split("/")[-1]
                return f"https://i.imgur.com/{imgur_id}.jpg"
            elif "i.imgur.com" not in reddit_url:
                # Regular imgur links - convert to direct image link
                imgur_id = reddit_url.split("/")[-1].split(".")[0]
                # Try multiple formats
                formats = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
                for fmt in formats:
                    potential_url = f"https://i.imgur.com/{imgur_id}{fmt}"
                    return potential_url  # Return first format, will test in download
            else:
                # Already a direct imgur link
                return reddit_url
        
        # Method 5: Direct image URLs from other hosts
        elif any(ext in reddit_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            return reddit_url
        
        # If none of the above, return original URL and hope for the best
        return reddit_url
        
    except Exception as e:
        print(f"Error processing Reddit URL {reddit_url}: {e}")
        return reddit_url

def download_reddit_image(img_url, output_path, max_retries=3):
    """
    Download an image from Reddit with multiple retry strategies.
    
    Args:
        img_url (str): Image URL to download
        output_path (str): Local file path to save the image
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        bool: True if download successful, False otherwise
    """
    # Convert Reddit URL to direct downloadable URL
    direct_url = get_reddit_image_url(img_url)
    
    # Try multiple URL variations and headers
    url_attempts = [direct_url]
    
    # If it's an imgur URL, try multiple formats
    if "imgur.com" in direct_url and not any(ext in direct_url for ext in ['.jpg', '.jpeg', '.png', '.gif']):
        base_url = direct_url.split('.')[0] if '.' in direct_url else direct_url
        url_attempts = [
            f"{base_url}.jpg",
            f"{base_url}.jpeg", 
            f"{base_url}.png",
            f"{base_url}.gif",
            f"{base_url}.webp"
        ]
    
    # Try different header combinations
    header_attempts = [
        IMAGE_HEADERS,  # Primary image headers
        HEADERS,        # General headers
        {              # Minimal headers
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.reddit.com/"
        }
    ]
    
    # Try each URL with each header combination
    for attempt_num in range(max_retries):
        for url_to_try in url_attempts:
            for headers_to_try in header_attempts:
                try:
                    # Add small delay between attempts
                    if attempt_num > 0:
                        time.sleep(random.uniform(0.5, 1.0))
                    
                    # Make the request with current headers
                    response = requests.get(url_to_try, headers=headers_to_try, timeout=15)
                    
                    # Check if request was successful
                    response.raise_for_status()
                    
                    # Verify we got actual image data
                    content_type = response.headers.get('content-type', '').lower()
                    
                    # Check for HTML error pages (Reddit's common blocking response)
                    if 'text/html' in content_type:
                        continue  # Try next combination
                    
                    # Check for valid image content
                    if not content_type.startswith('image/') and len(response.content) < 1000:
                        continue  # Try next combination
                    
                    # Check if we got a reasonable amount of data
                    if len(response.content) < 500:  # Very small files are likely errors
                        continue  # Try next combination
                    
                    # Save the image
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Verify the file was written and has content
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        return True
                    
                except requests.RequestException as e:
                    # Continue to next attempt on network errors
                    continue
                except IOError as e:
                    # Continue to next attempt on file errors
                    continue
    
    # All attempts failed
    return False

def extract_reddit_images(post_data):
    """
    Extract image URLs from various Reddit post formats.
    
    Args:
        post_data (dict): Reddit post data from JSON API
        
    Returns:
        list: List of image URLs found in the post
    """
    # Initialize list to store found image URLs
    image_urls = []
    
    # Check if post has preview images (Reddit's image hosting)
    if post_data.get("preview") and post_data["preview"].get("images"):
        # Loop through all preview images available
        for image in post_data["preview"]["images"]:
            # Get the source image URL (highest quality version)
            if image.get("source") and image["source"].get("url"):
                # Reddit encodes URLs, so we need to decode HTML entities
                img_url = image["source"]["url"].replace("&amp;", "&")
                image_urls.append(img_url)
    
    # Check for direct image links in the post URL
    post_url = post_data.get("url", "")
    if post_url:
        # Check if the post URL points directly to an image file
        if any(post_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            image_urls.append(post_url)
        
        # Check for imgur links (very common on Reddit)
        elif "imgur.com" in post_url:
            image_urls.append(post_url)  # Will be processed by get_reddit_image_url
        
        # Check for Reddit image links
        elif "redd.it" in post_url:
            image_urls.append(post_url)
    
    # Check for images in post text/selftext (markdown image links)
    selftext = post_data.get("selftext", "")
    if selftext:
        # Use regex to find markdown image links [text](url) and direct URLs
        markdown_images = re.findall(r'!\[.*?\]\((https?://[^\)]+)\)', selftext)
        image_urls.extend(markdown_images)
        
        # Find direct image URLs in text
        direct_urls = re.findall(r'https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp)', selftext, re.IGNORECASE)
        image_urls.extend(direct_urls)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in image_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    return unique_urls

def scrape_reddit_subreddit(subreddit: str, search_query: str = None, limit: int = 25, time_filter: str = "week", output_folder: str = "reddit_images/") -> str:
    """
    Scrape posts from a specific subreddit and download images.
    
    Args:
        subreddit (str): Name of subreddit to scrape (without r/)
        search_query (str): Optional search term within the subreddit
        limit (int): Maximum number of posts to process
        time_filter (str): Time filter for posts (hour, day, week, month, year, all)
        output_folder (str): Folder path where downloaded images will be saved
    
    Returns:
        str: Path to the JSON file containing scraped post metadata
    """
    # Construct the Reddit JSON API URL
    if search_query:
        # Search within subreddit for specific terms
        base_url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": search_query,  # Search query
            "restrict_sr": "on",  # Restrict search to this subreddit only
            "sort": "relevance",  # Sort by relevance to search query
            "t": time_filter,  # Time filter for results
            "limit": limit  # Maximum number of posts to fetch
        }
    else:
        # Get hot posts from subreddit (no search query)
        base_url = f"https://www.reddit.com/r/{subreddit}/hot.json"
        params = {
            "limit": limit,  # Maximum number of posts to fetch
            "t": time_filter  # Time filter for results
        }
    
    # Print status message showing what we're scraping
    search_info = f" (searching: '{search_query}')" if search_query else ""
    print(f"Scraping r/{subreddit}{search_info}...")
    print(f"API URL: {base_url}")
    
    try:
        # Make HTTP request to Reddit's JSON API
        print("Fetching posts from Reddit API...")
        response = requests.get(base_url, headers=HEADERS, params=params, timeout=15)
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Parse JSON response from Reddit API
        data = response.json()
        
    except requests.RequestException as e:
        # Handle network errors, timeouts, or HTTP errors
        print(f"Error fetching Reddit data: {e}")
        return None
    except json.JSONDecodeError as e:
        # Handle invalid JSON responses
        print(f"Error parsing Reddit JSON response: {e}")
        return None
    
    # Extract posts from Reddit API response structure
    if "data" not in data or "children" not in data["data"]:
        print("No posts found in Reddit response")
        return None
    
    posts = data["data"]["children"]
    print(f"Found {len(posts)} posts from r/{subreddit}")
    
    # ✅ FIXED: Use output folder directly, no subfolders per subreddit
    subreddit_folder = output_folder  # Save all images to the same folder
    os.makedirs(subreddit_folder, exist_ok=True)
    os.makedirs("results", exist_ok=True)  # Folder for JSON metadata files
    
    # Generate filename for JSON output
    today = datetime.now().strftime("%Y-%m-%d")
    search_suffix = f"_search_{search_query.replace(' ', '_')}" if search_query else ""
    output_json = f"results/reddit_{subreddit}{search_suffix}_{today}.json"
    
    # Initialize list to store all scraped post data
    results = []
    
    # Initialize counter to track successfully processed posts
    count = 0
    
    # Process each post from the subreddit
    for post_index, post_wrapper in enumerate(posts):
        # Reddit API wraps post data in a "data" field
        post_data = post_wrapper.get("data", {})
        
        # Skip if this isn't a valid post
        if not post_data:
            continue
        
        # Extract basic post information
        title = post_data.get("title", "").strip()  # Post title
        author = post_data.get("author", "unknown")  # Username who posted
        score = post_data.get("score", 0)  # Upvotes minus downvotes
        num_comments = post_data.get("num_comments", 0)  # Number of comments
        created_utc = post_data.get("created_utc", 0)  # Unix timestamp when posted
        permalink = post_data.get("permalink", "")  # Relative URL to post
        
        # Convert Reddit relative URL to absolute URL
        full_url = f"https://www.reddit.com{permalink}" if permalink else ""
        
        # Convert Unix timestamp to readable date
        post_date = datetime.fromtimestamp(created_utc).isoformat() if created_utc else "unknown"
        
        # Extract all image URLs from this post
        image_urls = extract_reddit_images(post_data)
        
        # Skip posts without images since we need images for watch matching
        if not image_urls:
            print(f"Skipping post '{title[:50]}...': no images found")
            continue
        
        print(f"Processing post {post_index + 1}: '{title[:50]}...' ({len(image_urls)} images)")
        
        # Download each image found in this post
        post_images = []  # List to store local paths of downloaded images
        
        for img_index, img_url in enumerate(image_urls):
            try:
                # Add delay between image downloads to be respectful
                if img_index > 0:  # No delay for first image
                    time.sleep(random.uniform(0.5, 1.0))
                
                # Generate unique filename for this image
                timestamp = datetime.now().strftime('%H%M%S%f')[:-3]  # Include milliseconds
                safe_title = re.sub(r'[^\w\s-]', '', title)[:30]  # Remove special chars, limit length
                safe_title = re.sub(r'\s+', '_', safe_title)  # Replace spaces with underscores
                filename = f"reddit_{subreddit}_{count + 1}_{img_index + 1}_{safe_title}_{timestamp}.jpg"
                file_path = os.path.join(subreddit_folder, filename)
                
                # Use enhanced download function with retry logic
                print(f"  Downloading image {img_index + 1}/{len(image_urls)}: {img_url}")
                success = download_reddit_image(img_url, file_path)
                
                if success:
                    file_size = os.path.getsize(file_path)
                    print(f"    Successfully saved: {filename} ({file_size} bytes)")
                    post_images.append(file_path)  # Add to list of successfully downloaded images
                else:
                    print(f"    Failed to download image after all retry attempts")
                    continue
                    
            except Exception as e:
                # Handle any unexpected errors during image processing
                print(f"    Unexpected error downloading image: {e}")
                continue
        
        # Only save post data if we successfully downloaded at least one image
        if post_images:
            # Store all post information in structured format
            post_info = {
                "title": title,                                  # Post title
                "author": author,                                # Reddit username
                "subreddit": subreddit,                          # Which subreddit this came from
                "score": score,                                  # Reddit score (upvotes - downvotes)
                "num_comments": num_comments,                    # Number of comments on post
                "post_date": post_date,                          # When post was created
                "url": full_url,                                 # Full URL to Reddit post
                "image_paths": post_images,                      # Local paths to downloaded images
                "image_urls": image_urls[:len(post_images)],     # Original image URLs that worked
                "scraped_at": datetime.now().isoformat(),        # When this data was scraped
                "search_query": search_query,                    # Search term used (if any)
                "source": "reddit"                               # Source platform identifier
            }
            
            # Add this post's data to our results collection
            results.append(post_info)
            count += 1
            
            print(f"  Successfully processed post: {len(post_images)} images saved")
        else:
            print(f"  Skipped post: no images could be downloaded")
        
        # Add delay between posts to be respectful to Reddit's servers
        time.sleep(random.uniform(1.0, 2.0))
    
    # Save all scraped post metadata to JSON file
    try:
        with open(output_json, "w", encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Print comprehensive summary of scraping operation
        print(f"\n{'='*60}")
        print(f"REDDIT SCRAPING COMPLETE")
        print(f"{'='*60}")
        print(f"Subreddit: r/{subreddit}")
        if search_query:
            print(f"Search query: '{search_query}'")
        print(f"Successfully processed: {count} posts")
        print(f"Total images downloaded: {sum(len(post['image_paths']) for post in results)}")
        print(f"Images saved to: {subreddit_folder}")
        print(f"Metadata saved to: {output_json}")
        
        return output_json
        
    except IOError as e:
        print(f"Error saving results to JSON: {e}")
        return None

def scrape_multiple_subreddits(search_query: str, subreddits: list = None, posts_per_sub: int = 10, base_folder: str = "reddit_results/"):
    """
    Scrape multiple subreddits for watch-related posts.
    
    Args:
        search_query (str): Search term to look for across subreddits
        subreddits (list): List of subreddit names to search (defaults to WATCH_SUBREDDITS)
        posts_per_sub (int): Maximum posts to scrape per subreddit
        base_folder (str): Base folder for organizing results
    """
    # Use default watch subreddits if none specified
    if subreddits is None:
        subreddits = WATCH_SUBREDDITS
    
    print(f"Starting multi-subreddit search for: '{search_query}'")
    print(f"Will search {len(subreddits)} subreddits: {', '.join(subreddits)}")
    
    # Process each subreddit in the list
    for i, subreddit in enumerate(subreddits, 1):
        print(f"\n{'='*70}")
        print(f"Searching subreddit {i}/{len(subreddits)}: r/{subreddit}")
        print(f"{'='*70}")
        
        # Create folder structure for this subreddit
        subreddit_folder = os.path.join(base_folder, subreddit)
        
        # Scrape this subreddit and get results
        result_file = scrape_reddit_subreddit(
            subreddit=subreddit,
            search_query=search_query,
            limit=posts_per_sub,
            output_folder=base_folder
        )
        
        # Add delay between subreddits to be extra respectful
        if i < len(subreddits):  # Don't wait after the last subreddit
            delay = random.uniform(2, 4)  # 2-4 second delay between subreddits
            print(f"Waiting {delay:.1f} seconds before next subreddit...")
            time.sleep(delay)

# Main execution block - runs only when script is called directly
if __name__ == "__main__":
    print("Starting Reddit scraping operation...")
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Example 1: Search specific subreddit for watch terms
    result_file = scrape_reddit_subreddit(
        subreddit="Watches",
        search_query="patek philippe",
        limit=10,
        output_folder="reddit_images/"
    )
    
    if result_file:
        print(f"\nSingle subreddit scraping completed!")
        print(f"Results saved to: {result_file}")
    
    # Example 2: Search multiple watch subreddits (uncomment to use)
    # scrape_multiple_subreddits(
    #     search_query="rolex submariner",
    #     posts_per_sub=5,
    #     base_folder="multi_reddit_results/"
    # )
    
    print("\nReddit scraping operation completed!")