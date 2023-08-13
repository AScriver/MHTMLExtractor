# MHTMLExtractor

`MHTMLExtractor` is a Python utility to extract files from MHTML (MIME HTML) documents. These documents are typically a snapshot of a web page and might contain images, scripts, styles, and the web page itself as a single file.

## Features

- Extracts embedded files (e.g., CSS, images, JavaScript) from MHTML documents.
- Provides options to selectively skip extraction of certain file types.
- Handles potential filename conflicts by appending a counter.
- Efficient reading of large MHTML files through buffering.
- Updates links in extracted HTML files to point to the newly extracted resources.

## Prerequisites

- Python 3.x
- No external libraries are required.

## Usage

To use the MHTML Extractor, simply run the script and provide the necessary arguments:
```bash
usage: mhtml_extractor.py yourFile.mhtml
						  [-h] [--output_dir OUTPUT_DIR]
                          [--buffer_size BUFFER_SIZE]
                          [--no_css] [--no_images] [--html_only]
                          

positional arguments:
  mhtml_path            Path to the MHTML document.

optional arguments:
  -h, --help            show this help message and exit
  --output_dir OUTPUT_DIR
                        Output directory for the extracted files. Default is
                        the current directory.
  --buffer_size BUFFER_SIZE
                        Buffer size for reading the MHTML file. Defaults to
                        8192.
  --no_css              If set, CSS files will not be extracted.
  --no_images           If set, image files will not be extracted.
  --html_only           If set, only HTML files will be extracted.

```

## Examples

1. Extract all files from an MHTML document:
```bash
python mhtml_extractor.py example.mhtml
```

2. Extract files to a specific directory
```
Extract files to a specific directory:
```

3. Extract only the HTML files:
```
python mhtml_extractor.py example.mhtml --html_only
```

## Notes

- **Purpose**: This script is designed to extract files (like images, CSS, and HTML content) from MHTML documents. MHTML is a web page archive format that's used to combine multiple resources from a web page into a single file.

- **Performance**: The script efficiently reads the MHTML file in chunks (default size: 8192 bytes) to handle even large files without consuming excessive memory.

- **Handling Conflicts**: If potential filename conflicts arise (two extracted resources having the same name), the script handles it by appending a counter to the filename.

- **File Naming**: The filenames for the extracted files are either based on the `Content-Location` from the MHTML headers or, if that's unavailable, a random UUID. Additionally, a hash derived from the original URL is appended to ensure uniqueness.

- **Link Updates**: Once extraction is complete, the script updates the links within the extracted HTML files to ensure they point to the new filenames of the extracted resources.

- **Filtering Options**: The script provides command-line flags to optionally exclude CSS files, image files, or to extract only HTML files.

- **Dependencies**: The script uses Python's built-in libraries, so no additional installation is required. Make sure to have Python 3.x installed.

- **Usage**: Use the script via the command line. It provides several optional arguments for customization, like specifying an output directory, setting the buffer size, or applying filters. Refer to the script's help (`--help` option) for detailed usage information.


## License

This script is provided as-is under the MIT License. Use it at your own risk.
