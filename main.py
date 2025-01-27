import os
import socket
import io
import os.path
import re
import time
from datetime import datetime, timedelta
import geocoder
import pandas as pd
import pytz
from PIL import Image
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
import random
import requests
import logging
import traceback
# fix for issues on 1/20/2023
# selenium 3 not compatible with python 3
# stackover flow link with info: https://stackoverflow.com/questions/65323114/robotframework-choose-file-causes-attributeerror-module-base64-has-no-attri
import base64
base64.encodestring = base64.encodebytes


# Selenium Grid and dynamic hostname setup
GRID_URL = os.getenv("GRID_URL", "http://selenium-hub:4444/wd/hub")
MACHINE_NAME = os.getenv("MACHINE_NAME", socket.gethostname())

# Google API Scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']


from dotenv import load_dotenv

load_dotenv()


SLACK_TOKEN = os.getenv('SLACK_TOKEN')
SLACK_CHANNEL_USER_ID = os.getenv('SLACK_CHANNEL_USER_ID')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL')
HEREMAP_API_KEY = os.getenv('HEREMAP_API_KEY')

def log_in():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def uploadImages(driver, post_data):
    creds = log_in()
    service = build('drive', 'v3', credentials=creds)
    print(post_data[-1])
    folder_id = post_data[-1].split('?')[0].split('/')[-1]
    results = service.files().list(
        pageSize=10, q=f"'{folder_id}' in parents", fields="nextPageToken, files(id, name)").execute()

    items = results.get('files', [])
    if not items:
        print('No files found.')
    else:
        random.shuffle(items)
        for item in items:
            extension = os.path.splitext(item['name'])[1]
            request = service.files().get_media(fileId=item['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            byteImg = Image.open(fh)
            if byteImg.mode in ("RGBA", "P"):
                byteImg = byteImg.convert("RGB")
            byteImg.save('currentImg' + extension)
            driver.find_element(By.XPATH, '//*[@id="uploader"]/form/input[3]').send_keys('currentImg' + extension)
            os.remove('currentImg' + extension)


def fixed_keys(keys_to_send):
    return re.split('[^a-zA-Z]', keys_to_send)[0]

def pull_tasks():
    spreadsheet_id = GOOGLE_SHEET_ID
    range_name = '2:1000'
    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    tasks = result.get('values', [])
    return tasks

def set_up_browser():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--headless')
    options.add_argument('--disable-blink-features=AutomationControlled')
    driver = webdriver.Remote(command_executor=GRID_URL, options=options)
    print(f"Browser launched on {MACHINE_NAME}")
    return driver

def send_slack_dm(txtToSend):
    data = {
        'token': SLACK_TOKEN,
        'channel': SLACK_CHANNEL_USER_ID,
        'as_user': True,
        'text': txtToSend
    }
    requests.post(url='https://slack.com/api/chat.postMessage',
                  data=data)

def get_post_data(link):
    # The ID and range of a sample spreadsheet.
    SAMPLE_SPREADSHEET_ID = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
    SAMPLE_RANGE_NAME = 'PostData!2:3000'

    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)
    # Call the Sheets API
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID,
                                range=SAMPLE_RANGE_NAME).execute()
    tasks = result.get('values', [])
    df = pd.DataFrame(tasks)
    df = df[df[0] == link]
    df = df.replace([''], [None])
    return df.values.tolist()[0]

