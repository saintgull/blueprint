#!/usr/bin/env python3
"""
Convert Markdown files from _draft to HTML in post/ directory.
Uses the same CSS styling as index.html.
Removes text before first header (except metadata).
Deletes converted Markdown files.
"""

import os
import re
import json
import markdown
import yaml
from pathlib import Path
from datetime import datetime

# CSS extracted from index.html
CSS_TEMPLATE = """        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Montserrat', sans-serif;
            background-color: #1237b2;
            color: #333;
            line-height: 1.6;
            overflow-x: hidden;
        }
        
        /* Dotted grid background */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: radial-gradient(circle, rgba(255, 255, 255, 0.4) 1px, transparent 1px);
            background-size: 20px 20px;
            z-index: -1;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        
        header {
            text-align: center;
            margin-bottom: 60px;
            padding: 60px 0;
        }
        
        h1 {
            font-family: 'Libre Baskerville', serif;
            font-size: 4rem;
            color: white;
            font-weight: 700;
            margin-bottom: 16px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
        }
        
        .tagline {
            font-family: 'Libre Baskerville', serif;
            font-size: 1.8rem;
            color: white;
            font-weight: 400;
            text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2);
            line-height: 1.4;
        }
        
        .content-box {
            background-color: white;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        h2 {
            font-family: 'Libre Baskerville', serif;
            font-size: 2rem;
            margin-bottom: 20px;
            color: #1237b2;
        }
        
        h3 {
            font-family: 'Montserrat', sans-serif;
            font-size: 1.3rem;
            font-weight: 600;
            margin-top: 24px;
            margin-bottom: 12px;
            color: #333;
        }
        
        p {
            font-size: 1rem;
            margin-bottom: 16px;
            font-weight: 400;
        }
        
        .highlight-box {
            background-color: #f0f4ff;
            padding: 30px;
            margin: 20px 0;
            position: relative;
        }
        
        .highlight-box::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background-color: #1237b2;
        }
        
        .cta-section {
            background-color: white;
            padding: 60px 40px;
            text-align: center;
            margin-top: 40px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .cta-button {
            display: inline-block;
            background-color: #1237b2;
            color: white;
            padding: 16px 32px;
            text-decoration: none;
            font-weight: 600;
            font-size: 1.1rem;
            margin: 10px;
            transition: background-color 0.3s ease;
        }
        
        .cta-button:hover {
            background-color: #0e2a7e;
        }
        
        ul {
            margin-left: 20px;
            margin-bottom: 16px;
        }
        
        li {
            margin-bottom: 8px;
        }
        
        nav {
            background-color: rgba(18, 55, 178, 0.6);
            padding: 20px 0;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 100;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }
        
        nav .nav-container {
            max-width: 900px;
            margin: 0 auto;
            padding: 0 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        nav a {
            font-family: 'Libre Baskerville', serif;
            color: white;
            text-decoration: none;
            font-weight: 400;
            margin: 0 20px;
            transition: opacity 0.3s ease;
            font-size: 1.1rem;
        }
        
        nav a:hover {
            opacity: 0.8;
        }
        
        body {
            padding-top: 60px;
        }
        
        .post-meta {
            color: #666;
            font-size: 0.9rem;
            margin-bottom: 20px;
            font-style: italic;
        }
        
        @media (max-width: 768px) {
            h1 {
                font-size: 2.5rem;
            }
            
            .tagline {
                font-size: 1.3rem;
            }
            
            .content-box {
                padding: 30px;
            }
        }"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - The Blueprint Magazine</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Montserrat:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
{css}
    </style>
</head>
<body>
    <nav>
        <div class="nav-container">
            <div>
                <a href="../index.html">Home</a>
                <a href="https://the-blueprint.ghost.io/contributor-portal/">For Writers</a>
            </div>
        </div>
    </nav>
    
    <div class="container">
        <header>
            <h1>{title}</h1>
            {tagline}
        </header>

        <div class="content-box">
            {metadata_section}
            {content}
        </div>
    </div>
</body>
</html>"""


