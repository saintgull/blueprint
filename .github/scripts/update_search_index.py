#!/usr/bin/env python3
"""
Update search index for The Blueprint Magazine.
Checks sitemap for changes, fetches new posts, and builds encrypted ChromaDB index.
"""

import os
import json
import hashlib
import requests
import xmltodict
from pathlib import Path
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

import chromadb
from chromadb.utils.embedding_functions import ChromaBm25EmbeddingFunction
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Configuration
GHOST_API_URL = os.environ.get('GHOST_API_URL', 'https://the-blueprint.ghost.io')
GHOST_CONTENT_API_KEY = os.environ.get('GHOST_CONTENT_API_KEY', '')
INDEX_ENCRYPTION_KEY = os.environ.get('INDEX_ENCRYPTION_KEY', '')
SITEMAP_URL = f"{GHOST_API_URL}/sitemap-posts.xml"

# Directories
CACHE_DIR = Path('cache')
INDEX_DIR = Path('index')
CACHE_DIR.mkdir(exist_ok=True)
INDEX_DIR.mkdir(exist_ok=True)

SITEMAP_CACHE = CACHE_DIR / 'sitemap_hash.txt'
INDEXED_POSTS_CACHE = CACHE_DIR / 'indexed_posts.json'
CHROMA_DB_PATH = INDEX_DIR / 'chroma_db'
ENCRYPTED_INDEX_PATH = INDEX_DIR / 'search_index.enc'


def get_encryption_key():
    """Get or derive 32-byte encryption key from environment."""
    key_str = INDEX_ENCRYPTION_KEY
    if not key_str:
        raise ValueError("INDEX_ENCRYPTION_KEY environment variable not set")
    
    # Derive 32-byte key using SHA-256
    return hashlib.sha256(key_str.encode()).digest()


def encrypt_directory(input_dir, output_path, key):
    """Encrypt entire directory into a single file."""
    import tarfile
    import io
    
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    
    # Create tar archive in memory
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        tar.add(input_dir, arcname='chroma_db')
    
    plaintext = tar_buffer.getvalue()
    
    # Generate nonce
    nonce = os.urandom(12)
    
    # Encrypt
    cipher = ChaCha20Poly1305(key)
    ciphertext = cipher.encrypt(nonce, plaintext, None)
    
    # Write: nonce (12) + ciphertext (includes 16-byte tag)
    with open(output_path, 'wb') as f:
        f.write(nonce + ciphertext)
    
    print(f"✓ Encrypted index saved to {output_path}")


def decrypt_directory(input_path, output_dir, key):
    """Decrypt file and extract directory."""
    import tarfile
    import io
    
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    
    # Read encrypted file
    with open(input_path, 'rb') as f:
        data = f.read()
    
    # Extract nonce and ciphertext
    nonce = data[:12]
    ciphertext = data[12:]
    
    # Decrypt (validates tag automatically)
    cipher = ChaCha20Poly1305(key)
    plaintext = cipher.decrypt(nonce, ciphertext, None)
    
    # Extract tar archive
    tar_buffer = io.BytesIO(plaintext)
    with tarfile.open(fileobj=tar_buffer, mode='r:gz') as tar:
        tar.extractall(path=output_dir.parent)
    
    print(f"✓ Decrypted index to {output_dir}")


def fetch_sitemap():
    """Fetch and parse sitemap XML."""
    try:
        response = requests.get(SITEMAP_URL, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"✗ Error fetching sitemap: {e}")
        return None


def get_sitemap_hash(sitemap_content):
    """Calculate hash of sitemap content."""
    return hashlib.sha256(sitemap_content.encode()).hexdigest()


def parse_sitemap(sitemap_content):
    """Parse sitemap XML and extract post URLs."""
    try:
        sitemap_dict = xmltodict.parse(sitemap_content)
        urls = []
        
        if 'urlset' in sitemap_dict and 'url' in sitemap_dict['urlset']:
            url_entries = sitemap_dict['urlset']['url']
            if not isinstance(url_entries, list):
                url_entries = [url_entries]
            
            for entry in url_entries:
                if 'loc' in entry:
                    urls.append(entry['loc'])
        
        return urls
    except Exception as e:
        print(f"✗ Error parsing sitemap: {e}")
        return []


