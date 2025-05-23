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
     - Create a service account and download the JSON key
     - Create an API key for Google Maps
   - Share your target Google Sheet with the service account email

4. Create a new Google Sheet and copy its ID (from the URL)

5. Set up environment variables:
   - GOOGLE_MAPS_API_KEY: Your Google Maps API key
   - SPREADSHEET_ID: Your Google Sheets spreadsheet ID
   - GOOGLE_SERVICE_ACCOUNT_KEY: The entire JSON content of your service account key file

## Deployment on Render

1. Fork this repository to your GitHub account
2. Create a new Web Service on Render
3. Connect your GitHub repository
4. Add the following environment variables in Render:
   - GOOGLE_MAPS_API_KEY
   - SPREADSHEET_ID
   - GOOGLE_SERVICE_ACCOUNT_KEY (paste the entire JSON content)
   - ALLOWED_EMAIL (your Google account email)

## Usage

The application provides a web interface where you can:
1. Log in with your Google account
2. Enter postal codes and keywords
3. Search for businesses
4. View results in your Google Sheet

## Notes

- The script includes rate limiting to comply with API restrictions
- Email extraction attempts to find email addresses on business websites but may not always be successful
- The Google Sheet will be updated with new data in a new sheet

## Requirements

- Python 3.7+
- Google Cloud Platform account
- Google Maps API key
- Google Service Account credentials
- Google Sheet 