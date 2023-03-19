import logging
import os
import time
import re

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient

SEARCH_KEY = os.getenv("SEARCH_KEY")
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
SEARCH_INDEX = os.getenv("SEARCH_INDEX")
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")
STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")

default_cred = DefaultAzureCredential()
search_creds = AzureKeyCredential(SEARCH_KEY)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    filename = req.params.get("filename")

    logging.info(f"Processing remove request for {filename}.")
    failure_msg = "Error encountered during removal"
    try:
        if filename:
            if filename == "ALL":
                failure_msg += " of all files."
                remove_blobs(None)
                remove_from_index(None)
                success_msg = f"All file successfully removed from index."
            else:
                failure_msg += " of all file {filename}."
                remove_blobs(filename)
                remove_from_index(filename)
                success_msg = f"File {filename} successfully removed from index."
            return func.HttpResponse(success_msg, status_code=200)
        else:
            return func.HttpResponse(
                "'filename' must be provided in the request url.", status_code=400
            )

    except:
        return func.HttpResponse(failure_msg, status_code=500)


def remove_from_index(filename):
    search_client = SearchClient(
        endpoint=f"https://{SEARCH_SERVICE}.search.windows.net/",
        index_name=SEARCH_INDEX,
        credential=search_creds,
    )
    while True:
        filter = (
            None
            if filename == None
            else f"sourcefile eq '{os.path.basename(filename)}'"
        )
        r = search_client.search("", filter=filter, top=1000, include_total_count=True)
        if r.get_count() == 0:
            break
        r = search_client.delete_documents(documents=[{"id": d["id"]} for d in r])
        # It can take a few seconds for search results to reflect changes, so wait a bit
        time.sleep(2)


def remove_blobs(filename):
    blob_service = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=default_cred,
    )
    blob_container = blob_service.get_container_client(CONTAINER)
    if blob_container.exists():
        if filename == None:
            blobs = blob_container.list_blob_names()
        else:
            prefix = os.path.splitext(os.path.basename(filename))[0]
            blobs = filter(
                lambda b: re.match(f"{prefix}-\d+\.pdf", b),
                blob_container.list_blob_names(
                    name_starts_with=os.path.splitext(os.path.basename(prefix))[0]
                ),
            )
        for b in blobs:
            blob_container.delete_blob(b)