def post(listing_data, driver):
    # Go to the link
    driver.get('https://accounts.craigslist.org/login/')

    # Log in
    # print(listing_data[2])
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.implicitly_wait(1.5)
    # print(listing_data[3])
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.implicitly_wait(1.5)
    driver.find_element(By.ID, 'login').click()
    # print('It clicked on login')

    update_stats(listing_data, driver)

    # Go back to the main page
    driver.get('https://newyork.craigslist.org/')

    # click on create a post
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.cl-thumb-anchor.cl-goto-post'))).click()

    # Get the data for the post
    post_data = get_post_data(listing_data[1])

    print(post_data, 'data to post===>>>')


    # Select location
    # driver.find_element(By.XPATH, f"//*[contains(text(), '{post_data[1]}')]").click()

    try:
        driver.find_element(By.XPATH, f"//*[contains(text(), '{post_data[1]}')]").click()
    except NoSuchElementException:
        print(f"Could not find location option: {post_data[1]}")
        # Optionally interact with the submit button div as a fallback
        try:
            submit_button = driver.find_element(By.CSS_SELECTOR, '.submit_button .pickbutton')
            submit_button.click()

            submit_button = driver.find_element(By.CSS_SELECTOR, '.submit_button .pickbutton')
            submit_button.click()

            driver.find_element(By.XPATH, f"//*[contains(text(), '{post_data[1]}')]").click()

        except Exception as e:
            print(f"Error interacting with fallback submit button: {e}")
            return

    # Deal with another location question
    try:
        if driver.find_element(By.CSS_SELECTOR, '.label').text == 'choose the location that fits best:':
            if post_data[2]:
                driver.find_element(By.XPATH, f"//*[contains(text(), '{post_data[2]}')]").click()
            else:
                driver.find_element(By.XPATH, f"//*[contains(text(), 'bypass this step')]").click()
    except NoSuchElementException:
        pass

    # Select the housing category
    driver.find_element(By.XPATH, f"//*[contains(text(), 'housing offered')]").click()

    # If category is given use that category
    if post_data[3]:
        category = post_data[3]
        driver.find_element(By.XPATH, f"//*[contains(text(), '{post_data[3]}')]").click()
    # If not, use the one with the least active posts
    else:
        accounts = get_account_data()
        accounts = accounts[accounts['Email'] == listing_data[2]]
        category = accounts[['Active listings in rooms & shares',
                             'Active listings in vacation rentals',
                             'Active listings in sublets & temporary']].apply(pd.to_numeric).idxmin(axis=1)
        category = category.tolist()[0].split(' ')[-1]
        driver.find_element(By.XPATH, f"//*[contains(text(), '{category}')]").click()

    # Fix Categories
    if category == 'shares':
        category = 'rooms & shares'
    if category == 'temporary':
        category = 'sublets & temporary'
    if category == 'rentals':
        category = 'vacation rentals'

    # Set the title
    driver.find_element(By.CSS_SELECTOR, '#PostingTitle').send_keys(post_data[4])

    # Set description
    driver.find_element(By.CSS_SELECTOR, '#PostingBody').send_keys(post_data[6])

    # Set Zip
    driver.find_element(By.CSS_SELECTOR, '#postal_code').send_keys(post_data[7])

    # Set sqft if we have info
    if post_data[8]:
        driver.find_element(By.CSS_SELECTOR, '.surface_area .json-form-input').clear()
        driver.find_element(By.CSS_SELECTOR, '.surface_area .json-form-input').send_keys(post_data[8])

    # Cats
    if post_data[16] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, '.variant-checkbox .pets_cat').click()

    # Dogs
    if post_data[17] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .pets_dog").click()

    # Furnished
    if post_data[18] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .is_furnished").click()
    # No smoking
    if post_data[19] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .no_smoking").click()

    # Wheel
    if post_data[20] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .wheelchaccess").click()

    # Air
    if post_data[21] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .airconditioning").click()

    # EV
    if post_data[22] == 'TRUE':
        driver.find_element(By.CSS_SELECTOR, ".variant-checkbox .ev_charging").click()

    # Available on:
    if post_data[23]:
        driver.find_element(By.CSS_SELECTOR, '.hasDatepicker').send_keys(post_data[23])

    # Street and City
    if post_data[24] or post_data[25]:
        driver.find_element(By.CSS_SELECTOR, '.variant-checkbox .show_address_ok').click()
        if post_data[24]:
            driver.find_element(By.CSS_SELECTOR, '.xstreet0 .json-form-input').send_keys(post_data[24])
        if post_data[25]:
            driver.find_element(By.CSS_SELECTOR, '.city .json-form-input').send_keys(post_data[25])

    # Rent
    if post_data[5]:
        driver.find_element(By.CSS_SELECTOR, '.short-input .json-form-input').send_keys(post_data[5])

    if category == 'vacation rentals':

        # Laundry
        driver.find_element(By.CSS_SELECTOR, '#ui-id-3-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-3-menu').send_keys(fixed_keys(post_data[11]))
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-3-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Apt type
        if post_data[26]:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-1-button .ui-selectmenu-text').click()
            driver.find_element(By.CSS_SELECTOR, '#ui-id-1-menu').send_keys(fixed_keys(post_data[26]))
            try:
                driver.find_element(By.CSS_SELECTOR, '#ui-id-1-menu').send_keys(Keys.ENTER)
            except:
                pass

        # Parking
        driver.find_element(By.CSS_SELECTOR, '#ui-id-4-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-4-menu').send_keys(fixed_keys(post_data[12]))
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-4-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Bedrooms
        driver.find_element(By.CSS_SELECTOR, '#ui-id-5-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-5-menu').send_keys(post_data[13])
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-5-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Bathrooms
        driver.find_element(By.CSS_SELECTOR, '#ui-id-6-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-6-menu').send_keys(post_data[14])
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-6-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Rent Period
        if post_data[15]:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-1-button .ui-selectmenu-text').click()
            driver.find_elements(By.XPATH, f"//*[contains(text(), '{post_data[15]}')]")[1].click()

    if category == 'rooms & shares' or category == 'sublets & temporary':

        # Laundry
        driver.find_element(By.CSS_SELECTOR, '#ui-id-5-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-5-menu').send_keys(fixed_keys(post_data[11]))
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-5-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Private Room
        driver.find_element(By.CSS_SELECTOR, '#ui-id-2-button .ui-selectmenu-text').click()
        driver.implicitly_wait(5)
        if post_data[9] == "TRUE":
            driver.find_elements(By.XPATH, f"//*[text() = 'private room']")[2].click()
        else:
            driver.find_elements(By.XPATH, f"//*[text() = 'room not private']")[1].click()

        # Private Bath
        driver.find_element(By.CSS_SELECTOR, '#ui-id-4-button .ui-selectmenu-text').click()
        driver.implicitly_wait(5)
        if post_data[10] == "TRUE":
            driver.find_elements(By.XPATH, f"//*[text() = 'private bath']")[2].click()
        else:
            driver.find_elements(By.XPATH, f"//*[text() = 'no private bath']")[1].click()

        # Apt type
        if post_data[26]:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-3-button .ui-selectmenu-text').click()
            driver.find_element(By.CSS_SELECTOR, '#ui-id-3-menu').send_keys(fixed_keys(post_data[26]))
            try:
                driver.find_element(By.CSS_SELECTOR, '#ui-id-3-menu').send_keys(Keys.ENTER)
            except:
                pass

        # Parking
        driver.find_element(By.CSS_SELECTOR, '#ui-id-6-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-6-menu').send_keys(fixed_keys(post_data[12]))
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-6-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Bedrooms
        driver.find_element(By.CSS_SELECTOR, '#ui-id-7-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-7-menu').send_keys(post_data[13])
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-7-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Bathrooms
        driver.find_element(By.CSS_SELECTOR, '#ui-id-8-button .ui-selectmenu-text').click()
        driver.find_element(By.CSS_SELECTOR, '#ui-id-8-menu').send_keys(post_data[14])
        try:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-8-menu').send_keys(Keys.ENTER)
        except:
            pass

        # Rent Period
        if post_data[15]:
            driver.find_element(By.CSS_SELECTOR, '#ui-id-1-button .ui-selectmenu-text').click()
            # driver.find_element(By.XPATH, f"//option[contains(text(), '{post_data[15]}')]").click()
            print(driver.find_elements(By.XPATH, f"//*[contains(text(), '{post_data[15]}')]"))
            driver.find_elements(By.XPATH, f"//*[contains(text(), '{post_data[15]}')]")[1].click()

    # Submit
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, '.submit-button'))).click()

    # Approve Location
    # Deal with New Jersey
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, '.bigbutton'))).click()
    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, '.medium-pickbutton+ .medium-pickbutton'))).click()
    except:
        pass

    # Set Up image upload button
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, '#classic'))).click()

    # Upload images
    uploadImages(driver, post_data)

    # Submit
    WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'button#doneWithImages.bigbutton'))).click()

    # Post
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, '.button'))).click()

    #tell slack which machine posted
    import requests
    import json
    webhookZap = f"{WEBHOOK_BASE_URL}?computername="
    print(listing_data[5])
    webhook_url = f"{webhookZap}{str(listing_data[5])}"
    requests.post(webhook_url, headers={'Content-Type': 'application/json'})



    # Update spreadsheet
    host = listing_data[4]
    # link = driver.find_element(By.XPATH, '//*[@id="new-edit"]/div/div/ul/li[2]/a').get_attribute('href')
    # link = driver.find_element(By.XPATH, '//ul[@class="ul"]/li[2]/a').get_attribute('href')

    try:
        link = driver.find_element(By.XPATH, '//ul[@class="ul"]/li[2]/a').get_attribute('href')

        curr_time = datetime.now(pytz.timezone('America/New_York')).strftime("%H:%M")
        location = f"{post_data[2]}, {post_data[1].capitalize()}" if post_data[2] is not None else post_data[1].capitalize()
        today_date = datetime.now(pytz.timezone('America/New_York')).strftime("%m/%d")
        output = [host, listing_data[1], 'Post', category, link, location,
                  today_date, curr_time, listing_data[5], '-', '-', '-', listing_data[2]]

        # Update account stats
        update_stats(listing_data, driver)

        # Close browser
        driver.quit()

        return output

    except NoSuchElementException:
        print(f"Could not post successfully")
        driver.quit()




