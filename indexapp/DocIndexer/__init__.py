import logging
import re

import azure.functions as func


import os
import io
import html
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
SEARCH_INDEX = os.getenv("CHAT_SEARCH_INDEX")
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER")
STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
FORM_RECOGNIZER_SERVICE = os.getenv("FORM_RECOGNIZER_SERVICE")
FORM_RECOGNIZER_KEY = os.getenv("FORM_RECOGNIZER_KEY")
from azure.ai.formrecognizer import DocumentAnalysisClient

default_creds = DefaultAzureCredential()

# Use the current user identity to connect to Azure services unless a key is explicitly set for any of them
search_creds = default_creds if SEARCH_KEY is None else AzureKeyCredential(SEARCH_KEY)
formrecognizer_creds = (
    default_creds
    if FORM_RECOGNIZER_KEY is None
    else AzureKeyCredential(FORM_RECOGNIZER_KEY)
)


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
    page_map = get_document_text(blob)
    sections = create_sections(os.path.basename(filename), page_map)
    index_sections(os.path.basename(filename), sections)
    upload_blobs(filename)


def blob_name_from_file_page(filename, page=0):
    if os.path.splitext(filename)[1].lower() == ".pdf":
        return os.path.splitext(os.path.basename(filename))[0] + f"-{page}" + ".pdf"
    else:
        return os.path.basename(filename)


def table_to_html(table):
    table_html = "<table>"
    rows = [
        sorted(
            [cell for cell in table.cells if cell.row_index == i],
            key=lambda cell: cell.column_index,
        )
        for i in range(table.row_count)
    ]
    for row_cells in rows:
        table_html += "<tr>"
        for cell in row_cells:
            tag = (
                "th"
                if (cell.kind == "columnHeader" or cell.kind == "rowHeader")
                else "td"
            )
            cell_spans = ""
            if cell.column_span > 1:
                cell_spans += f" colSpan={cell.column_span}"
            if cell.row_span > 1:
                cell_spans += f" rowSpan={cell.row_span}"
            table_html += f"<{tag}{cell_spans}>{html.escape(cell.content)}</{tag}>"
        table_html += "</tr>"
    table_html += "</table>"
    return table_html


def get_document_text(filename):
    offset = 0
    page_map = []
    form_recognizer_client = DocumentAnalysisClient(
        endpoint=f"https://{FORM_RECOGNIZER_SERVICE}.cognitiveservices.azure.com/",
        credential=formrecognizer_creds,
        headers={"x-ms-useragent": "azure-search-chat-demo/1.0.0"},
    )
    poller = form_recognizer_client.begin_analyze_document(
        "prebuilt-layout", document=filename
    )
    form_recognizer_results = poller.result()

    for page_num, page in enumerate(form_recognizer_results.pages):
        tables_on_page = [
            table
            for table in form_recognizer_results.tables
            if table.bounding_regions[0].page_number == page_num + 1
        ]

        # mark all positions of the table spans in the page
        page_offset = page.spans[0].offset
        page_length = page.spans[0].length
        table_chars = [-1] * page_length
        for table_id, table in enumerate(tables_on_page):
            for span in table.spans:
                # replace all table spans with "table_id" in table_chars array
                for i in range(span.length):
                    idx = span.offset - page_offset + i
                    if idx >= 0 and idx < page_length:
                        table_chars[idx] = table_id

        # build page text by replacing charcters in table spans with table html
        page_text = ""
        added_tables = set()
        for idx, table_id in enumerate(table_chars):
            if table_id == -1:
                page_text += form_recognizer_results.content[page_offset + idx]
            elif not table_id in added_tables:
                page_text += table_to_html(tables_on_page[table_id])
                added_tables.add(table_id)

        page_text += " "
        page_map.append((page_num, offset, page_text))
        offset += len(page_text)

    return page_map


def split_text(page_map):
    SENTENCE_ENDINGS = [".", "!", "?"]
    WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]

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

        section_text = all_text[start:end]
        yield (section_text, find_page(start))

        last_table_start = section_text.rfind("<table")
        if (
            last_table_start > 2 * SENTENCE_SEARCH_LIMIT
            and last_table_start > section_text.rfind("</table")
        ):
            # If the section ends with an unclosed table, we need to start the next section with the table.
            # If table starts inside SENTENCE_SEARCH_LIMIT, we ignore it, as that will cause an infinite loop for tables longer than MAX_SECTION_LENGTH
            # If last table starts inside SECTION_OVERLAP, keep overlapping
            start = min(end - SECTION_OVERLAP, start + last_table_start)
        else:
            start = end - SECTION_OVERLAP


def create_sections(filename, page_map):
    for i, (section, pagenum) in enumerate(split_text(page_map)):
        yield {
            "id": re.sub("[^0-9a-zA-Z_-]", "_", f"{filename}-{i}"),
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
            results = search_client.upload_documents(documents=batch)
            succeeded = sum([1 for r in results if r.succeeded])
            batch = []

    if len(batch) > 0:
        results = search_client.upload_documents(documents=batch)
        succeeded = sum([1 for r in results if r.succeeded])


def upload_blobs(filename):
    blob_service = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=default_creds,
    )
    blob_container = blob_service.get_container_client(CONTAINER)
    if not blob_container.exists():
        blob_container.create_container()
    blob_name = blob_name_from_file_page(filename)
    with open(filename, "rb") as data:
        blob_container.upload_blob(blob_name, data, overwrite=True)
