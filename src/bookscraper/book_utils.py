import hashlib
import re
import sys
from datetime import datetime
import logging
import os
from dotenv import load_dotenv
from pymongo import MongoClient, server_api
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure

# --- Global logging setup ---
# Define basic ANSI color codes (customize as needed)
# Moved COLORS and RESET_COLOR_CODE outside print_log for efficiency
COLORS = {
	"info": "\x1b[0m",  # White for info
	"step": "\x1b[36m", # Cyan for important process steps
	"success": "\x1b[32m",  # Green for info
	"warning": "\x1b[33m",  # Yellow for warning
	"error": "\x1b[31m",  # Red for error
	"debug": "\x1b[36m",  # Cyan for debug
	"critical": "\x1b[41m\x1b[37m",  # White text on Red background for critical
}
RESET_COLOR_CODE = "\x1b[0m"  # Reset all attributes

# Set up a dedicated logger for bookscraper output
# Using a specific logger name to avoid conflicts with the root logger
logger = logging.getLogger('bookscraper_app')
logger.setLevel(logging.INFO)  # Set the default logging level

# File Handler: Writes logs to a file
log_file_path = "bookscraper.log"
# Ensure file_handler is only added once
if not any(
		isinstance(handler, logging.FileHandler) and handler.baseFilename == os.path.abspath(log_file_path) for handler
		in logger.handlers):
	file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
	file_handler.setLevel(logging.INFO)
	formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	file_handler.setFormatter(formatter)
	logger.addHandler(file_handler)

# Stream Handler: Writes logs to console
# Ensure console_handler is only added once
# if not any(isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout for handler in logger.handlers):
#     console_handler = logging.StreamHandler(sys.stdout)
#     console_handler.setLevel(logging.INFO)
# The console handler's encoding is crucial here
# It attempts to set the stream's encoding if possible, but the underlying
# terminal might still have limitations.
# console_handler.encoding = "utf-8"
# For console output, we want to allow raw ANSI codes to be interpreted
# so we'll apply them in print_log and pass clean text to the logger itself.
# console_handler.setFormatter(logging.Formatter('%(message)s'))  # Formatter for console handler (no extra info)
# logger.addHandler(console_handler)

# Optional: If you want to suppress output from the root logger, you can configure it:
# logging.getLogger().setLevel(logging.CRITICAL)
# logging.getLogger().addHandler(logging.NullHandler()) # Adds a handler that does nothing


# Regex to remove ANSI escape codes from a string (for clean file logs)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def print_log(text: str, status: str = "info") -> None:
	"""
	Logs the given text with color-coding for console output,
	and plain text for file logs.
	"""
	# Get the appropriate logging method (info, error, warning, etc.)
	log_method = getattr(logger, status.lower(), logger.info)  # Use .lower() for status consistency

	# Create the colored message for console output
	colored_text = f"{COLORS.get(status, '')}{text}{RESET_COLOR_CODE}"

	# Log the UNCOLORED text to the logger.
	# The file_handler will get this clean text.
	# The console_handler *also* gets this, but we'll additionally print colored text directly.
	clean_text = ANSI_ESCAPE_PATTERN.sub('', text)  # Strip ANSI codes for the logger message
	log_method(clean_text)

	# Attempt to print the colored message directly to sys.stdout.
	# This bypasses the logging handler's internal write method and its encoding,
	# relying on sys.stdout (which is hopefully UTF-8 enabled) and terminal ANSI support.
	try:
		sys.stdout.write(colored_text + "\n")
		sys.stdout.flush()  # Ensure it's written immediately
	except Exception as e:
		# Fallback if direct console print fails (e.g., non-compatible terminal),
		# log it uncolored via the logger.
		logger.error(f"Failed to print colored message to console directly: {e}. Original message: {clean_text}",
		             exc_info=False)


def check_csv_write_permission(directory: str = '.') -> bool:
	"""
	Checks if the application has write permissions in the specified directory.
	Attempts to create, write to, and delete a dummy file.
	Returns True if successful, False otherwise.
	"""
	test_file_path = os.path.join(directory, "test_write_permission.tmp")
	try:
		with open(test_file_path, 'w') as f:
			f.write("test")
		os.remove(test_file_path)
		print_log("Successfully created write permission file.", "success")
		logger.info(f"Successfully verified write permission in '{directory}'.")
		return True
	except OSError as e:
		logger.error(f"Write permission test failed in '{directory}': {e}")
		print_log(
			f"Permission Error: Cannot write to the current directory ('{directory}'). Please ensure you have write access.",
			"error")
		return False
	except Exception as e:
		logger.error(f"An unexpected error occurred during CSV write permission test: {e}", exc_info=True)
		print_log("An unexpected error occurred during CSV write permission test. Check log for details.", "error")
		return False


