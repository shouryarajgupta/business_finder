import os
import re
import time
from typing import Dict, List
import googlemaps
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import threading
from datetime import datetime
import json
import traceback
from tenacity import retry, stop_after_attempt, wait_exponential

def log_step(step: str, error: bool = False):
    """Helper function to print visually distinct log messages."""
    line = "=" * 50
    status = "ERROR" if error else "START"
    print(f"\n{line}")
    print(f"{status}: {step}")
    print(f"{line}\n")

# Load environment variables
load_dotenv()

class BusinessFinder:
    def __init__(self):
        log_step("Initializing BusinessFinder")
        try:
            # Validate Google Maps API Key
            self.api_key = os.getenv('GOOGLE_MAPS_API_KEY')
            if not self.api_key:
                log_step("Google Maps API key not found", error=True)
                raise ValueError("Google Maps API key not found in environment variables")
            print(f"✓ Found Maps API key: {self.api_key[:10]}...")
            
            # Validate Spreadsheet ID
            self.spreadsheet_id = os.getenv('SPREADSHEET_ID')
            if not self.spreadsheet_id:
                log_step("Spreadsheet ID not found", error=True)
                raise ValueError("Spreadsheet ID not found in environment variables")
            print(f"✓ Found spreadsheet ID: {self.spreadsheet_id}")
            
            # Initialize Google Maps client
            log_step("Initializing Google Maps Client")
            self.gmaps = googlemaps.Client(key=self.api_key)
            print("✓ Google Maps client initialized successfully")
            
            self.SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
            self.SHEET_NAME_MAX_LENGTH = 100  # Google Sheets maximum sheet name length
            
            # Initialize Sheets service
            log_step("Initializing Google Sheets Service")
            self.sheets_service = self._initialize_sheets_service()
            print("✓ Google Sheets service initialized successfully")
            
            self.DEFAULT_MAX_RESULTS = 20
            self.MAX_ALLOWED_RESULTS = 100
            self.BASE_SEARCH_TIMEOUT = 60  # Base timeout for 20 results
            self.MAX_SEARCH_TIMEOUT = 300  # Maximum timeout (5 minutes)
            
            log_step("BusinessFinder Initialization Complete")
            
        except Exception as e:
            log_step(f"BusinessFinder Initialization Failed: {str(e)}", error=True)
            print(f"Error traceback:\n{traceback.format_exc()}")
            raise

    def _initialize_sheets_service(self):
        """Initialize Google Sheets API service using service account."""
        log_step("Setting up Google Sheets Authentication")
        try:
            # Get and validate service account info
            service_account_key = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY')
            if not service_account_key:
                log_step("Service Account Key Not Found", error=True)
                print("CRITICAL: GOOGLE_SERVICE_ACCOUNT_KEY environment variable is not set")
                raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY not found in environment variables")
            print("✓ Found service account key in environment")
            
            try:
                print("Parsing service account JSON...")
                service_account_info = json.loads(service_account_key)
                print("✓ Successfully parsed service account JSON")
            except json.JSONDecodeError as e:
                log_step("Invalid Service Account JSON", error=True)
                print(f"CRITICAL: Failed to parse GOOGLE_SERVICE_ACCOUNT_KEY as JSON: {str(e)}")
                raise ValueError(f"Invalid JSON in GOOGLE_SERVICE_ACCOUNT_KEY: {str(e)}")
            
            # Validate required fields
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in service_account_info]
            if missing_fields:
                log_step("Missing Required Fields in Service Account", error=True)
                print(f"CRITICAL: Service account JSON is missing fields: {', '.join(missing_fields)}")
                raise ValueError(f"Service account key missing required fields: {', '.join(missing_fields)}")
            
            print(f"✓ Using service account email: {service_account_info.get('client_email')}")
            
            log_step("Creating Google Sheets Credentials")
            try:
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=self.SCOPES
                )
                print("✓ Successfully created service account credentials")
            except Exception as e:
                log_step("Failed to Create Credentials", error=True)
                print(f"CRITICAL: Could not create service account credentials: {str(e)}")
                print(f"Error traceback:\n{traceback.format_exc()}")
                raise ValueError(f"Failed to create service account credentials: {str(e)}")
            
            log_step("Building Google Sheets Service")
            try:
                sheets_service = build('sheets', 'v4', credentials=credentials)
                print("✓ Successfully built Google Sheets service")
                
                # Test the service with a simple API call
                log_step("Testing Google Sheets API Access")
                sheets_service.spreadsheets().get(
                    spreadsheetId=self.spreadsheet_id
                ).execute()
                print("✓ Successfully verified Google Sheets API access")
                
                return sheets_service
                
            except Exception as e:
                log_step("Failed to Initialize Sheets Service", error=True)
                print(f"CRITICAL: Failed to initialize or test Google Sheets service: {str(e)}")
                print(f"Error traceback:\n{traceback.format_exc()}")
                raise ValueError(f"Failed to initialize Google Sheets service: {str(e)}")
            
        except Exception as e:
            error_details = traceback.format_exc()
            log_step(f"Sheets Authentication Failed: {str(e)}", error=True)
            print(f"CRITICAL: Authentication failed with error: {str(e)}")
            print(f"Error traceback:\n{error_details}")
            raise ValueError(f"Failed to initialize Google Sheets service: {str(e)}")

    def validate_postal_code(self, postal_code: str, country: str) -> bool:
        """Validate postal code format based on country."""
        if country == 'US':
            pattern = r'^\d{5}(-\d{4})?$'
        else:  # India
            pattern = r'^\d{6}$'
        return bool(re.match(pattern, postal_code))

    def _sanitize_sheet_name(self, name: str) -> str:
        """Sanitize sheet name to comply with Google Sheets requirements."""
        # Remove or replace invalid characters
        invalid_chars = r'[\\*?/\[\]:]'
        name = re.sub(invalid_chars, '_', name)
        
        # Truncate if too long
        if len(name) > self.SHEET_NAME_MAX_LENGTH:
            name = name[:self.SHEET_NAME_MAX_LENGTH - 10] + datetime.now().strftime("_%H%M%S")
        
        return name

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def _create_new_sheet(self, sheet_name: str = None) -> str:
        """Create a new sheet in the spreadsheet with retry logic."""
        log_step(f"Creating New Sheet: {sheet_name or 'auto-generated'}")
        try:
            if not sheet_name:
                sheet_name = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            sheet_name = self._sanitize_sheet_name(sheet_name)
            print(f"Using sanitized sheet name: {sheet_name}")
            
            request = {
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }
            
            result = self.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': [request]}
            ).execute()
            
            print(f"✓ Successfully created new sheet: {sheet_name}")
            return sheet_name
            
        except HttpError as e:
            if 'already exists' in str(e):
                print(f"Sheet name '{sheet_name}' already exists, generating new name...")
                new_name = f"{sheet_name}_{datetime.now().strftime('%H%M%S')}"
                return self._create_new_sheet(new_name)
            log_step(f"Failed to Create Sheet: {str(e)}", error=True)
            raise

    def _calculate_timeout(self, max_results: int) -> int:
        """Calculate appropriate timeout based on number of results requested."""
        if not max_results or max_results <= 0:
            max_results = self.DEFAULT_MAX_RESULTS
            
        # Scale timeout linearly with number of results
        # Base: 60 seconds for 20 results
        scaled_timeout = int((max_results / self.DEFAULT_MAX_RESULTS) * self.BASE_SEARCH_TIMEOUT)
        
        # Cap at maximum timeout
        return min(scaled_timeout, self.MAX_SEARCH_TIMEOUT)

    def _search_with_timeout(self, postal_code: str, keywords: List[str], country: str, max_results: int = None) -> List[Dict]:
        """Execute the search with a timeout for a single postal code."""
        result = []
        error_message = None
        
        # Validate and set max_results
        max_results = min(max_results or self.DEFAULT_MAX_RESULTS, self.MAX_ALLOWED_RESULTS)
        
        # Calculate appropriate timeout
        search_timeout = self._calculate_timeout(max_results)
        print(f"Using search timeout of {search_timeout} seconds for {max_results} results")

        def search_task():
            nonlocal result, error_message
            try:
                # Get location coordinates from postal code
                location_query = f"{postal_code}, {'United States' if country == 'US' else 'India'}"
                print(f"Geocoding: {location_query}")
                geocode_result = self.gmaps.geocode(location_query)
                
                if not geocode_result:
                    error_message = f"Could not find location for {location_query}"
                    return

                location = geocode_result[0]['geometry']['location']
                print(f"Location found: {location}")
                
                # Search for each keyword with exponential backoff
                for keyword in keywords:
                    search_query = f"{keyword} in {postal_code}"
                    print(f"Searching for: {search_query}")
                    
                    try:
                        places_result = self.gmaps.places(
                            query=search_query,
                            location=(location['lat'], location['lng']),
                            radius=5000  # 5km radius
                        )

                        places = places_result.get('results', [])[:max_results]
                        print(f"Found {len(places)} results for '{keyword}'")

                        # Process places in chunks to manage memory
                        chunk_size = min(5, max(2, max_results // 10))  # Adjust chunk size based on max_results
                        for i in range(0, len(places), chunk_size):
                            chunk = places[i:i + chunk_size]
                            for place in chunk:
                                try:
                                    place_details = self.gmaps.place(place['place_id'], 
                                        fields=['name', 'formatted_address', 'formatted_phone_number', 
                                               'website', 'url', 'business_status'])
                                    
                                    details = place_details.get('result', {})
                                    
                                    business_info = {
                                        'name': details.get('name', ''),
                                        'address': details.get('formatted_address', ''),
                                        'phone': details.get('formatted_phone_number', ''),
                                        'website': details.get('website', ''),
                                        'google_maps_url': details.get('url', ''),
                                        'business_status': details.get('business_status', ''),
                                        'postal_code': postal_code,
                                        'keyword': keyword
                                    }
                                    
                                    # Only extract email if website is available
                                    if details.get('website'):
                                        business_info['email'] = self._extract_email(details['website'])
                                    else:
                                        business_info['email'] = ''
                                        
                                    result.append(business_info)
                                    print(f"Added business: {business_info['name']}")
                                    
                                except Exception as e:
                                    print(f"Error processing place {place.get('place_id')}: {str(e)}")
                                    continue
                                
                            # Adjust sleep time based on chunk size
                            time.sleep(max(1, min(2, chunk_size / 3)))
                            
                    except Exception as e:
                        print(f"Error searching for keyword '{keyword}': {str(e)}")
                        continue
                    
            except Exception as e:
                error_message = str(e)
                print(f"Error during search: {error_message}")
                print(f"Error traceback: {traceback.format_exc()}")

        # Execute search with timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(search_task)
            try:
                future.result(timeout=search_timeout)
            except (FuturesTimeoutError, TimeoutError) as e:
                print(f"Search timed out after {search_timeout} seconds")
                # Return partial results if any
                if result:
                    print(f"Returning {len(result)} results collected before timeout")
                    return result
                error_message = f"Search timed out after {search_timeout} seconds"

        if not result and error_message:
            print(f"Error for postal code {postal_code}: {error_message}")
            
        return result

    def search_businesses(self, postal_codes: List[str], keywords: List[str], country: str, max_results: int = None) -> List[Dict]:
        """Search for businesses using Google Places API."""
        all_results = []
        errors = []

        # Validate all postal codes first
        for postal_code in postal_codes:
            if not self.validate_postal_code(postal_code.strip(), country):
                raise ValueError(f"Invalid {'US postal code' if country == 'US' else 'PIN code'}: {postal_code}")

        # Search for each postal code
        for postal_code in postal_codes:
            postal_code = postal_code.strip()
            try:
                results = self._search_with_timeout(postal_code, keywords, country, max_results)
                all_results.extend(results)
            except Exception as e:
                errors.append(f"Error searching {postal_code}: {str(e)}")
                continue

        if errors:
            print("Search completed with errors:", errors)
        
        return all_results

    def _extract_email(self, website: str) -> str:
        """Extract email from website if available."""
        if not website:
            return ''
            
        try:
            # Add timeout and headers to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(website, timeout=5, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            email_pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'
            
            # Only search in specific tags to reduce memory usage
            text_content = ' '.join([
                tag.get_text()
                for tag in soup.find_all(['p', 'a', 'span', 'div'])
                if tag.get_text()
            ])
            
            emails = re.findall(email_pattern, text_content)
            return emails[0] if emails else ''
            
        except Exception as e:
            print(f"Error extracting email from {website}: {str(e)}")
            return ''

    def export_to_sheets(self, businesses: List[Dict], sheet_name: str = None) -> str:
        """Export business data to Google Sheets using append."""
        if not businesses:
            return None

        try:
            # Create new sheet with timestamp if none provided
            if not sheet_name:
                sheet_name = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Create new sheet
            sheet_name = self._create_new_sheet(sheet_name)

            # Prepare the data
            headers = ['Name', 'Address', 'Phone', 'Website', 'Email', 'Google Maps URL', 'Status', 'Postal Code', 'Keyword']
            rows = [[
                business.get('name', ''),
                business.get('address', ''),
                business.get('phone', ''),
                business.get('website', ''),
                business.get('email', ''),
                business.get('google_maps_url', ''),
                business.get('business_status', ''),
                business.get('postal_code', ''),
                business.get('keyword', '')
            ] for business in businesses]

            # First, update headers
            range_name = f"{sheet_name}!A1:I1"
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body={'values': [headers]}
            ).execute()

            # Then append data
            range_name = f"{sheet_name}!A2:I{len(rows) + 1}"
            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': rows}
            ).execute()
            
            print(f"Successfully exported {len(businesses)} businesses to sheet '{sheet_name}'")
            return sheet_name
            
        except Exception as e:
            error_details = traceback.format_exc()
            print(f"Error exporting to sheets: {str(e)}")
            print(f"Error traceback: {error_details}")
            raise ValueError(f"Failed to export to Google Sheets: {str(e)}")

def main():
    finder = BusinessFinder()
    
    while True:
        postal_codes = input("Enter US postal codes (comma-separated, or 'quit' to exit): ").split(',')
        if postal_codes[0].lower() == 'quit':
            break
            
        keywords = input("Enter business type keywords: ").split(',')
        
        country = input("Enter country code (US for USA, IN for India): ")
        
        max_results = input("Enter max results (leave empty for default): ")
        if max_results:
            max_results = int(max_results)
        else:
            max_results = None
        
        print("\nSearching for businesses... This may take a few minutes.")
        businesses = finder.search_businesses(postal_codes, keywords, country, max_results)
        
        if businesses:
            print(f"\nFound {len(businesses)} businesses. Exporting to Google Sheets...")
            sheet_name = finder.export_to_sheets(businesses)
            print(f"Export complete! Check your Google Sheet: {sheet_name}")
        else:
            print("No businesses found matching your criteria.")

if __name__ == "__main__":
    main() 