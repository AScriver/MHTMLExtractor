# MHTMLExtractor

`MHTMLExtractor` is a high-performance, standalone Python utility to extract files from MHTML (MIME HTML) documents. These documents are typically a snapshot of a web page and might contain images, scripts, styles, and the web page itself as a single file.

## Features

- **High Performance**: Optimized memory usage and processing speed with automatic buffer sizing
- **Dry-run Mode**: Analyze MHTML files without extracting to preview contents
- **Comprehensive Statistics**: Detailed extraction statistics and timing information
- **Type Safety**: Full type hints for better code quality and IDE support
- **Flexible Filtering**: Selectively skip extraction of certain file types (CSS, images, etc.)
- **Smart Filename Handling**: Intelligent filename generation with conflict resolution
- **Efficient Processing**: Optimized string operations and memory management
- **Progress Reporting**: Detailed logging with configurable verbosity levels

## Performance Improvements

- **Adaptive Buffer Sizing**: Automatically optimizes buffer size based on file size
- **Linear String Operations**: Uses list-based concatenation for O(n) performance instead of O(n²)
- **Efficient Link Updates**: Optimized HTML link replacement using regex substitution
- **Memory Optimization**: Processes files in chunks to handle large MHTML files efficiently

## Prerequisites

- Python 3.7+ (with type hint support)

## Usage (CLI)

To use the MHTML Extractor, simply run the script and provide the necessary arguments:

```bash
usage: MHTMLExtractor.py [-h] [--output_dir OUTPUT_DIR] [--buffer_size BUFFER_SIZE] 
                         [--clear_output_dir] [--no-css] [--no-images] [--html-only] 
                         [--dry-run] [--verbose] [--quiet]
                         mhtml_path

positional arguments:
  mhtml_path              Path to the MHTML document.

optional arguments:
  -h, --help              show this help message and exit
  --output_dir OUTPUT_DIR
                          Output directory for the extracted files. (default: current directory)
  --buffer_size BUFFER_SIZE
                          Buffer size for reading the MHTML file. (default: 8192)
  --clear_output_dir      If set, clears the output directory before extraction.
  --no-css                If set, CSS files will not be extracted.
  --no-images             If set, image files will not be extracted.
  --html-only             If set, only HTML files will be extracted.
  --dry-run               If set, analyze the MHTML file without extracting files.
  --verbose, -v           Enable verbose logging output.
  --quiet, -q             Suppress all output except errors.
```

## Usage (Python)

To use the MHTML Extractor, simply import the script and provide the necessary arguments:
```py
from MHTMLExtractor import MHTMLExtractor

extractor = MHTMLExtractor(
  mhtml_path='example.mhtml',
  output_dir='path/to/output/dir',  # Optional, default is current directory (".")
  create_in_memory_output=True,  # Optional, default is False. If True, `extractor.extracted_contents` will be created, what contains extracted data. Only available in Python API (not CLI).
  create_output_files=False  # Optional, default is True. If False, output files won't be created.
)
```


## Examples (CLI)

1. **Extract all files** from an MHTML document:
```bash
python MHTMLExtractor.py example.mhtml
```

2. **Extract files to a specific directory**:
```bash
python MHTMLExtractor.py example.mhtml --output_dir ./extracted
```

3. **Extract only HTML files**:
```bash
python MHTMLExtractor.py example.mhtml --html-only
```

4. **Dry-run analysis** (preview without extracting):
```bash
python MHTMLExtractor.py example.mhtml --dry-run --verbose
```

5. **Extract without CSS and images**:
```bash
python MHTMLExtractor.py example.mhtml --no-css --no-images
```

6. **High-performance extraction with custom buffer**:
```bash
python MHTMLExtractor.py large_file.mhtml --buffer_size 65536 --verbose
```

## Examples (Python):

1. In-memory mode (files won't be created):
```py
from MHTMLExtractor import MHTMLExtractor

extractor = MHTMLExtractor(
  mhtml_path='example.mhtml',
  create_in_memory_output=True,
  create_output_files=False
)
extractor.extract()

# Extracted content available in `extractor.extracted_contents` dict.
for filename, details in extractor.extracted_contents.items():
  print('=== Filename:', filename, '\n')
  print('=== Content type:', details['content_type'], '\n')
  print('=== Decoded content:', details['decoded_body'])

  break
```

2. Both, in-memory mode and file mode:
```py
from MHTMLExtractor import MHTMLExtractor

extractor = MHTMLExtractor(
  mhtml_path='example.mhtml',
  output_dir='/path/to/output/dir',  # Optional, default is current directory (".")
  create_in_memory_output=True,
  create_output_files=True,
)
extractor.extract()

# Extracted content available in `extractor.extracted_contents` dict.
for filename, details in extractor.extracted_contents.items():
  print('=== Filename:', filename, '\n')
  print('=== Content type:', details['content_type'], '\n')
  print('=== Decoded content:', details['decoded_body'])

  break
```

## Notes

- **Purpose**: This script is designed to extract files (like images, CSS, and HTML content) from MHTML documents. MHTML is a web page archive format that's used to combine multiple resources from a web page into a single file.

- **In-Memory Feature**: The `create_in_memory_output` feature is only available when using the Python API directly. It is not accessible via the command-line interface.

- **Performance**: The script efficiently reads the MHTML file in adaptive chunks (auto-optimized from 1KB to 1MB) to handle even very large files without consuming excessive memory.

- **Dry-Run Analysis**: Use `--dry-run` to preview what would be extracted without actually writing files. Perfect for analyzing unknown MHTML files.

- **Statistics**: Comprehensive extraction statistics including file counts by type, total size, and processing time.

- **Error Handling**: Robust error handling with specific error types and detailed messages for troubleshooting.

- **Handling Conflicts**: If potential filename conflicts arise (two extracted resources having the same name), the script handles it by appending a counter to the filename.

- **File Naming**: The filenames for the extracted files are based on the `Content-Location` from the MHTML headers with sanitization for filesystem safety. If unavailable, UUID-based filenames are generated. A hash derived from the original URL is appended to ensure uniqueness.

- **Link Updates**: Once extraction is complete, the script updates the links within the extracted HTML files to ensure they point to the new filenames of the extracted resources (unless using `--html-only`).

- **Filtering Options**: The script provides command-line flags to optionally exclude CSS files, image files, or to extract only HTML files.

- **Dependencies**: The script uses only Python's built-in libraries, so no additional installation is required. Requires Python 3.7+ for type hint support.

- **Cross-Platform**: Works on Windows, macOS, and Linux with proper path handling.

## License

This script is provided as-is under the MIT License. Use it at your own risk.
