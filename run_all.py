# run_all.py
# Author: Makari Green
# Purpose: Master orchestrator script that runs all scrapers and watch matching in sequence
# This is the main entry point for the complete watch finding system

import os  # Operating system interface for file and directory operations
import sys  # System-specific parameters and functions for script control
import json  # JSON handling for loading/saving structured data
import time  # Time utilities for delays and timestamps
import argparse  # Command-line argument parsing for script configuration
from datetime import datetime  # Date and time utilities for session logging
from pathlib import Path  # Modern path handling for cross-platform compatibility
import shutil  # High-level file operations for moving/copying files

# Import all our custom scraper modules
try:
    from scrapers.ebay_scraper import scrape_ebay  # eBay marketplace scraper
    from scrapers.craigslist_scraper import scrape_craigslist  # Craigslist scraper
    from scrapers.reddit_scraper import scrape_reddit_subreddit, scrape_multiple_subreddits  # Reddit scraper
    from scrapers.poshmark_scraper import scrape_poshmark  # Poshmark fashion marketplace scraper
    from scrapers.facebook_marketplace_scraper import scrape_facebook_marketplace_with_cookies  # Facebook Marketplace scraper
    from match_watch import WatchMatcher  # Your AI-powered watch matching system
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure all scraper files are in the 'scrapers/' directory and match_watch.py is in the root directory")
    sys.exit(1)

# Configuration class to store all session settings and parameters
class WatchFinderConfig:
    """Configuration class that holds all settings for a complete watch finding session."""
    
    def __init__(self):
        # Session identification and logging
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # Unique session identifier
        self.session_folder = f"sessions/session_{self.session_id}"  # Folder for this session's data
        
        # Reference watch configuration (the watch we're looking for)
        self.reference_folder = "lost_watch_images/"  # Folder containing photos of the lost watch
        self.match_threshold = 0.80  # Minimum similarity score to consider a match (0.0 to 1.0)
        
        # Scraping configuration - how many results to get from each platform
        self.ebay_max_results = 20  # Maximum eBay listings to scrape
        self.craigslist_max_results = 15  # Maximum Craigslist listings to scrape
        self.reddit_max_results = 10  # Maximum Reddit posts to scrape
        self.poshmark_max_results = 15  # Maximum Poshmark listings to scrape
        self.facebook_max_results = 8  # Maximum Facebook Marketplace listings (keep low to avoid blocking)
        
        # Platform selection - which marketplaces to search
        self.enabled_platforms = {
            'ebay': True,  # Enable eBay scraping
            'craigslist': True,  # Enable Craigslist scraping
            'reddit': False,  # Disable Reddit by default (requires API setup)
            'poshmark': True,  # Enable Poshmark scraping
            'facebook': False  # Disable Facebook by default (requires ChromeDriver and often gets blocked)
        }
        
        # Geographic configuration for location-based searches
        self.craigslist_cities = ["losangeles", "newyork", "chicago"]  # Cities to search on Craigslist
        self.facebook_location = "Los Angeles, CA"  # Location for Facebook Marketplace search
        self.facebook_cookies_file = "facebook_cookies.json"  # Path to Facebook cookies file
        
        # Reddit-specific configuration
        self.reddit_subreddits = ["Watches", "WatchExchange", "rolex", "PatekPhilippe"]  # Subreddits to search
        
        # Output and organization settings
        self.consolidated_images_folder = None  # Will be set during session initialization
        self.results_summary_file = None  # Will be set during session initialization

