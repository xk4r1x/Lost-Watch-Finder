# match_watch.py
# Author: Makari Green
# Purpose: Enhanced watch matching with batch processing and caching for marketplace monitoring

import os  # Operating system interface for file/folder operations
import torch  # PyTorch library for tensor operations and deep learning
import clip  # OpenAI's CLIP model for vision-language understanding
from PIL import Image  # Python Imaging Library for image processing
from tqdm import tqdm  # Progress bar library to show processing status
import argparse  # Command-line argument parsing library
import json  # JSON serialization for saving/loading structured data
import pickle  # Python object serialization for caching embeddings
from datetime import datetime  # Date and time utilities for timestamps
from typing import List, Tuple, Dict  # Type hints for better code documentation

class WatchMatcher:
    def __init__(self, reference_folder: str = "lost_watch_images/", cache_file: str = "reference_embeddings.pkl"):
        """Initialize the watch matcher with caching capabilities."""
        # Automatically detect if GPU is available, otherwise use CPU for processing
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Load the CLIP model and its preprocessing pipeline onto the selected device
        self.model, self.preprocess = clip.load("ViT-B/32", device=self.device)
        
        # Store the path to the folder containing reference watch images
        self.reference_folder = reference_folder
        
        # Store the filename for caching computed embeddings to avoid recomputation
        self.cache_file = cache_file
        
        # Dictionary to store precomputed embeddings for reference images
        self.reference_embeddings = {}
        
        # Load existing cache or create new embeddings for reference images
        self.load_or_create_cache()
    
    def load_or_create_cache(self):
        """Load cached reference embeddings or create them if they don't exist."""
        # Check if the cache file already exists on disk
        if os.path.exists(self.cache_file):
            # Open the cache file in binary read mode
            with open(self.cache_file, 'rb') as f:
                # Load the pickled embeddings dictionary from file
                self.reference_embeddings = pickle.load(f)
            # Print status message showing how many embeddings were loaded
            print(f"Loaded {len(self.reference_embeddings)} cached reference embeddings.")
        else:
            # If no cache exists, create new embeddings for all reference images
            self.create_reference_cache()
    
    def create_reference_cache(self):
        """Create and save embeddings for all reference images."""
        # Print status message indicating cache creation has started
        print("Creating reference embeddings cache...")
        
        # Loop through every file in the reference folder
        for filename in os.listdir(self.reference_folder):
            # Check if the file has a valid image extension (case-insensitive)
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                try:
                    # Create the full path to the image file
                    img_path = os.path.join(self.reference_folder, filename)
                    
                    # Load the image, preprocess it, add batch dimension, and move to device
                    image = self.preprocess(Image.open(img_path)).unsqueeze(0).to(self.device)
                    
                    # Disable gradient computation for inference (saves memory and speeds up)
                    with torch.no_grad():
                        # Generate the CLIP embedding vector for this reference image
                        embedding = self.model.encode_image(image)
                    
                    # Store the embedding on CPU to save GPU memory (move from device to CPU)
                    self.reference_embeddings[filename] = embedding.cpu()
                    
                except Exception as e:
                    # Print error message if image processing fails, but continue with other images
                    print(f"Error processing {filename}: {e}")
        
        # Save all computed embeddings to disk as a pickle file for future use
        with open(self.cache_file, 'wb') as f:
            pickle.dump(self.reference_embeddings, f)
        
        # Print confirmation message with count of successfully cached embeddings
        print(f"Cached {len(self.reference_embeddings)} reference embeddings.")
    
    def match_single_image(self, test_image_path: str, threshold: float = 0.80) -> Dict:
        """Match a single test image against reference images."""
        try:
            # Load and preprocess the test image, add batch dimension, move to processing device
            test_image = self.preprocess(Image.open(test_image_path)).unsqueeze(0).to(self.device)
            
            # Generate embedding for the test image without computing gradients
            with torch.no_grad():
                test_embedding = self.model.encode_image(test_image)
            
            # Initialize variables to track the best matching reference image
            best_score = -1.0  # Start with lowest possible similarity score
            best_match = None  # Will store filename of best matching reference image
            all_scores = {}    # Dictionary to store similarity scores for all reference images
            
            # Compare test image embedding with each reference image embedding
            for filename, ref_embedding in self.reference_embeddings.items():
                # Move reference embedding back to processing device (GPU/CPU)
                ref_embedding = ref_embedding.to(self.device)
                
                # Calculate cosine similarity between test and reference embeddings
                similarity = torch.cosine_similarity(test_embedding, ref_embedding).item()
                
                # Store the similarity score for this reference image
                all_scores[filename] = similarity
                
                # Update best match if this similarity score is higher than previous best
                if similarity > best_score:
                    best_score = similarity      # Update highest similarity score
                    best_match = filename        # Update filename of best matching image
            
            # Return comprehensive results dictionary with all matching information
            return {
                'test_image': os.path.basename(test_image_path),        # Name of test image file
                'best_match': best_match,                               # Filename of best matching reference
                'best_score': best_score,                               # Highest similarity score achieved
                'is_likely_match': best_score >= threshold,             # Boolean: does score exceed threshold?
                'confidence_level': self.get_confidence_level(best_score), # Human-readable confidence description
                'all_scores': all_scores,                               # Dictionary of all similarity scores
                'timestamp': datetime.now().isoformat()                # ISO format timestamp of when matching occurred
            }
            
        except Exception as e:
            # Return error information if image processing or matching fails
            return {
                'test_image': os.path.basename(test_image_path),  # Test image filename for identification
                'error': str(e),                                  # Error message for debugging
                'timestamp': datetime.now().isoformat()          # Timestamp when error occurred
            }
    
    def batch_match(self, test_folder: str, threshold: float = 0.80, output_file: str = None) -> List[Dict]:
        """Process multiple test images and return results."""
        results = []  # List to store results from all processed images
        
        # Create list of all valid image files in the test folder
        test_images = [f for f in os.listdir(test_folder) 
                      if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))]
        
        # Process each test image with progress bar showing completion status
        for filename in tqdm(test_images, desc="Processing test images"):
            # Create full path to the current test image
            test_path = os.path.join(test_folder, filename)
            
            # Match this test image against all reference images
            result = self.match_single_image(test_path, threshold)
            
            # Add the matching result to our results list
            results.append(result)
        
        # Save results to JSON file if output filename was specified
        if output_file:
            # Open output file in write mode and save results as formatted JSON
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)  # indent=2 makes JSON human-readable
            # Print confirmation message showing where results were saved
            print(f"Results saved to {output_file}")
        
        # Return the complete list of matching results
        return results
    
    def get_confidence_level(self, score: float) -> str:
        """Convert similarity score to human-readable confidence level."""
        # Return confidence description based on similarity score ranges
        if score > 0.90:          # Very high similarity indicates strong match
            return "Very Likely Match"
        elif score > 0.80:        # High similarity indicates possible match worth investigating
            return "Possible Match"
        elif score > 0.70:        # Moderate similarity indicates weak match, manual check recommended
            return "Weak Match"
        else:                     # Low similarity indicates no meaningful match
            return "No Match"
    
    def print_summary(self, results: List[Dict]):
        """Print a summary of batch matching results."""
        # Filter results to find only those marked as likely matches
        likely_matches = [r for r in results if r.get('is_likely_match', False)]
        
        # Print formatted header for the summary section
        print(f"\n{'='*50}")
        print(f"BATCH MATCHING SUMMARY")
        print(f"{'='*50}")
        
        # Print total statistics
        print(f"Total images processed: {len(results)}")        # Show total number of images processed
        print(f"Likely matches found: {len(likely_matches)}")   # Show how many exceeded the threshold
        
        # If any likely matches were found, display them in detail
        if likely_matches:
            print(f"\nLIKELY MATCHES:")
            # Loop through each likely match and display key information
            for match in likely_matches:
                # Format: test_image -> reference_match (similarity_score)
                print(f"  • {match['test_image']} -> {match['best_match']} (Score: {match['best_score']:.4f})")