def renew(listing_data, driver):
    # Go to the link
    driver.get('https://accounts.craigslist.org/login/')

    # Log in
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.implicitly_wait(1.5)
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.implicitly_wait(1.5)
    driver.find_element(By.ID, 'login').click()

    # Go to the old listing
    driver.get(listing_data[1])

    # Get listing data
    lat = driver.find_element(By.ID, 'map').get_attribute("data-latitude")
    long = driver.find_element(By.ID, 'map').get_attribute("data-longitude")

    location = get_location(lat, long)


    category = driver.find_element(By.CSS_SELECTOR, '.category p').text
    category = category.replace('>', "")
    category = category.replace('<', "")
    category = category.strip()
    # g = geocoder.mapquest([lat, long], method='reverse', key='b7bow6CgalFYwE56sSxA4JT6BpOGqsHU')
    # location = g.osm['addr:city'] + ', ' + g.osm['addr:state']
    curr_time = datetime.now(pytz.timezone('America/New_York')).strftime("%H:%M")
    today_date = datetime.now(pytz.timezone('America/New_York')).strftime("%m/%d")
    host = listing_data[4]
    title = driver.find_element(By.XPATH, '//*[@id="titletextonly"]').text

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//*[@id="manage-posting"]/div[1]/table/tbody/tr[6]/td[1]/div/form/input[3]'))).click()
    except:
        print(f'Error, check if {listing_data[1]} is already reposted')

    time.sleep(3)
    update_stats(listing_data, driver)

    new_link = driver.find_elements(By.XPATH, f"//*[contains(text(), '{title}')]")[0].get_attribute('href')
    driver.quit()

    # Return updated listing
    output = [host, listing_data[1], 'Renew', category, new_link, location,
              today_date, curr_time, listing_data[5], '-', '-', '-', listing_data[2]]

    # tell slack which machine posted
    import requests
    import json

    webhookZap = f"{WEBHOOK_BASE_URL}?computername="
    print(listing_data[5])
    webhook_url = f"{webhookZap}{str(listing_data[5])} renewal"
    requests.post(webhook_url, headers={'Content-Type': 'application/json'})

    return output