class WatchFinderOrchestrator:
    """Main orchestrator class that coordinates all scraping and matching operations."""
    
    def __init__(self, config: WatchFinderConfig, search_query: str):
        """
        Initialize the orchestrator with configuration and search parameters.
        
        Args:
            config (WatchFinderConfig): Configuration object with all session settings
            search_query (str): The search term to use across all platforms (e.g., "patek philippe watch")
        """
        self.config = config  # Store configuration for this session
        self.search_query = search_query  # Store the search query
        self.session_log = []  # List to store log entries for this session
        self.all_scraped_files = []  # List to store paths to all scraped JSON files
        self.all_image_folders = []  # List to store paths to all image folders
        self.match_results = {}  # Dictionary to store matching results from each platform
        
        # Initialize session folder structure
        self._setup_session_folders()
        
        # Initialize the AI watch matcher
        try:
            self.matcher = WatchMatcher(reference_folder=self.config.reference_folder)
        except Exception as e:
            self._log(f"Warning: Could not initialize WatchMatcher: {e}", "WARNING")
            self.matcher = None
        
        # Log session start
        self._log(f"Session started: {self.config.session_id}")
        self._log(f"Search query: '{self.search_query}'")
        self._log(f"Reference images folder: {self.config.reference_folder}")
    
    def _setup_session_folders(self):
        """Create folder structure for organizing this session's data."""
        # Create main session folder
        os.makedirs(self.config.session_folder, exist_ok=True)
        
        # Create subfolders for different types of data
        os.makedirs(f"{self.config.session_folder}/scraped_images", exist_ok=True)  # All downloaded images
        os.makedirs(f"{self.config.session_folder}/results", exist_ok=True)  # JSON metadata files
        os.makedirs(f"{self.config.session_folder}/matches", exist_ok=True)  # Matching results
        os.makedirs(f"{self.config.session_folder}/logs", exist_ok=True)  # Session logs
        
        # Set paths for consolidated results
        self.config.consolidated_images_folder = f"{self.config.session_folder}/scraped_images"
        self.config.results_summary_file = f"{self.config.session_folder}/results/session_summary.json"
    
    def _log(self, message: str, level: str = "INFO"):
        """
        Add an entry to the session log with timestamp.
        
        Args:
            message (str): Log message to record
            level (str): Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        # Create timestamped log entry
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message
        }
        
        # Add to session log
        self.session_log.append(log_entry)
        
        # Print to console with color coding
        colors = {
            "INFO": "\033[94m",      # Blue
            "SUCCESS": "\033[92m",   # Green
            "WARNING": "\033[93m",   # Yellow
            "ERROR": "\033[91m"      # Red
        }
        reset_color = "\033[0m"
        
        color = colors.get(level, "")
        print(f"{color}[{timestamp}] {level}: {message}{reset_color}")
    
    def _save_results_to_session(self, results, platform_name, session_result_filename):
        """Helper function to save scraper results to session folder and return the file path."""
        if not results:
            return None
            
        session_result_file = f"{self.config.session_folder}/results/{session_result_filename}"
        
        try:
            with open(session_result_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            self.all_scraped_files.append(session_result_file)
            self._log(f"{platform_name} results saved: {session_result_file}", "SUCCESS")
            return session_result_file
            
        except Exception as e:
            self._log(f"Error saving {platform_name} results: {e}", "ERROR")
            return None
    
    def run_ebay_scraper(self):
        """Execute eBay scraping and organize results."""
        if not self.config.enabled_platforms['ebay']:
            self._log("eBay scraping disabled in configuration", "INFO")
            return None
        
        self._log("Starting eBay scraping...", "INFO")
        
        try:
            # Create eBay-specific folder within session
            ebay_folder = f"{self.config.consolidated_images_folder}/ebay"
            
            # Run eBay scraper
            result_file = scrape_ebay(
                query=self.search_query,
                max_results=self.config.ebay_max_results,
                output_folder=ebay_folder
            )
            
            if result_file and os.path.exists(result_file):
                # Load the results and move file to session
                with open(result_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                
                session_result_file = self._save_results_to_session(results, "eBay", "ebay_results.json")
                self.all_image_folders.append(ebay_folder)
                
                # Clean up original file
                try:
                    os.remove(result_file)
                except:
                    pass
                    
                return session_result_file
            else:
                self._log("eBay scraping failed - no results", "ERROR")
                return None
                
        except Exception as e:
            self._log(f"eBay scraping error: {e}", "ERROR")
            return None
    
    def run_craigslist_scraper(self):
        """Execute Craigslist scraping across multiple cities."""
        if not self.config.enabled_platforms['craigslist']:
            self._log("Craigslist scraping disabled in configuration", "INFO")
            return []
        
        self._log("Starting Craigslist scraping...", "INFO")
        result_files = []
        
        # Scrape each configured city
        for city in self.config.craigslist_cities:
            self._log(f"Scraping Craigslist in {city}...", "INFO")
            
            try:
                # Create city-specific folder
                city_folder = f"{self.config.consolidated_images_folder}/craigslist_{city}"
                
                # Run Craigslist scraper for this city
                results = scrape_craigslist(
                    query=self.search_query,
                    city=city,
                    max_results=self.config.craigslist_max_results,
                    output_folder=city_folder
                )
                
                if results:
                    # Save results to session folder
                    session_result_file = self._save_results_to_session(results, f"Craigslist {city}", f"craigslist_{city}_results.json")
                    if session_result_file:
                        result_files.append(session_result_file)
                        self.all_image_folders.append(city_folder)
                else:
                    self._log(f"Craigslist {city} scraping failed - no results", "WARNING")
                    
            except Exception as e:
                self._log(f"Craigslist {city} error: {e}", "ERROR")
        
        return result_files
    
    def run_reddit_scraper(self):
        """Execute Reddit scraping across watch-related subreddits."""
        if not self.config.enabled_platforms['reddit']:
            self._log("Reddit scraping disabled in configuration", "INFO")
            return []
        
        self._log("Starting Reddit scraping...", "INFO")
        result_files = []
        all_reddit_results = []  # Collect all results from all subreddits
        
        # ✅ SIMPLIFIED: Create single reddit folder (like eBay, Facebook, Poshmark)
        reddit_folder = f"{self.config.consolidated_images_folder}/reddit"
        os.makedirs(reddit_folder, exist_ok=True)
        
        # Scrape each configured subreddit but save to same folder
        for subreddit in self.config.reddit_subreddits:
            self._log(f"Scraping Reddit r/{subreddit}...", "INFO")
            
            try:
                # Run Reddit scraper for this subreddit - save to unified reddit folder
                result_file = scrape_reddit_subreddit(
                    subreddit=subreddit,
                    search_query=self.search_query,
                    limit=self.config.reddit_max_results,
                    output_folder=reddit_folder  # ✅ All subreddits save to same folder
                )
                
                if result_file and os.path.exists(result_file):
                    # Load results and add to combined results
                    with open(result_file, 'r', encoding='utf-8') as f:
                        subreddit_results = json.load(f)
                    
                    # Add subreddit info to each result
                    for result in subreddit_results:
                        result['source_subreddit'] = subreddit
                    
                    all_reddit_results.extend(subreddit_results)
                    
                    # Clean up individual subreddit result file
                    try:
                        os.remove(result_file)
                    except:
                        pass
                        
                else:
                    self._log(f"Reddit r/{subreddit} scraping failed", "WARNING")
                    
            except Exception as e:
                self._log(f"Reddit r/{subreddit} error: {e}", "ERROR")
        
        # ✅ Save combined results from all subreddits
        if all_reddit_results:
            session_result_file = self._save_results_to_session(
                all_reddit_results, 
                "Reddit (All Subreddits)", 
                "reddit_results.json"
            )
            if session_result_file:
                result_files.append(session_result_file)
                # ✅ Add single reddit folder to analysis (like other platforms)
                self.all_image_folders.append(reddit_folder)
                self._log(f"Combined Reddit results: {len(all_reddit_results)} posts from {len(self.config.reddit_subreddits)} subreddits", "SUCCESS")
        else:
            self._log("No Reddit results from any subreddit", "WARNING")
        
        return result_files
    
    def run_poshmark_scraper(self):
        """Execute Poshmark scraping."""
        if not self.config.enabled_platforms['poshmark']:
            self._log("Poshmark scraping disabled in configuration", "INFO")
            return None
        
        self._log("Starting Poshmark scraping...", "INFO")
        
        try:
            # Create Poshmark-specific folder
            poshmark_folder = f"{self.config.consolidated_images_folder}/poshmark"
            
            # Run Poshmark scraper
            result_file = scrape_poshmark(
                query=self.search_query,
                max_results=self.config.poshmark_max_results,
                output_folder=poshmark_folder
            )
            
            if result_file and os.path.exists(result_file):
                # Load results and move to session
                with open(result_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                
                session_result_file = self._save_results_to_session(results, "Poshmark", "poshmark_results.json")
                self.all_image_folders.append(poshmark_folder)
                
                # Clean up original file
                try:
                    os.remove(result_file)
                except:
                    pass
                    
                return session_result_file
            else:
                self._log("Poshmark scraping failed - no results", "ERROR")
                return None
                
        except Exception as e:
            self._log(f"Poshmark scraping error: {e}", "ERROR")
            return None
    
    def run_facebook_scraper(self):
        """Execute Facebook Marketplace scraping (optional due to complexity)."""
        if not self.config.enabled_platforms['facebook']:
            self._log("Facebook Marketplace scraping disabled in configuration", "INFO")
            return None
        
        # Check if cookies file exists
        if not os.path.exists(self.config.facebook_cookies_file):
            self._log(f"Facebook cookies file not found: {self.config.facebook_cookies_file}", "WARNING")
            self._log("Skipping Facebook scraping - consider disabling it in config", "WARNING")
            return None
        
        self._log("Starting Facebook Marketplace scraping...", "WARNING")
        self._log("Note: Facebook scraping often fails due to anti-automation measures", "WARNING")
        
        try:
            # Create Facebook-specific folder
            facebook_folder = f"{self.config.consolidated_images_folder}/facebook"
            
            # Load cookies
            with open(self.config.facebook_cookies_file, 'r') as f:
                cookies = json.load(f)
            
            # Run Facebook scraper
            result_file = scrape_facebook_marketplace_with_cookies(
                query=self.search_query,
                location=self.config.facebook_location,
                max_results=self.config.facebook_max_results,
                output_folder=facebook_folder,
                cookies=cookies
            )
            
            if result_file and os.path.exists(result_file):
                # Load results and move to session
                with open(result_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                
                session_result_file = self._save_results_to_session(results, "Facebook", "facebook_results.json")
                self.all_image_folders.append(facebook_folder)
                
                # Clean up original file
                try:
                    os.remove(result_file)
                except:
                    pass
                    
                return session_result_file
            else:
                self._log("Facebook scraping failed (this is common)", "WARNING")
                return None
                
        except Exception as e:
            # More user-friendly error message
            self._log("Facebook scraping blocked by anti-automation measures", "WARNING")
            self._log("This is normal - Facebook actively blocks automated browsing", "INFO")
            self._log("Consider manually searching Facebook Marketplace for better results", "INFO")
            return None
    
    def run_all_scrapers(self):
        """Execute all enabled scrapers in sequence."""
        self._log("Starting comprehensive scraping across all platforms...", "INFO")
        
        # Run each scraper (order matters - start with most reliable)
        if self.config.enabled_platforms.get('reddit', False):
            self.run_reddit_scraper()  # Most reliable - uses API
            time.sleep(2)  # Brief pause between platforms
        
        if self.config.enabled_platforms.get('ebay', False):
            self.run_ebay_scraper()  # Usually reliable
            time.sleep(2)
        
        if self.config.enabled_platforms.get('craigslist', False):
            self.run_craigslist_scraper()  # Moderate reliability
            time.sleep(3)
        
        if self.config.enabled_platforms.get('poshmark', False):
            self.run_poshmark_scraper()  # Can be finicky
            time.sleep(3)
        
        if self.config.enabled_platforms.get('facebook', False):
            self.run_facebook_scraper()  # Most likely to fail
        
        # Log scraping summary
        total_platforms = sum(1 for platform, enabled in self.config.enabled_platforms.items() if enabled)
        successful_platforms = len(self.all_scraped_files)
        
        self._log(f"Scraping phase complete: {successful_platforms}/{total_platforms} platforms successful", "SUCCESS")
        self._log(f"Total image folders created: {len(self.all_image_folders)}", "INFO")
    
    def run_matching_analysis(self):
        """Run AI matching analysis on all scraped images."""
        if not self.matcher:
            self._log("Watch matcher not available - skipping matching analysis", "WARNING")
            return
            
        self._log("Starting AI matching analysis on all scraped images...", "INFO")
        
        # Process each image folder with the watch matcher
        for folder_path in self.all_image_folders:
            if not os.path.exists(folder_path):
                self._log(f"Folder does not exist: {folder_path}", "WARNING")
                continue
            
            # Check if folder has images directly, or in subfolders
            image_files = []
            
            # First, check for images directly in the folder
            try:
                for file in os.listdir(folder_path):
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        image_files.append(os.path.join(folder_path, file))
            except:
                continue
            
            # If no images found directly, check subfolders (Reddit case)
            if not image_files:
                try:
                    for subfolder in os.listdir(folder_path):
                        subfolder_path = os.path.join(folder_path, subfolder)
                        if os.path.isdir(subfolder_path):
                            for file in os.listdir(subfolder_path):
                                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                                    image_files.append(os.path.join(subfolder_path, file))
                            # If we found images in a subfolder, update the folder_path
                            if image_files:
                                folder_path = subfolder_path
                                break
                except:
                    continue
            
            if not image_files:
                self._log(f"No images found in: {folder_path}", "WARNING")
                continue
            
            folder_name = os.path.basename(folder_path)
            self._log(f"Analyzing {len(image_files)} images in {folder_name}...", "INFO")
            
            try:
                # Run batch matching on this folder
                results = self.matcher.batch_match(
                    test_folder=folder_path,
                    threshold=self.config.match_threshold,
                    output_file=f"{self.config.session_folder}/matches/{folder_name}_matches.json"
                )
                
                # Count likely matches found
                likely_matches = [r for r in results if r.get('is_likely_match', False)]
                self.match_results[folder_name] = {
                    'total_images': len(results),
                    'likely_matches': len(likely_matches),
                    'match_details': likely_matches
                }
                
                self._log(f"{folder_name}: {len(likely_matches)} likely matches found out of {len(results)} images", "SUCCESS" if likely_matches else "INFO")
                
            except Exception as e:
                self._log(f"Error analyzing {folder_name}: {e}", "ERROR")
                self.match_results[folder_name] = {'error': str(e)}
    
    def generate_session_summary(self):
        """Generate comprehensive summary of the entire session."""
        self._log("Generating session summary report...", "INFO")
        
        # Calculate overall statistics
        total_images_analyzed = sum(
            result.get('total_images', 0) 
            for result in self.match_results.values() 
            if 'error' not in result
        )
        total_likely_matches = sum(
            result.get('likely_matches', 0) 
            for result in self.match_results.values() 
            if 'error' not in result
        )
        
        # Collect all likely matches across platforms
        all_matches = []
        for platform, result in self.match_results.items():
            if 'match_details' in result:
                for match in result['match_details']:
                    match['platform'] = platform  # Add platform identifier
                    all_matches.append(match)
        
        # Sort matches by confidence score (highest first)
        all_matches.sort(key=lambda x: x.get('best_score', 0), reverse=True)
        
        # Create comprehensive session summary
        session_summary = {
            "session_info": {
                "session_id": self.config.session_id,
                "search_query": self.search_query,
                "timestamp": datetime.now().isoformat(),
                "reference_folder": self.config.reference_folder,
                "match_threshold": self.config.match_threshold
            },
            "scraping_summary": {
                "platforms_attempted": list(self.config.enabled_platforms.keys()),
                "platforms_enabled": [k for k, v in self.config.enabled_platforms.items() if v],
                "successful_scrapes": len(self.all_scraped_files),
                "total_image_folders": len(self.all_image_folders)
            },
            "matching_summary": {
                "total_images_analyzed": total_images_analyzed,
                "total_likely_matches": total_likely_matches,
                "match_rate": f"{(total_likely_matches/total_images_analyzed*100):.1f}%" if total_images_analyzed > 0 else "0%",
                "platform_breakdown": self.match_results
            },
            "top_matches": all_matches[:10],  # Top 10 matches across all platforms
            "session_log": self.session_log,
            "file_paths": {
                "session_folder": self.config.session_folder,
                "image_folders": self.all_image_folders,
                "result_files": self.all_scraped_files
            }
        }
        
        # ✅ Export matched images to web/static/matched/
        try:
            matched_dir = os.path.join("web", "static", "matched")
            os.makedirs(matched_dir, exist_ok=True)
            for match in session_summary["top_matches"]:
                image_path = match.get("image_path")
                if image_path and os.path.exists(image_path):
                    filename = os.path.basename(image_path)
                    dest_path = os.path.join(matched_dir, filename)
                    shutil.copy2(image_path, dest_path)
                    match["filename"] = filename  # Needed for HTML
                    # Update the image_path to point to the web-accessible location
                    match["image_path"] = f"matched/{filename}"  # This is the key change!
        except Exception as e:
            self._log(f"Error exporting matched images: {e}", "ERROR")

        # ✅ Save to web/static/results.json for Flask app
        try:
            with open("web/static/results.json", "w", encoding="utf-8") as f:
                json.dump(session_summary, f, indent=2, ensure_ascii=False)
            self._log("Saved top matches to: web/static/results.json", "SUCCESS")
        except Exception as e:
            self._log(f"Failed to write web results.json: {e}", "ERROR")
        
        # Save session summary to file
        try:
            with open(self.config.results_summary_file, 'w', encoding='utf-8') as f:
                json.dump(session_summary, f, indent=2, ensure_ascii=False)
            
            self._log(f"Session summary saved: {self.config.results_summary_file}", "SUCCESS")
            
        except Exception as e:
            self._log(f"Error saving session summary: {e}", "ERROR")
        
        return session_summary
    
    def print_final_report(self):
        """Print a formatted final report to console."""
        print(f"\n{'='*80}")
        print(f"🔍 WATCH FINDER SESSION COMPLETE - {self.config.session_id}")
        print(f"{'='*80}")
        
        print(f"\n📋 SEARCH DETAILS:")
        print(f"   Query: '{self.search_query}'")
        print(f"   Reference: {self.config.reference_folder}")
        print(f"   Threshold: {self.config.match_threshold}")
        
        print(f"\n🌐 SCRAPING RESULTS:")
        for platform, enabled in self.config.enabled_platforms.items():
            status = "✅ Enabled" if enabled else "❌ Disabled"
            print(f"   {platform.capitalize()}: {status}")
        
        print(f"\n🤖 MATCHING ANALYSIS:")
        total_matches = sum(
            result.get('likely_matches', 0) 
            for result in self.match_results.values() 
            if 'error' not in result
        )
        
        if total_matches > 0:
            print(f"   🎯 {total_matches} LIKELY MATCHES FOUND!")
            print(f"\n   Platform Breakdown:")
            for platform, result in self.match_results.items():
                if 'likely_matches' in result:
                    matches = result['likely_matches']
                    total = result['total_images']
                    print(f"      {platform}: {matches}/{total} matches")
        else:
            print(f"   😞 No likely matches found")
            print(f"   Consider lowering the threshold or expanding search terms")
        
        print(f"\n📁 SESSION FILES:")
        print(f"   Session folder: {self.config.session_folder}")
        print(f"   Summary report: {self.config.results_summary_file}")
        
        if total_matches > 0:
            print(f"\n🎯 NEXT STEPS:")
            print(f"   1. Review matches in: {self.config.session_folder}/matches/")
            print(f"   2. Check images in: {self.config.consolidated_images_folder}/")
            print(f"   3. Use web dashboard for detailed review")
        
        print(f"\n{'='*80}")

def main():
    """Main function that handles command-line execution of the watch finder."""
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Complete Watch Finder - Scrape and Match Across All Platforms")
    
    # Required argument: what to search for
    parser.add_argument("search_query", help="Search term for the watch (e.g., 'patek philippe nautilus')")
    
    # Optional arguments for customization
    parser.add_argument("--reference-folder", default="lost_watch_images/", 
                       help="Folder containing reference images of the lost watch")
    parser.add_argument("--threshold", type=float, default=0.80,
                       help="Matching threshold (0.0 to 1.0, higher = more strict)")
    parser.add_argument('--enable-facebook', action='store_true', help='Enable Facebook scraping')
    parser.add_argument('--enable-reddit', action='store_true', help='Enable Reddit scraping')
    parser.add_argument('--disable-ebay', action='store_true', help='Disable eBay scraping')
    parser.add_argument('--disable-craigslist', action='store_true', help='Disable Craigslist scraping')
    parser.add_argument('--disable-poshmark', action='store_true', help='Disable Poshmark scraping')
    parser.add_argument("--max-results", type=int, default=20, help="Maximum results per platform")
    
    # Parse command-line arguments
    args = parser.parse_args()
    
    # Create configuration object
    config = WatchFinderConfig()

    # Apply command-line overrides to configuration
    config.reference_folder = args.reference_folder
    config.match_threshold = args.threshold
    # Force-enable Reddit and Facebook in the Flask version
    config.enabled_platforms['reddit'] = True
    config.enabled_platforms['facebook'] = True
    
    # Apply platform enable/disable flags
    if args.disable_ebay:
        config.enabled_platforms['ebay'] = False
    if args.disable_craigslist:
        config.enabled_platforms['craigslist'] = False
    if args.enable_reddit:
        config.enabled_platforms['reddit'] = True
    if args.disable_poshmark:
        config.enabled_platforms['poshmark'] = False
    if args.enable_facebook:
        config.enabled_platforms['facebook'] = True
    
    # Apply max results setting to all platforms
    if args.max_results != 20:
        config.ebay_max_results = args.max_results
        config.craigslist_max_results = max(10, args.max_results - 5)  # Slightly fewer for Craigslist
        config.reddit_max_results = max(5, args.max_results - 10)  # Fewer for Reddit
        config.poshmark_max_results = args.max_results
        config.facebook_max_results = max(5, args.max_results - 12)  # Much fewer for Facebook
    
    # Validate reference folder exists (only if WatchMatcher will be used)
    if os.path.exists("match_watch.py"):
        if not os.path.exists(config.reference_folder):
            print(f"❌ Error: Reference folder does not exist: {config.reference_folder}")
            print("Please create this folder and add photos of the lost watch.")
            sys.exit(1)
        
        # Check if reference folder has images
        reference_images = [f for f in os.listdir(config.reference_folder) 
                           if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        if not reference_images:
            print(f"❌ Error: No images found in reference folder: {config.reference_folder}")
            print("Please add photos of the lost watch to this folder.")
            sys.exit(1)
        
        print(f"✅ Found {len(reference_images)} reference images in {config.reference_folder}")
    else:
        print("⚠️  match_watch.py not found - will run scraping only (no AI matching)")
    
    # Create orchestrator and run complete workflow
    orchestrator = WatchFinderOrchestrator(config, args.search_query)
    
    try:
        # Step 1: Run all scrapers
        orchestrator.run_all_scrapers()
        
        # Step 2: Run AI matching analysis (if available)
        if orchestrator.matcher:
            orchestrator.run_matching_analysis()
        
        # Step 3: Generate comprehensive summary
        orchestrator.generate_session_summary()
        
        # Step 4: Print final report
        orchestrator.print_final_report()
        
    except KeyboardInterrupt:
        orchestrator._log("Session interrupted by user", "WARNING")
        print("\n⚠️  Session interrupted. Partial results may be available in session folder.")
    except Exception as e:
        orchestrator._log(f"Unexpected error: {e}", "ERROR")
        print(f"\n❌ Session failed with error: {e}")
        print("Check session logs for details.")   


# Entry point for script execution
if __name__ == "__main__":
    main()