def check_mongodb_connection() -> bool | None:
	"""
	Attempts to establish and ping a MongoDB Atlas connection.
	Returns True if successful, False otherwise.
	"""
	load_dotenv()  # Ensure .env variables are loaded
	mongodb_uri = os.environ.get("MONGODB_URI")
	tls_cert_file = os.environ.get("TLS_CERT_FILE")

	if not mongodb_uri:
		logger.error("MONGODB_URI not found in environment variables for MongoDB connection test.")
		print_log("MongoDB Check Error: MONGODB_URI not found in environment variables. Cannot test connection.",
		          "error")
		return False

	client = None
	try:
		if tls_cert_file and os.path.exists(tls_cert_file):
			client = MongoClient(mongodb_uri,
			                     tls=True,
			                     tlsCertificateKeyFile=tls_cert_file,
			                     server_api=server_api.ServerApi('1'),
			                     serverSelectionTimeoutMS=5000)  # Added timeout
		else:
			client = MongoClient(mongodb_uri,
			                     server_api=server_api.ServerApi('1'),
			                     serverSelectionTimeoutMS=5000)  # Added timeout

		client.admin.command('ping')
		logger.info("MongoDB connection test successful.")
		return True
	except (ConnectionFailure, ServerSelectionTimeoutError) as e:
		logger.error(f"MongoDB connection test failed: {e}")
		print_log(
			f"MongoDB Connection Error: Failed to connect to MongoDB Atlas. Please check your MONGODB_URI, TLS certificate, and network. Details: {e}",
			"error")
		return False
	except Exception as e:
		logger.critical(f"An unexpected error occurred during MongoDB connection test: {e}", exc_info=True)
		print_log(
			"MongoDB Check Error: An unexpected error occurred during connection test. Check log for full traceback.",
			"error")
		return False
	finally:
		if client:
			client.close()


def extract_year_from_date(date_string: str) -> int | None:
	"""
	Extracts the year from a date string.

	Args:
	  date_string: The date string in any supported format (e.g., "2023-12-19", "December 17, 2019", "1995", "Apr 23, 2021", "September 2016", "Last updated on 2016-11-29").

	Returns:
	  int: The extracted year, or None if the year cannot be extracted.
	"""
	if date_string == "N/A" or date_string is None:
		return None

	if not isinstance(date_string, str):
		logger.warning(f"Invalid input type for date_string: {type(date_string)}. Expected string.")
		return None

	# 1. Try to extract YYYY-MM-DD using regex if it's embedded in a larger string
	# This handles "Last updated on YYYY-MM-DD" from leanpub.com or similar
	date_pattern_in_text = r'\d{4}-\d{2}-\d{2}'
	match = re.search(date_pattern_in_text, date_string)
	if match:
		extracted_date_part = match.group(0)
		try:
			date_object = datetime.strptime(extracted_date_part, "%Y-%m-%d")
			return date_object.year
		except ValueError:
			logger.debug(f"Regex extracted '{extracted_date_part}' but it failed to parse as %Y-%m-%d.")
			pass

	# 2. Attempt to parse the date string using different direct formats
	supported_formats = ["%Y-%m-%d", "%B %d, %Y", "%Y", "%b %d, %Y", "%B %Y"]

	try:
		for date_format in supported_formats:
			try:
				date_object = datetime.strptime(date_string, date_format)
				return date_object.year
			except ValueError:
				continue  # Try the next format

		# If none of the formats worked
		logger.warning(
			f"Could not extract year from date string: '{date_string}' using known formats or regex pattern.")
		return None

	except Exception as e:
		logger.error(f"Error in extract_year_from_date for '{date_string}': {e}", exc_info=True)
		return None


def hash_book(title: str = "", authors: list = None, year=None) -> str:
	"""
	Calculates a SHA-256 hash for a book based on its title, authors, and year.

	Args:
		title: The title of the book (required).
		authors: The authors of the book, separated by commas (required).
		year: The publication year of the book (optional, default is 0).

	Returns:
		A hexadecimal string representing the SHA-256 hash of the combined fields.
	"""

	if authors is None:
		authors = []
	else:
		# Normalize and sort authors for consistent hashing
		authors = sorted([str(a).strip().lower() for a in authors if a is not None])

	try:
		if not title:
			logger.warning("Attempted to hash a book with no title. Hash will be based on empty title.")
			# raise ValueError("Title is required.") # Could raise an error, but warning might be better to hash incomplete entries

		year_str = str(year) if year is not None else ""

		# Join authors for consistent hashing
		authors_str = "|".join(authors)

		# Normalize hash input and proceed
		combined_fields = f"{title.strip().lower()}|{authors_str}|{year_str}"
		hash_object = hashlib.sha256()
		hash_object.update(combined_fields.encode('utf-8'))
		return hash_object.hexdigest()

	except Exception as e:
		logger.error(f"Error hashing book (title: '{title}', authors: {authors}, year: {year}): {e}")
		return ''