def repost(listing_data, driver):
    if len(listing_data) < 6:
        print(
            f'Listing: {listing_data} is invalid. The code requires a row to have a task, link, email, password,'
            f'host name, and the computer used to make the post. In that order.')

    # Go to the link #driver.get(listing_data[0])
    driver.get('https://accounts.craigslist.org/login/')

    # Log in
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.implicitly_wait(1.5)
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.implicitly_wait(1.5)
    driver.find_element(By.ID, 'login').click()

    # Go to the old listing
    driver.get(listing_data[1])

    lat = driver.find_element(By.ID, 'map').get_attribute("data-latitude")
    long = driver.find_element(By.ID, 'map').get_attribute("data-longitude")
    category = driver.find_element(By.CSS_SELECTOR, '.category p').text
    category = category.replace('>', "")
    category = category.replace('<', "")
    category = category.strip()
    # g = geocoder.mapquest([lat, long], method='reverse', key="b7bow6CgalFYwE56sSxA4JT6BpOGqsHU")

    # location = g.osm['addr:city'] + ', ' + g.osm['addr:state']

    location = get_location(lat, long)

    # Repost
    driver.find_element(By.CSS_SELECTOR, '.managebtn').click()
    driver.implicitly_wait(3)
    driver.find_element(By.CSS_SELECTOR, '.submit-button').click()

    # Publish
    driver.find_element(By.CSS_SELECTOR, '.button').click()

    # Get new link
    driver.implicitly_wait(5)
    # link = driver.find_element(By.XPATH, '//*[@id="new-edit"]/div/div/ul/li[2]/a').get_attribute('href')
    # link = driver.find_element(By.XPATH, '//ul[@class="ul"]/li[2]/a').get_attribute('href')

    try:
        link = driver.find_element(By.XPATH, '//ul[@class="ul"]/li[2]/a').get_attribute('href')

        # Update account stats
        update_stats(listing_data, driver)

        # Close browser
        driver.quit()

        # Return updated listing
        curr_time = datetime.now(pytz.timezone('America/New_York')).strftime("%H:%M")
        today_date = datetime.now(pytz.timezone('America/New_York')).strftime("%m/%d")
        host = listing_data[4]
        output = [host, listing_data[1], 'Repost', category, link, location,
                  today_date, curr_time, listing_data[5], '-', '-', '-', listing_data[2]]

        # tell slack which machine reposted
        import requests
        import json
        import json

        webhookZap = f"{WEBHOOK_BASE_URL}?computername="
        print(listing_data[5])
        webhook_url = f"{webhookZap}{str(listing_data[5])} repost"

        requests.post(webhook_url, headers={'Content-Type': 'application/json'})

        return output

    except NoSuchElementException:
        print(f"Could not post successfully")
        driver.quit()


