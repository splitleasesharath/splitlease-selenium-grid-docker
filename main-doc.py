import os
import re
import time
import traceback
import socket
from datetime import datetime
import requests
import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from google.auth.transport.requests import Request

import io
import os.path
import re
import shutil
import sys
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
    spreadsheet_id = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
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


def post(listing_data, driver):
    # Example logic for posting a new listing
    driver.get('https://accounts.craigslist.org/login/')
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.find_element(By.ID, 'login').click()

    # Example steps for posting a listing
    # Replace these with your specific Craigslist posting flow
    print(f"Posting task: {listing_data}")
    return {
        'status': 'success',
        'machine': MACHINE_NAME,
        'task': listing_data[0]
    }

def renew(listing_data, driver):
    # Example logic for renewing a listing
    driver.get('https://accounts.craigslist.org/login/')
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.find_element(By.ID, 'login').click()

    # Navigate to the listing and renew it
    print(f"Renewing task: {listing_data}")
    return {
        'status': 'renewed',
        'machine': MACHINE_NAME,
        'task': listing_data[0]
    }

def repost(listing_data, driver):
    # Example logic for reposting a listing
    driver.get('https://accounts.craigslist.org/login/')
    driver.find_element(By.ID, 'inputEmailHandle').send_keys(listing_data[2])
    driver.find_element(By.ID, 'inputPassword').send_keys(listing_data[3])
    driver.find_element(By.ID, 'login').click()

    # Navigate to the listing and repost it
    print(f"Reposting task: {listing_data}")
    return {
        'status': 'reposted',
        'machine': MACHINE_NAME,
        'task': listing_data[0]
    }

def update(task_result):
    print(task_result, "task_result===>>>")
    spreadsheet_id = '1eBxVRTIfnHO1miRg6grcNrprMGDZ7dvIGrEoFNDTxio'
    range_name = 'Results!2:1000'
    creds = log_in()
    service = build('sheets', 'v4', credentials=creds)
    body = {'values': [[task_result['machine'], task_result['task'], task_result['status']]]}
    print(body,"====================>>")
    result = service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id, range=range_name, valueInputOption='RAW', body=body).execute()
    print(f"Updated task results: {result}")

def main():
    tasks = pull_tasks()
    for row_num, task in enumerate(tasks):
        try:
            if len(task) not in [6, 7]:
                print(f"Skipping invalid task at row {row_num}")
                continue
            driver = set_up_browser()
            task_type = task[0].lower()
            if task_type == 'post':
                task_result = post(task, driver)
            elif task_type == 'renew':
                task_result = renew(task, driver)
            elif task_type == 'repost':
                task_result = repost(task, driver)
            else:
                print(f"Unknown task type: {task_type}")
                continue
            print(task_result, "task added successfully====>>>>>>")
            update(task_result)
            driver.quit()
        except Exception as e:
            print(f"Error processing task at row {row_num}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main()