def load_indexed_posts():
    """Load list of already indexed post URLs."""
    if INDEXED_POSTS_CACHE.exists():
        with open(INDEXED_POSTS_CACHE, 'r') as f:
            return set(json.load(f))
    return set()


def save_indexed_posts(post_urls):
    """Save list of indexed post URLs."""
    with open(INDEXED_POSTS_CACHE, 'w') as f:
        json.dump(list(post_urls), f, indent=2)


def fetch_post_content(post_url):
    """Fetch post content using Ghost Content API."""
    try:
        # Extract slug from URL
        slug = post_url.rstrip('/').split('/')[-1]
        
        # Fetch post via Content API
        api_url = f"{GHOST_API_URL}/ghost/api/content/posts/slug/{slug}/"
        params = {
            'key': GHOST_CONTENT_API_KEY,
            'formats': 'plaintext'
        }
        
        response = requests.get(api_url, params=params, timeout=30)
        response.raise_for_status()
        
        post_data = response.json()['posts'][0]
        
        return {
            'url': post_url,
            'slug': slug,
            'title': post_data.get('title', ''),
            'excerpt': post_data.get('excerpt', ''),
            'plaintext': post_data.get('plaintext', ''),
            'published_at': post_data.get('published_at', ''),
            'tags': [tag['name'] for tag in post_data.get('tags', [])],
            'feature_image': post_data.get('feature_image', ''),
        }
    except Exception as e:
        print(f"✗ Error fetching post {post_url}: {e}")
        return None


def initialize_chromadb():
    """Initialize ChromaDB with BM25 and semantic embeddings."""
    
    # Initialize BM25 for keyword search
    bm25_ef = ChromaBm25EmbeddingFunction(
        k=1.2,
        b=0.75,
        avg_doc_length=4000.0,  # Average article length in words
        token_max_length=50
    )
    
    # Initialize semantic embeddings
    semantic_ef = SentenceTransformerEmbeddingFunction(
        model_name="Qwen/Qwen3-Embedding-0.6B",
        device="cpu",
        normalize_embeddings=False
    )
    
    # Create persistent client
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    
    # Get or create collections
    try:
        bm25_collection = client.get_collection(
            name="posts_bm25",
            embedding_function=bm25_ef
        )
        semantic_collection = client.get_collection(
            name="posts_semantic",
            embedding_function=semantic_ef
        )
        print("✓ Loaded existing ChromaDB collections")
    except:
        bm25_collection = client.create_collection(
            name="posts_bm25",
            embedding_function=bm25_ef
        )
        semantic_collection = client.create_collection(
            name="posts_semantic",
            embedding_function=semantic_ef
        )
        print("✓ Created new ChromaDB collections")
    
    return client, bm25_collection, semantic_collection


def add_post_to_index(post_data, bm25_collection, semantic_collection):
    """Add a post to both ChromaDB collections."""
    
    # Prepare document text (combine title, excerpt, and content)
    doc_text = f"{post_data['title']}\n\n{post_data['excerpt']}\n\n{post_data['plaintext']}"
    
    # Prepare metadata
    metadata = {
        'url': post_data['url'],
        'title': post_data['title'],
        'excerpt': post_data['excerpt'],
        'published_at': post_data['published_at'],
        'tags': ','.join(post_data['tags']),
        'feature_image': post_data.get('feature_image', ''),
    }
    
    # Add to BM25 collection
    try:
        bm25_collection.add(
            documents=[doc_text],
            metadatas=[metadata],
            ids=[post_data['slug']]
        )
        print(f"  ✓ Added to BM25 index: {post_data['title']}")
    except Exception as e:
        print(f"  ✗ Error adding to BM25: {e}")
    
    # Add to semantic collection
    try:
        semantic_collection.add(
            documents=[doc_text],
            metadatas=[metadata],
            ids=[post_data['slug']]
        )
        print(f"  ✓ Added to semantic index: {post_data['title']}")
    except Exception as e:
        print(f"  ✗ Error adding to semantic: {e}")