def get_location(lat, long):
    url = "https://revgeocode.search.hereapi.com/v1/revgeocode"
    params = {
        "at": f"{lat},{long}",
        "lang": "en-US",  # Language for the response
        "apikey": HEREMAP_API_KEY,
        "mode": 'retrieveAddresses'
    }

    import requests
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    location = ''

    if data.get("items"):
        address = data["items"][0].get("address", {})
        city = address.get("city", "")
        state = address.get("state", "")

        # Build the location string
        if city and state:
            location = f"{city}, {state}"
        elif city:
            location = city
        elif state:
            location = state
        else:
            location = "Location not found"

    return location

# def update(listing_data_updated):
#     # The ID and range of a sample spreadsheet.
#     SAMPLE_SPREADSHEET_ID = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
#     SAMPLE_RANGE_NAME = 'Results!2:1000'
#     creds = log_in()
#     service = build('sheets', 'v4', credentials=creds)
#     body = {
#         'values': listing_data_updated
#     }
#
#     # Update new sheet
#     result = service.spreadsheets().values().append(
#         spreadsheetId=SAMPLE_SPREADSHEET_ID, range=SAMPLE_RANGE_NAME,
#         valueInputOption='RAW', body=body).execute()
#     print('{0} cells appended to the new sheet.'.format(result
#                                                         .get('updates')
#                                                         .get('updatedCells')))
#
#     # Update old sheet
#     old_SPREADSHEET_ID = '1Juftetgo4c2i9SmFkAE9QvE0fVQdpQDZIKziQ8EJSjw'
#     old_RANGE_NAME = 'Enumerated Postings!2:1000'
#     result = service.spreadsheets().values().append(
#         spreadsheetId=old_SPREADSHEET_ID, range=old_RANGE_NAME,
#         valueInputOption='RAW', body=body).execute()
#     print('{0} cells appended to the old sheet.'.format(result
#                                                         .get('updates')
#                                                         .get('updatedCells')))

