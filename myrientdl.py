#!/usr/bin/env python3

import sys
import re
import os
import argparse
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, unquote
from rapidfuzz import fuzz
from tqdm import tqdm

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='''Download Links Extractor and Downloader.
This script extracts download links from a web page and optionally downloads them concurrently.
You can search for specific keywords with fuzzy matching, specify the number of top matches,
and control the number of concurrent downloads.
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-u', '--url', help='URL of the web page to parse')
    parser.add_argument('-kw', '--keywords', help='Path to the text file containing keywords (one per line)')
    parser.add_argument('-o', '--output', default='links.txt', help='Output file to store links')
    parser.add_argument('-d', '--download', action='store_true', help='Download the links from the saved list')
    parser.add_argument('-l', '--linkfile', help='File containing links to download')
    parser.add_argument('-c', '--concurrent', type=int, default=5, help='Number of concurrent downloads (default: 5)')
    parser.add_argument('-p', '--path', default='.', help='Path to save downloaded files (default: current directory)')
    parser.add_argument('--topn', type=int, help='Number of best matches to retrieve (default: all matches)', default=None)
    return parser.parse_args()

def read_keywords(keyword_file):
    try:
        with open(keyword_file, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        sys.exit(f'Error: Keyword file {keyword_file} not found.')

def fetch_page(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        sys.exit(f'HTTP error occurred: {e}')
    except requests.exceptions.RequestException as e:
        sys.exit(f'Error fetching the page: {e}')

def extract_links(html_content, base_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    for link in soup.find_all('a', href=True):
        full_url = urljoin(base_url, link['href'])
        links.append({'href': full_url, 'text': link.get_text(strip=True)})
    return links

def fuzzy_match(links, keyword, topn):
    scored_links = []
    for link in links:
        text = link['text'] + ' ' + link['href']
        score = fuzz.partial_ratio(keyword.lower(), text.lower())
        if score > 0:
            scored_links.append((score, link['href']))
    scored_links.sort(reverse=True, key=lambda x: x[0])
    return [link for _, link in scored_links[:topn]]

def save_links(keyword_links, output_file):
    with open(output_file, 'w') as f:
        for keyword, links in keyword_links.items():
            f.write(f'--- {keyword} ---\n')
            for link in links:
                f.write(f'{link}\n')
            f.write('\n')
    print(f'Links saved to {output_file}')

def read_links(link_file):
    try:
        with open(link_file, 'r') as f:
            return [line.strip() for line in f if re.match(r'^https?://', line.strip())]
    except FileNotFoundError:
        sys.exit(f'Error: Link file {link_file} not found.')

def download_link(url, path, retries=3, error_log="error_log.txt"):
    attempt = 0
    while attempt < retries:
        try:
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                filename = r.headers.get('Content-Disposition')
                if filename:
                    filename = re.findall('filename="(.+)"', filename)
                    local_filename = os.path.join(path, filename[0]) if filename else os.path.join(path, url.split('/')[-1])
                else:
                    local_filename = os.path.join(path, url.split('/')[-1])

                readable_name = unquote(os.path.basename(local_filename))
                display_name = readable_name if len(readable_name) <= 30 else readable_name[:27] + '...'

                total_size = int(r.headers.get('content-length', 0))
                with open(local_filename, 'wb') as f, tqdm(
                    desc=display_name,
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    leave=False
                ) as bar:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bar.update(len(chunk))
            return f"Downloaded {url} to {local_filename}"
        except Exception as e:
            attempt += 1
            if attempt == retries:
                with open(error_log, 'a') as log_file:
                    log_file.write(f"Failed to download {url} after {retries} attempts: {e}\n")
                return f"Failed to download {url}: {e}"
            print(f"Retrying {url} ({attempt}/{retries})...")

def download_links(links, max_workers, path):
    os.makedirs(path, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_link, url, path): url for url in links}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Downloading files", unit="file"):
            result = future.result()
            print(result)

def main():
    args = parse_arguments()

    if args.url and args.keywords:
        keywords = read_keywords(args.keywords)
        html_content = fetch_page(args.url)
        links = extract_links(html_content, args.url)
        
        keyword_links = {}
        for keyword in keywords:
            matched_links = fuzzy_match(links, keyword, topn=args.topn)
            keyword_links[keyword] = matched_links
        
        save_links(keyword_links, args.output)

    if args.download:
        if not args.linkfile:
            sys.exit('Error: Link file is required for downloading.')
        links_to_download = read_links(args.linkfile)
        download_links(links_to_download, args.concurrent, args.path)

if __name__ == '__main__':
    main()