# Main program execution block - only runs when script is called directly (not imported)
if __name__ == "__main__":
    # Create argument parser to handle command-line options
    parser = argparse.ArgumentParser(description="Enhanced watch matching with batch processing")
    
    # Add argument for selecting processing mode (single image vs batch of images)
    parser.add_argument("--mode", choices=['single', 'batch'], default='single', 
                       help="Processing mode: single image or batch processing")
    
    # Arguments specific to single image processing mode
    parser.add_argument("--test_image", help="Path to single test image")
    
    # Arguments specific to batch processing mode
    parser.add_argument("--test_folder", help="Path to folder containing test images")
    parser.add_argument("--output", help="Output file for batch results (JSON)")
    
    # Arguments that apply to both processing modes
    parser.add_argument("--reference_folder", default="lost_watch_images/", 
                       help="Path to reference images folder")
    parser.add_argument("--threshold", type=float, default=0.80, 
                       help="Similarity threshold for matches")
    
    # Parse all command-line arguments provided by user
    args = parser.parse_args()
    
    # Create WatchMatcher instance with specified reference folder
    matcher = WatchMatcher(reference_folder=args.reference_folder)
    
    # Handle single image processing mode
    if args.mode == 'single':
        # Check if required test_image argument was provided
        if not args.test_image:
            print("Error: --test_image required for single mode")
            exit(1)  # Exit with error code 1
        
        # Process the single test image and get matching results
        result = matcher.match_single_image(args.test_image, args.threshold)
        
        # Check if an error occurred during processing
        if 'error' in result:
            print(f"Error: {result['error']}")  # Display error message
        else:
            # Display successful matching results in formatted output
            print(f"\nTest Image: {result['test_image']}")              # Show test image filename
            print(f"Best Match: {result['best_match']}")                # Show best matching reference image
            print(f"Similarity Score: {result['best_score']:.4f}")      # Show similarity score to 4 decimal places
            print(f"Confidence: {result['confidence_level']}")          # Show human-readable confidence level
    
    # Handle batch processing mode
    elif args.mode == 'batch':
        # Check if required test_folder argument was provided
        if not args.test_folder:
            print("Error: --test_folder required for batch mode")
            exit(1)  # Exit with error code 1
        
        # Process all images in the test folder and get results list
        results = matcher.batch_match(args.test_folder, args.threshold, args.output)
        
        # Print formatted summary of batch processing results
        matcher.print_summary(results)