def update(listing_data_updated):
    # Ensure the data is in a list of lists format
    if not isinstance(listing_data_updated, list) or not all(isinstance(row, list) for row in listing_data_updated):
        # Wrap the single row in another list if it's flat
        listing_data_updated = [listing_data_updated]

    SAMPLE_SPREADSHEET_ID = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
    SAMPLE_RANGE_NAME = 'Results!2:1000'
    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)

    # Verify the data structure before sending
    print("Data to be appended to the new sheet:", listing_data_updated)

    # Prepare the request body
    body = {
        'values': listing_data_updated
    }

    try:
        # Append data to the new sheet
        result = service.spreadsheets().values().append(
            spreadsheetId=SAMPLE_SPREADSHEET_ID,
            range=SAMPLE_RANGE_NAME,
            valueInputOption='RAW',
            body=body
        ).execute()
        print('{0} cells appended to the new sheet.'.format(result.get('updates').get('updatedCells')))

        # Append data to the old sheet
        old_SPREADSHEET_ID = '1Juftetgo4c2i9SmFkAE9QvE0fVQdpQDZIKziQ8EJSjw'
        old_RANGE_NAME = 'Enumerated Postings!2:1000'

        print("Data to be appended to the old sheet:", listing_data_updated)
        result = service.spreadsheets().values().append(
            spreadsheetId=old_SPREADSHEET_ID,
            range=old_RANGE_NAME,
            valueInputOption='RAW',
            body=body
        ).execute()
        print('{0} cells appended to the old sheet.'.format(result.get('updates').get('updatedCells')))

    except Exception as e:
        print("An error occurred:", e)


def wait_until(target_time):
    """
    Wait until the specified target time.

    Parameters:
        target_time (datetime): The time to wait until.
    """
    timezone = pytz.timezone("America/New_York")

    # Ensure target_time is timezone-aware
    if target_time.tzinfo is None:
        target_time = timezone.localize(target_time)

    print("Current Time (with timezone):", datetime.now(timezone))
    print("Target Time (with timezone):", target_time)

    while datetime.now(timezone) < target_time:
        print(f"Waiting... Current time: {datetime.now(timezone)}, Target time: {target_time}")
        time.sleep(10)  # Sleep for 10 seconds

    print("Target time reached:", datetime.now(timezone))


