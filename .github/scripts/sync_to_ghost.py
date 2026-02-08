#!/usr/bin/env python3
"""
Sync Markdown files from _draft to Ghost CMS.
Uses Ghost Admin API to create posts with specific tags and visibility settings.
"""

import os
import re
import jwt
import yaml
import requests
from pathlib import Path
from datetime import datetime as dt
from datetime import timedelta

# Ghost API configuration from environment variables
GHOST_API_URL = os.environ.get('GHOST_API_URL', '')  # e.g., https://your-site.ghost.io
GHOST_ADMIN_API_KEY = os.environ.get('GHOST_ADMIN_API_KEY', '')


def extract_frontmatter(content):
    """Extract YAML frontmatter from markdown content."""
    frontmatter_pattern = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
    match = frontmatter_pattern.match(content)
    
    if match:
        frontmatter_text = match.group(1)
        remaining_content = content[match.end():]
        try:
            metadata = yaml.safe_load(frontmatter_text)
            return metadata, remaining_content
        except yaml.YAMLError:
            return {}, content
    
    return {}, content


def remove_text_before_first_header(content):
    """Remove all text before the first header (# or ##, etc.)."""
    header_pattern = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
    match = header_pattern.search(content)
    
    if match:
        return content[match.start():]
    
    return content


def generate_ghost_token(api_key):
    """Generate JWT token for Ghost Admin API authentication."""
    # Split the key into ID and SECRET
    key_id, key_secret = api_key.split(':')
    
    # Prepare header and payload
    iat = int(dt.now().timestamp())
    
    header = {'alg': 'HS256', 'typ': 'JWT', 'kid': key_id}
    payload = {
        'iat': iat,
        'exp': iat + 5 * 60,  # Token expires in 5 minutes
        'aud': '/admin/'
    }
    
    # Create token
    token = jwt.encode(payload, bytes.fromhex(key_secret), algorithm='HS256', headers=header)
    
    return token


def create_ghost_post(api_url, token, title, markdown_content, metadata):
    """Create a new post in Ghost CMS."""
    
    # Prepare the post data
    post_data = {
        'posts': [{
            'title': title,
            'mobiledoc': convert_markdown_to_mobiledoc(markdown_content),
            'status': 'published',  # Set as published
            'visibility': 'public',  # Publicly accessible
            'tags': ['type-field-trip'],  # Add the required tag
        }]
    }
    
    # Add optional metadata
    if 'author' in metadata:
        # Note: Ghost will use the authenticated user as author by default
        # To set a specific author, you'd need to query authors first
        pass
    
    if 'date' in metadata:
        try:
            # Parse and format the date
            if isinstance(metadata['date'], str):
                post_date = dt.fromisoformat(str(metadata['date']))
            else:
                post_date = metadata['date']
            post_data['posts'][0]['published_at'] = post_date.isoformat()
        except:
            pass
    
    if 'tagline' in metadata:
        post_data['posts'][0]['custom_excerpt'] = metadata['tagline']
    elif 'description' in metadata:
        post_data['posts'][0]['custom_excerpt'] = metadata['description']
    
    if 'featured' in metadata and metadata['featured']:
        post_data['posts'][0]['featured'] = True
    
    # Prepare headers
    headers = {
        'Authorization': f'Ghost {token}',
        'Content-Type': 'application/json',
        'Accept-Version': 'v5.0'
    }
    
    # Make the API request
    endpoint = f"{api_url.rstrip('/')}/ghost/api/admin/posts/"
    
    try:
        response = requests.post(endpoint, json=post_data, headers=headers)
        response.raise_for_status()
        
        post = response.json()['posts'][0]
        print(f"✓ Created Ghost post: {post['title']} (ID: {post['id']})")
        print(f"  URL: {post['url']}")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to create Ghost post: {e}")
        if hasattr(e.response, 'text'):
            print(f"  Response: {e.response.text}")
        return False


def convert_markdown_to_mobiledoc(markdown_content):
    """
    Convert Markdown to Ghost's Mobiledoc format.
    Ghost's Mobiledoc format supports markdown cards.
    """
    
    # Create a simple Mobiledoc structure with a markdown card
    mobiledoc = {
        "version": "0.3.1",
        "atoms": [],
        "cards": [
            ["markdown", {"markdown": markdown_content}]
        ],
        "markups": [],
        "sections": [
            [10, 0]  # Card section referencing the first card (index 0)
        ],
        "ghostVersion": "4.0"
    }
    
    return mobiledoc


def process_markdown_file(file_path, api_url, token):
    """Process a single markdown file and sync to Ghost."""
    print(f"\nProcessing: {file_path}")
    
    # Read markdown file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract frontmatter
    metadata, md_content = extract_frontmatter(content)
    
    # Remove text before first header
    md_content = remove_text_before_first_header(md_content)
    
    # Extract title from metadata or first h1
    title = metadata.get('title', '')
    if not title:
        h1_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1)
        else:
            title = Path(file_path).stem.replace('-', ' ').title()
    
    # Create post in Ghost
    success = create_ghost_post(api_url, token, title, md_content, metadata)
    
    return success


def main():
    """Main sync process."""
    # Validate environment variables
    if not GHOST_API_URL:
        print("Error: GHOST_API_URL environment variable not set")
        print("Please set it to your Ghost site URL (e.g., https://your-site.ghost.io)")
        return
    
    if not GHOST_ADMIN_API_KEY:
        print("Error: GHOST_ADMIN_API_KEY environment variable not set")
        print("Please set your Ghost Admin API key in repository secrets")
        return
    
    print(f"Ghost API URL: {GHOST_API_URL}")
    
    # Generate authentication token
    try:
        token = generate_ghost_token(GHOST_ADMIN_API_KEY)
        print("✓ Generated authentication token")
    except Exception as e:
        print(f"✗ Failed to generate token: {e}")
        return
    
    # Define draft directory
    draft_dir = Path('_draft')
    
    if not draft_dir.exists():
        print(f"Draft directory '{draft_dir}' does not exist.")
        return
    
    # Find all markdown files
    md_files = list(draft_dir.glob('*.md'))
    
    if not md_files:
        print("No markdown files found in _draft directory.")
        return
    
    print(f"\nFound {len(md_files)} markdown file(s) to sync to Ghost.")
    
    # Process each file
    success_count = 0
    for md_file in md_files:
        try:
            if process_markdown_file(md_file, GHOST_API_URL, token):
                success_count += 1
        except Exception as e:
            print(f"✗ Error processing {md_file}: {e}")
    
    print(f"\n{'='*60}")
    print(f"Sync complete! Successfully synced {success_count}/{len(md_files)} post(s) to Ghost.")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
