import logging

import azure.functions as func


import os
import io
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents.indexes.models import *
from azure.search.documents import SearchClient

MAX_SECTION_LENGTH = 1000
SENTENCE_SEARCH_LIMIT = 100
SECTION_OVERLAP = 100

SEARCH_KEY = os.getenv("SEARCH_KEY")
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
SEARCH_INDEX = os.getenv("SEARCH_INDEX")
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")
STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")

default_cred = DefaultAzureCredential()

# Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
search_creds = AzureKeyCredential(SEARCH_KEY)


def main(myblob: func.InputStream):
    logging.info(
        f"Python blob trigger function processed blob \n"
        f"Name: {myblob.name}\n"
        f"Blob Size: {myblob.length} bytes"
    )

    filename = myblob.name
    blob = BytesIO()
    blob.write(myblob.read())
    blob.seek(0)
    reader = PdfReader(blob)
    pages = reader.pages
    sections = create_sections(os.path.basename(filename), pages)
    index_sections(os.path.basename(filename), sections)
    upload_blobs(pages, filename)


def blob_name_from_file_page(filename, page):
    return os.path.splitext(os.path.basename(filename))[0] + f"-{page}" + ".pdf"


def split_text(pages):
    SENTENCE_ENDINGS = [".", "!", "?"]
    WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]

    page_map = []
    offset = 0
    for i, p in enumerate(pages):
        text = p.extract_text()
        page_map.append((i, offset, text))
        offset += len(text)

    def find_page(offset):
        l = len(page_map)
        for i in range(l - 1):
            if offset >= page_map[i][1] and offset < page_map[i + 1][1]:
                return i
        return l - 1

    all_text = "".join(p[2] for p in page_map)
    length = len(all_text)
    start = 0
    end = length
    while start + SECTION_OVERLAP < length:
        last_word = -1
        end = start + MAX_SECTION_LENGTH

        if end > length:
            end = length
        else:
            # Try to find the end of the sentence
            while (
                end < length
                and (end - start - MAX_SECTION_LENGTH) < SENTENCE_SEARCH_LIMIT
                and all_text[end] not in SENTENCE_ENDINGS
            ):
                if all_text[end] in WORDS_BREAKS:
                    last_word = end
                end += 1
            if end < length and all_text[end] not in SENTENCE_ENDINGS and last_word > 0:
                end = last_word  # Fall back to at least keeping a whole word
        if end < length:
            end += 1

        # Try to find the start of the sentence or at least a whole word boundary
        last_word = -1
        while (
            start > 0
            and start > end - MAX_SECTION_LENGTH - 2 * SENTENCE_SEARCH_LIMIT
            and all_text[start] not in SENTENCE_ENDINGS
        ):
            if all_text[start] in WORDS_BREAKS:
                last_word = start
            start -= 1
        if all_text[start] not in SENTENCE_ENDINGS and last_word > 0:
            start = last_word
        if start > 0:
            start += 1

        yield (all_text[start:end], find_page(start))
        start = end - SECTION_OVERLAP

    if start + SECTION_OVERLAP < end:
        yield (all_text[start:end], find_page(start))


def create_sections(filename, pages):
    for i, (section, pagenum) in enumerate(split_text(pages)):
        yield {
            "id": f"{filename}-{i}".replace(".", "_").replace(" ", "_"),
            "content": section,
            "category": "general",
            "sourcepage": blob_name_from_file_page(filename, pagenum),
            "sourcefile": filename,
        }


def index_sections(filename, sections):
    search_client = SearchClient(
        endpoint=f"https://{SEARCH_SERVICE}.search.windows.net/",
        index_name=SEARCH_INDEX,
        credential=search_creds,
    )
    i = 0
    batch = []
    for s in sections:
        batch.append(s)
        i += 1
        if i % 1000 == 0:
            results = search_client.index_documents(batch=batch)
            succeeded = sum([1 for r in results if r.succeeded])
            batch = []

    if len(batch) > 0:
        results = search_client.upload_documents(documents=batch)
        succeeded = sum([1 for r in results if r.succeeded])


def upload_blobs(pages, filename):
    blob_service = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=default_cred,
    )
    blob_container = blob_service.get_container_client(CONTAINER)
    if not blob_container.exists():
        blob_container.create_container()
    for i in range(len(pages)):
        blob_name = blob_name_from_file_page(filename, i)
        f = io.BytesIO()
        writer = PdfWriter()
        writer.add_page(pages[i])
        writer.write(f)
        f.seek(0)
        blob_container.upload_blob(blob_name, f, overwrite=True)