def main():
    tasks = pull_tasks()
    for row_num, task in enumerate(tasks):
        try:
            if len(task) not in [6, 7]:
                print(f"Skipping invalid task at row {row_num}")
                continue

            timezone = pytz.timezone("America/New_York")
            current_time = datetime.now(timezone)

            # Format and display the current time
            print("Current Time:", current_time.strftime("%H:%M:%S"))

            # Check for scheduling if task length is 7
            if len(task) == 7:
                time_col = 6
                try:
                    print('Checking scheduled time...')
                    post_time = datetime.strptime(task[time_col], '%m/%d/%Y %H:%M:%S')
                    print(f"Task scheduled for: {post_time}")

                    # exit()
                    wait_until(post_time)  # Wait until the scheduled time
                    print("Time reached, proceeding with task...")
                except Exception as e:
                    print(f"Invalid scheduled time format at row {row_num}: {e}")
                    traceback.print_exc()
                    continue

            driver = set_up_browser()
            task_type = task[0].lower()
            print(task, "====>>>")
            if task_type == 'post':
                task_result = post(task, driver)
            elif task_type == 'renew':
                task_result = renew(task, driver)
            elif task_type == 'repost':
                task_result = repost(task, driver)
            else:
                print(f"Unknown task type: {task_type}")
                continue
            print(task_result, "Task added successfully.")
            update(task_result)
            driver.quit()
        except Exception as e:
            print(f"Error processing task at row {row_num}: {e}")
            traceback.print_exc()
            send_slack_dm(f"Task {task} just threw an error \n {traceback.format_exc()}")
            try:
                driver.quit()
            except:
                pass




def get_account_data():
    # The ID and range of a sample spreadsheet.
    SAMPLE_SPREADSHEET_ID = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
    'AccountData!2:1000'

    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)
    # Call the Sheets API
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SAMPLE_SPREADSHEET_ID,
                                range='AccountData!1:1000').execute()
    data = result.get('values')
    df = pd.DataFrame(data[1:], columns=data[0])
    df = df.replace([''], [None])
    return df


""" Updates the sheet with the number of current active, flagged, and expired listings """


def update_stats(listing_data, driver):
    # The ID and range of a sample spreadsheet.
    SAMPLE_SPREADSHEET_ID = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
    SAMPLE_RANGE_NAME = 'AccountData!1:1000'
    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)
    driver.get('https://accounts.craigslist.org/login/home')
    time.sleep(3)
    driver.refresh()
    email = listing_data[2]
    total_posts = len(driver.find_elements(By.CSS_SELECTOR, '.gc')) / 2
    active_listings = len(driver.find_elements(By.CSS_SELECTOR, '.active .gc')) / 2
    removed_listings = len(driver.find_elements(By.CSS_SELECTOR, '.removed .gc')) / 2
    expired_listings = len(driver.find_elements(By.CSS_SELECTOR, '.expired .gc')) / 2
    active_listings_categories = [el.text.strip() for el in driver.find_elements(By.CSS_SELECTOR, '.areacat.active')]

    count_rooms_shares = 0
    count_vacation_rentals = 0
    count_sublets_temporary = 0
    for element in active_listings_categories:
        if 'rooms & shares' in element:
            count_rooms_shares += 1
        if 'vacation rentals' in element:
            count_vacation_rentals += 1
        if 'sublets & temporary' in element:
            count_sublets_temporary += 1
    update_for_accounts = [email, total_posts, active_listings,
                           count_rooms_shares, count_vacation_rentals,
                           count_sublets_temporary, expired_listings, removed_listings]
    df = get_account_data()
    if email not in df.Email.values:
        body = {
            'values': [update_for_accounts]
        }
        service.spreadsheets().values().append(
            spreadsheetId=SAMPLE_SPREADSHEET_ID, range=SAMPLE_RANGE_NAME,
            valueInputOption='RAW', body=body).execute()
    else:
        df.loc[df['Email'] == email, ['Email', 'Total Posts', 'Active Listings',
                                      'Active listings in rooms & shares',
                                      'Active listings in vacation rentals',
                                      'Active listings in sublets & temporary', 'Number of expired listings',
                                      'Times flagged']] = update_for_accounts
        data = [df.columns.values.tolist()]
        data.extend(df.values.tolist())
        value_range_body = {"values": data}
        service.spreadsheets().values().update(spreadsheetId=SAMPLE_SPREADSHEET_ID, range=SAMPLE_RANGE_NAME,
                                               valueInputOption='RAW', body=value_range_body).execute()

# Run the code
logging.basicConfig(filename='test.log', level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)
try:
    main()
except Exception as bigErr:
    send_slack_dm(f"Error {traceback.format_exc()} just occurred")
    logger.error(bigErr)