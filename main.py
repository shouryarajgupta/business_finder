import os
import re
import time
from typing import Dict, List
import googlemaps
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading
from datetime import datetime

# Load environment variables
load_dotenv()

class BusinessFinder:
    def __init__(self):
        api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        print(f"Initializing with API key: {api_key[:10]}...")
        self.gmaps = googlemaps.Client(key=api_key)
        self.SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        self.spreadsheet_id = os.getenv('SPREADSHEET_ID')
        self.sheets_service = self._initialize_sheets_service()
        self.MAX_RESULTS = 20
        self.SEARCH_TIMEOUT = 60  # seconds

    def _initialize_sheets_service(self):
        """Initialize Google Sheets API service."""
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', self.SCOPES)
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', self.SCOPES)
            creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return build('sheets', 'v4', credentials=creds)

    def validate_postal_code(self, postal_code: str, country: str) -> bool:
        """Validate postal code format based on country."""
        if country == 'US':
            pattern = r'^\d{5}(-\d{4})?$'
        else:  # India
            pattern = r'^\d{6}$'
        return bool(re.match(pattern, postal_code))

    def _create_new_sheet(self, sheet_name: str = None) -> str:
        """Create a new sheet in the spreadsheet."""
        if not sheet_name:
            sheet_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
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
            
            return sheet_name
            
        except HttpError as e:
            if 'already exists' in str(e):
                # If sheet name exists, append timestamp
                new_name = f"{sheet_name}_{datetime.now().strftime('%H%M%S')}"
                return self._create_new_sheet(new_name)
            raise

    def _search_with_timeout(self, postal_code: str, keywords: List[str], country: str) -> List[Dict]:
        """Execute the search with a timeout for a single postal code."""
        result = []
        error_message = None
        
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
                
                # Search for each keyword
                for keyword in keywords:
                    search_query = f"{keyword} in {postal_code}"
                    print(f"Searching for: {search_query}")
                    
                    places_result = self.gmaps.places(
                        query=search_query,
                        location=(location['lat'], location['lng']),
                        radius=5000  # 5km radius
                    )

                    places = places_result.get('results', [])[:self.MAX_RESULTS]
                    print(f"Found {len(places)} results for '{keyword}'")

                    for place in places:
                        place_details = self.gmaps.place(place['place_id'], 
                            fields=['name', 'formatted_address', 'formatted_phone_number', 
                                   'website', 'url', 'business_status'])
                        
                        details = place_details['result']
                        
                        business_info = {
                            'name': details.get('name', ''),
                            'address': details.get('formatted_address', ''),
                            'phone': details.get('formatted_phone_number', ''),
                            'website': details.get('website', ''),
                            'google_maps_url': details.get('url', ''),
                            'email': self._extract_email(details.get('website', '')),
                            'business_status': details.get('business_status', ''),
                            'postal_code': postal_code,
                            'keyword': keyword
                        }
                        result.append(business_info)
                        print(f"Added business: {business_info['name']}")
                        time.sleep(1)
                    
            except Exception as e:
                error_message = str(e)
                print(f"Error during search: {error_message}")

        # Execute search with timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(search_task)
            try:
                future.result(timeout=self.SEARCH_TIMEOUT)
            except TimeoutError:
                error_message = f"Search timed out after {self.SEARCH_TIMEOUT} seconds"
                print(error_message)

        if not result and error_message:
            print(f"Error for postal code {postal_code}: {error_message}")
            
        return result

    def search_businesses(self, postal_codes: List[str], keywords: List[str], country: str) -> List[Dict]:
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
                results = self._search_with_timeout(postal_code, keywords, country)
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
            response = requests.get(website, timeout=5)
            soup = BeautifulSoup(response.text, 'html.parser')
            email_pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'
            
            text_content = soup.get_text()
            emails = re.findall(email_pattern, text_content)
            
            return emails[0] if emails else ''
            
        except Exception as e:
            print(f"Error extracting email from {website}: {str(e)}")
            return ''

    def export_to_sheets(self, businesses: List[Dict], sheet_name: str = None) -> str:
        """Export business data to Google Sheets."""
        if not businesses:
            return None

        # Create new sheet
        sheet_name = self._create_new_sheet(sheet_name)

        # Prepare the data
        headers = ['Name', 'Address', 'Phone', 'Website', 'Email', 'Google Maps URL', 'Status', 'Postal Code', 'Keyword']
        rows = [[
            business['name'],
            business['address'],
            business['phone'],
            business['website'],
            business['email'],
            business['google_maps_url'],
            business['business_status'],
            business['postal_code'],
            business['keyword']
        ] for business in businesses]

        try:
            # Update the new sheet
            range_name = f"{sheet_name}!A1:I{len(rows) + 1}"
            values = [headers] + rows
            body = {'values': values}
            
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"Successfully exported {len(businesses)} businesses to sheet '{sheet_name}'")
            return sheet_name
            
        except Exception as e:
            print(f"Error exporting to sheets: {str(e)}")
            raise

def main():
    finder = BusinessFinder()
    
    while True:
        postal_codes = input("Enter US postal codes (comma-separated, or 'quit' to exit): ").split(',')
        if postal_codes[0].lower() == 'quit':
            break
            
        keywords = input("Enter business type keywords: ").split(',')
        
        country = input("Enter country code (US for USA, IN for India): ")
        
        print("\nSearching for businesses... This may take a few minutes.")
        businesses = finder.search_businesses(postal_codes, keywords, country)
        
        if businesses:
            print(f"\nFound {len(businesses)} businesses. Exporting to Google Sheets...")
            sheet_name = finder.export_to_sheets(businesses)
            print(f"Export complete! Check your Google Sheet: {sheet_name}")
        else:
            print("No businesses found matching your criteria.")

if __name__ == "__main__":
    main() 