def append_to_jsonl(filename, data_object):
    """Appends a single Python object as a JSON line to a file."""
    with open(filename, 'a', encoding='utf-8') as f:
        # Serialize the object to a JSON string and add a newline
        json_string = json.dumps(data_object)
        f.write(json_string + '\n')


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
    # Find the first header
    header_pattern = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
    match = header_pattern.search(content)
    
    if match:
        # Return content from the first header onwards
        return content[match.start():]
    
    # If no header found, return original content
    return content


def convert_markdown_to_html(md_file_path, output_dir):
    """Convert a single markdown file to HTML."""
    print(f"Converting: {md_file_path}")
    
    # Read markdown file
    with open(md_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract frontmatter
    metadata, md_content = extract_frontmatter(content)
    
    # Remove text before first header
    md_content = remove_text_before_first_header(md_content)
    
    # Convert markdown to HTML
    html_content = markdown.markdown(
        md_content,
        extensions=['extra', 'codehilite', 'tables', 'fenced_code']
    )
    
    # Extract title from metadata or first h1
    title = metadata.get('title', '')
    if not title:
        # Try to extract from first h1 in markdown
        h1_match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1)
        else:
            title = Path(md_file_path).stem.replace('-', ' ').title()
    
    # remove duplicate title in template
    html_content.replace('<h1>{title}</h1>', '')
            
    # Create tagline if available
    tagline = ''
    if 'tagline' in metadata:
        tagline = f'<p class="tagline">{metadata["tagline"]}</p>'
    elif 'description' in metadata:
        tagline = f'<p class="tagline">{metadata["description"]}</p>'
    
    # Create metadata section
    metadata_parts = []
    if 'author' in metadata:
        metadata_parts.append(f"By {metadata['author']}")
    if 'date' in metadata:
        metadata_parts.append(str(metadata['date']))
    
    metadata_section = ''
    if metadata_parts:
        metadata_section = f'<p class="post-meta">{" | ".join(metadata_parts)}</p>'
    
    # Generate final HTML
    final_html = HTML_TEMPLATE.format(
        title=title,
        tagline=tagline,
        metadata_section=metadata_section,
        content=html_content,
        css=CSS_TEMPLATE
    )
    
    # Create output filename
    output_filename = Path(md_file_path).stem + '.html'
    output_path = output_dir / output_filename
    
    # Write HTML file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_html)

    # append the new data
    append_to_jsonl(output_dir / '_data.jsonl',
                    {"title": title, "url": str(output_path)})
    
    print(f"Created: {output_path}")
    return True


def main():
    """Main conversion process."""
    # Define directories
    draft_dir = Path('_draft')
    output_dir = Path('post')
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)
    
    # Check if draft directory exists
    if not draft_dir.exists():
        print(f"Draft directory '{draft_dir}' does not exist. Creating it...")
        draft_dir.mkdir(exist_ok=True)
        print("No markdown files to convert.")
        return
    
    # Find all markdown files
    md_files = list(draft_dir.glob('*.md'))
    
    if not md_files:
        print("No markdown files found in _draft directory.")
        return
    
    print(f"Found {len(md_files)} markdown file(s) to convert.")
    
    # Convert each file
    converted_files = []
    for md_file in md_files:
        try:
            if convert_markdown_to_html(md_file, output_dir):
                converted_files.append(md_file)
        except Exception as e:
            print(f"Error converting {md_file}: {e}")
    
    # Remove converted markdown files
    for md_file in converted_files:
        try:
            md_file.unlink()
            print(f"Removed: {md_file}")
        except Exception as e:
            print(f"Error removing {md_file}: {e}")
    
    print(f"\nConversion complete! Converted {len(converted_files)} file(s).")


if __name__ == '__main__':
    main()