def main():
    """Main execution flow."""
    print("="*60)
    print("Blueprint Magazine - Search Index Updater")
    print("="*60)
    
    # Validate environment variables
    if not GHOST_CONTENT_API_KEY:
        print("✗ Error: GHOST_CONTENT_API_KEY not set")
        return
    
    if not INDEX_ENCRYPTION_KEY:
        print("✗ Error: INDEX_ENCRYPTION_KEY not set")
        return
    
    print(f"\n📡 Fetching sitemap from {SITEMAP_URL}")
    
    # Fetch current sitemap
    sitemap_content = fetch_sitemap()
    if not sitemap_content:
        print("✗ Failed to fetch sitemap")
        return
    
    current_hash = get_sitemap_hash(sitemap_content)
    print(f"✓ Sitemap hash: {current_hash[:16]}...")
    
    # Check if sitemap changed
    sitemap_changed = True
    if SITEMAP_CACHE.exists():
        with open(SITEMAP_CACHE, 'r') as f:
            cached_hash = f.read().strip()
        
        if cached_hash == current_hash:
            print("✓ Sitemap unchanged - no updates needed")
            sitemap_changed = False
        else:
            print("📝 Sitemap changed - checking for new posts")
    else:
        print("📝 No cached sitemap - indexing all posts")
    
    # Parse sitemap
    post_urls = parse_sitemap(sitemap_content)
    print(f"✓ Found {len(post_urls)} posts in sitemap")
    
    # Load already indexed posts
    indexed_posts = load_indexed_posts()
    print(f"✓ Already indexed: {len(indexed_posts)} posts")
    
    # Find new posts
    new_posts = [url for url in post_urls if url not in indexed_posts]
    
    if not new_posts:
        print("✓ No new posts to index")
        # Update sitemap hash even if no new posts
        with open(SITEMAP_CACHE, 'w') as f:
            f.write(current_hash)
        return
    
    print(f"\n📚 Found {len(new_posts)} new post(s) to index")
    
    # Initialize ChromaDB
    print("\n🔧 Initializing ChromaDB...")
    client, bm25_collection, semantic_collection = initialize_chromadb()
    
    # Process new posts
    print("\n📥 Fetching and indexing new posts...")
    successfully_indexed = []
    
    for i, post_url in enumerate(new_posts, 1):
        print(f"\n[{i}/{len(new_posts)}] Processing: {post_url}")
        
        # Fetch post content
        post_data = fetch_post_content(post_url)
        if not post_data:
            continue
        
        # Add to index
        add_post_to_index(post_data, bm25_collection, semantic_collection)
        successfully_indexed.append(post_url)
    
    # Update indexed posts list
    if successfully_indexed:
        indexed_posts.update(successfully_indexed)
        save_indexed_posts(indexed_posts)
        print(f"\n✓ Successfully indexed {len(successfully_indexed)} new post(s)")
    
    # Encrypt the database
    print("\n🔐 Encrypting index...")
    try:
        encryption_key = get_encryption_key()
        encrypt_directory(CHROMA_DB_PATH, ENCRYPTED_INDEX_PATH, encryption_key)
        
        # Show encrypted file size
        file_size = ENCRYPTED_INDEX_PATH.stat().st_size / (1024 * 1024)
        print(f"✓ Encrypted index size: {file_size:.2f} MB")
    except Exception as e:
        print(f"✗ Error encrypting index: {e}")
        return
    
    # Update sitemap hash
    with open(SITEMAP_CACHE, 'w') as f:
        f.write(current_hash)
    
    print("\n" + "="*60)
    print("✅ Index update complete!")
    print("="*60)
    print(f"Total posts indexed: {len(indexed_posts)}")
    print(f"New posts added: {len(successfully_indexed)}")
    print(f"Encrypted index: {ENCRYPTED_INDEX_PATH}")
    print("="*60)


if __name__ == '__main__':
    main()
