# Business Finder

This Python application helps you find businesses in a specific US postal code area and exports the results to Google Sheets. It searches for businesses using Google Places API and attempts to extract additional information like email addresses from their websites.

## Features

- Search businesses by postal code and keywords
- Validates US postal codes
- Extracts business information:
  - Name
  - Address
  - Phone number
  - Website
  - Email (if available on website)
  - Google Maps URL
  - Business status
- Exports results to Google Sheets

## Setup

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up Google Cloud Project:
   - Create a new project at [Google Cloud Console](https://console.cloud.google.com)
   - Enable the following APIs:
     - Google Places API
     - Google Sheets API
   - Create credentials:
     - Create OAuth 2.0 credentials
     - Download the credentials and save as `credentials.json` in the project root
     - Create an API key for Google Maps

4. Create a new Google Sheet and copy its ID (from the URL)

5. Create `.env` file:
   - Copy `.env.example` to `.env`
   - Add your Google Maps API key
   - Add your Google Sheets spreadsheet ID

## Usage

1. Run the script:
   ```bash
   python main.py
   ```

2. Enter a US postal code when prompted (format: XXXXX or XXXXX-XXXX)

3. Enter keywords for the type of business you're looking for (e.g., "restaurants", "dentists", "hardware stores")

4. The script will:
   - Search for matching businesses
   - Extract available information
   - Export results to your Google Sheet

5. Type 'quit' at the postal code prompt to exit

## Notes

- The script includes rate limiting to comply with API restrictions
- Email extraction attempts to find email addresses on business websites but may not always be successful
- The Google Sheet will be cleared before new data is written

## Requirements

- Python 3.7+
- Google Cloud Platform account
- Google Maps API key
- Google OAuth 2.0 credentials
- Google Sheet 